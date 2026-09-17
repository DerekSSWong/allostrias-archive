"""Building cache/stash.sqlite from the .gst files in the save directory.

REBUILT ON EVERY LAUNCH, unconditionally. The catalogue earns its staleness
check because rebuilding it costs minutes; this costs a few milliseconds
against five small files, and the files change every time the game is played.
A gate here would be more code than the work it avoided, and would introduce
the one failure the catalogue's gate exists to prevent -- a cache that reports
itself fresh while the thing it mirrors has moved.

PARSE EVERYTHING BEFORE WRITING ANYTHING. A save file caught mid-write by an
autosave must not leave a half-populated database behind, and the previous
build is a better answer than a partial one. So every file is read into memory
first, and the database is only touched once all of them have verified; the
write itself is a single transaction on top of that.
"""
import os

from . import apply_schema, connect
from ..archive import gst

SCHEMA_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'stash.sql')
SCHEMA_VERSION = '1'

# Emptied and refilled on every build, children first so the foreign key from
# stash_item to stash_page never dangles mid-transaction.
TABLES = ('stash_item', 'stash_page', 'reagent', 'source_file', 'build_meta')


def _read_all(saves_dir: str) -> list[tuple[str, str, dict]]:
    """[(path, kind, parsed)] for every stash file present, or a refusal.

    A file that will not parse raises. It is not skipped: a stash missing one
    of its four mode files looks exactly like a stash that never had it, and
    that is the difference between "you own no Aether Shards" and "the reader
    could not tell".
    """
    out = []
    for path in gst.save_files(saves_dir):
        kind = 'reagents' if os.path.basename(path).startswith('reagents') \
            else 'transfer'
        reader = gst.read_reagents if kind == 'reagents' else gst.read_transfer
        out.append((path, kind, reader(path)))
    return out


def _source_row(path: str, kind: str, parsed: dict) -> tuple:
    stat = os.stat(path)
    return (os.path.basename(path), kind, gst.mode_of(path), stat.st_size,
            stat.st_mtime_ns, parsed['file_version'], parsed['version'],
            parsed.get('expansion'), parsed['mod'])


def _blank(value: str) -> str | None:
    """'' means "no affix here". Stored as NULL so the fact has one spelling."""
    return value or None


def _cell(value: float, axis: str, base: str) -> int:
    """A grid coordinate, which the file stores as a float32.

    Every coordinate in a real stash is a whole number -- items sit on cells --
    so a fractional one means the tail was misread, not that the game invented
    half a column. int() would round it away and leave a database that looks
    perfectly ordinary, so it raises instead.
    """
    if value != int(value):
        raise ValueError(f'{base}: {axis} is {value}, not a grid cell')
    return int(value)


def refresh(cfg) -> dict[str, int]:
    """Rebuild the stash database. Returns the counts, for the caller to show."""
    parsed = _read_all(cfg.saves)

    conn = connect(cfg.stash_db)
    try:
        apply_schema(conn, SCHEMA_PATH)
        row = conn.execute(
            "SELECT value FROM build_meta WHERE key='schema_version'").fetchone()
        if row is not None and row['value'] != SCHEMA_VERSION:
            # A schema change is the one case the in-place refill cannot cover:
            # the old tables may not have the columns to refill. Start over.
            conn.close()
            _remove(cfg.stash_db)
            conn = connect(cfg.stash_db)
            apply_schema(conn, SCHEMA_PATH)

        counts = {'files': len(parsed), 'pages': 0, 'items': 0, 'materials': 0}
        with conn:                               # one transaction, or none
            for table in TABLES:
                conn.execute(f'DELETE FROM {table}')
            conn.execute(
                'INSERT INTO build_meta (key, value) VALUES (?, ?)',
                ('schema_version', SCHEMA_VERSION))
            for path, kind, data in parsed:
                conn.execute(
                    'INSERT INTO source_file (relpath, kind, mode, size, '
                    'mtime_ns, file_version, version, expansion, mod_name) '
                    'VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)',
                    _source_row(path, kind, data))
                mode = gst.mode_of(path)
                if kind == 'reagents':
                    conn.executemany(
                        'INSERT INTO reagent (mode, item_path, count) '
                        'VALUES (?, ?, ?)',
                        [(mode, it['item'], it['count']) for it in data['items']])
                    counts['materials'] += len(data['items'])
                    continue
                for page in data['pages']:
                    cursor = conn.execute(
                        'INSERT INTO stash_page (mode, idx, width, height) '
                        'VALUES (?, ?, ?, ?)',
                        (mode, page['index'], page['width'], page['height']))
                    page_id = cursor.lastrowid
                    counts['pages'] += 1
                    conn.executemany(
                        'INSERT INTO stash_item (page_id, x, y, base_path, '
                        'prefix_path, suffix_path, modifier_path, '
                        'transmute_path, seed, component_path, '
                        'relic_bonus_path, augment_path, stack) '
                        'VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
                        [(page_id, _cell(it['x'], 'x', it['base']),
                          _cell(it['y'], 'y', it['base']), it['base'],
                          _blank(it['prefix']), _blank(it['suffix']),
                          _blank(it['modifier']), _blank(it['transmute']),
                          it['seed'], _blank(it['component']),
                          _blank(it['relic_bonus']), _blank(it['augment']),
                          it['stack'])
                         for it in page['items']])
                    counts['items'] += len(page['items'])
    finally:
        conn.close()
    return counts


def _remove(path: str):
    for suffix in ('', '-wal', '-shm'):
        if os.path.exists(path + suffix):
            os.remove(path + suffix)


def summary(path: str) -> list[dict]:
    """One row per source file, with what was read out of it. For `status`."""
    conn = connect(path, create=False, hint='it is rebuilt on every launch')
    try:
        rows = []
        for src in conn.execute('SELECT * FROM source_file ORDER BY relpath'):
            row = dict(src)
            if src['kind'] == 'reagents':
                row['materials'] = conn.execute(
                    'SELECT count(*) FROM reagent WHERE mode = ?',
                    (src['mode'],)).fetchone()[0]
            else:
                row['pages'] = conn.execute(
                    'SELECT count(*) FROM stash_page WHERE mode = ?',
                    (src['mode'],)).fetchone()[0]
                row['items'] = conn.execute(
                    'SELECT count(*) FROM stash_item i JOIN stash_page p '
                    'ON p.id = i.page_id WHERE p.mode = ?',
                    (src['mode'],)).fetchone()[0]
            rows.append(row)
        return rows
    finally:
        conn.close()
