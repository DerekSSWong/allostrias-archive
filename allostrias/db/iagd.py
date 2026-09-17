"""Reading Item Assistant for Grim Dawn's collection into cache/stash_iagd.sqlite.

IAGD's `userdata.db` holds TWO unrelated things and only one of them is wanted
here. Roughly 285 of its 288 MB is IAGD's own copy of the game database --
`DatabaseItemStat_v2` alone is 2.44 million rows -- which `catalogue.sqlite`
already holds from the archives themselves. Mirroring it would cost a quarter
of a gigabyte to gain a SECOND answer to every question the catalogue already
answers, and the two would drift. What is genuinely only here is the
COLLECTION: the items IAGD has taken out of the shared stash and stored itself.

They are disjoint from `stash.sqlite` by construction -- IAGD removes what it
takes -- and measured to be so: zero overlap on (base record, seed), and zero
even on base record alone.

⚠️ THE WAL IS NOT OPTIONAL. IAGD writes with journal_mode=WAL and the sibling
`-wal` file here is over 2 MB, so everything it has stored since its last
checkpoint lives there and nowhere else. Opening with `immutable=1` would read
the main file alone and succeed -- returning a collection that is simply
missing the most recent items, with nothing to say so. That fallback is
therefore refused rather than offered: if the database cannot be opened with
its WAL, this raises and says why.

⚠️ IAGD'S `Rarity` AND `Name` ARE NOT READ, and the reason is not squeamishness
about duplication. `Rarity` is a COLOUR name and sits one tier below the word
the catalogue uses for the same item: every one of its 704 `Blue` rows is
`Epic` in the catalogue, and every one of its 310 `Epic` rows is `Legendary`.
A query that read it as a tier would be wrong for all 1,014. `Name` is a
rendered display string ("Mythical Deathmarked Claw", "Dawnshard Hauberk
[Ancient Armor Plate]") rather than the item's name. Both are resolved through
the catalogue instead, on `item.path`.
"""
import os
import sqlite3

from . import apply_schema, connect

# The columns this reader needs, checked before anything is read. A future
# IAGD that renames one FAILS THE BUILD naming it, rather than quietly
# returning a collection with that field blank -- the same rule the catalogue's
# `Class=` whitelist follows for a game update.
#
# Deliberately absent: `Rarity` and `Name` (see the module docstring),
# `PrefixRarity` and `UNKNOWN` (IAGD's own derived value, and an unnamed save
# field, both zero for every row here and neither adding anything a record path
# does not already say), and `cloudid`/`cloud_hassync` (IAGD's sync bookkeeping,
# not a property of the item).
ITEM_COLUMNS = (
    'Id', 'baserecord', 'PrefixRecord', 'SuffixRecord', 'ModifierRecord',
    'TransmuteRecord', 'Seed', 'MateriaRecord', 'RelicCompletionBonusRecord',
    'RelicSeed', 'EnchantmentRecord', 'EnchantmentSeed', 'MateriaCombines',
    'StackCount', 'Mod', 'IsHardcore', 'created_at',
    'AscendantAffixNameRecord', 'AscendantAffix2hNameRecord',
    'RerollsUsed', 'AffixRerollsUsed',
)
RECORD_COLUMNS = ('PlayerItemId', 'Record')


class IagdError(Exception):
    """IAGD's database is missing, unreadable, or not the shape we know."""


def _connect(path: str) -> sqlite3.Connection:
    """Open IAGD's database read-only, WAL included, or refuse.

    IAGD may be running. A reader does not disturb it -- WAL exists so readers
    and a writer coexist -- but the shared-memory index must be reachable, and
    when it is not the honest answer is an error rather than a stale one.
    """
    if not os.path.isfile(path):
        raise IagdError(f'no IAGD database at {path}')
    try:
        conn = sqlite3.connect(f'file:{path}?mode=ro', uri=True)
        conn.execute('SELECT 1 FROM PlayerItem LIMIT 1').fetchone()
    except sqlite3.Error as exc:
        wal = path + '-wal'
        detail = (f'; its write-ahead log ({wal}) holds data that is in no '
                  f'other file, so this cannot be read without it'
                  if os.path.exists(wal) else '')
        raise IagdError(f'cannot read {os.path.basename(path)}: {exc}{detail}')
    conn.row_factory = sqlite3.Row
    return conn


def _require_columns(conn: sqlite3.Connection, table: str, wanted: tuple):
    present = {row['name'] for row in conn.execute(f'PRAGMA table_info({table})')}
    if not present:
        raise IagdError(f'IAGD database has no {table} table')
    missing = [c for c in wanted if c not in present]
    if missing:
        raise IagdError(
            f'IAGD {table} is missing {", ".join(missing)} -- this reader knows '
            f'a different version of Item Assistant')


def read_collection(path: str) -> dict:
    """{'items': [...], 'records': [...]} -- IAGD's stored items.

    ORPHANS ARE DROPPED HERE rather than carried in and explained later.
    `PlayerItemRecord` holds rows for items that no longer exist (9 of 1,121
    when this was written), and importing them would put referents in the
    database for items nobody can look up.
    """
    conn = _connect(path)
    try:
        _require_columns(conn, 'PlayerItem', ITEM_COLUMNS)
        _require_columns(conn, 'PlayerItemRecord', RECORD_COLUMNS)
        columns = ', '.join(f'"{c}"' for c in ITEM_COLUMNS)
        items = [dict(r) for r in
                 conn.execute(f'SELECT {columns} FROM PlayerItem ORDER BY Id')]
        live = {it['Id'] for it in items}
        records, orphans = [], 0
        for row in conn.execute(
                'SELECT PlayerItemId, Record FROM PlayerItemRecord '
                'ORDER BY PlayerItemId, Record'):
            if row['PlayerItemId'] in live:
                records.append(dict(row))
            else:
                orphans += 1
        return {'items': items, 'records': records, 'orphan_records': orphans}
    finally:
        conn.close()


SCHEMA_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           'stash_iagd.sql')
SCHEMA_VERSION = '1'

# Emptied children first, so the foreign key never dangles mid-transaction.
TABLES = ('iagd_item_record', 'iagd_item', 'source_file', 'build_meta')

# IAGD spells "no record here" as the empty string; the database spells it
# NULL, so one fact has one spelling. Same rule as stash.sqlite.
PATHS = {'PrefixRecord': 'prefix_path', 'SuffixRecord': 'suffix_path',
         'ModifierRecord': 'modifier_path', 'TransmuteRecord': 'transmute_path',
         'MateriaRecord': 'component_path',
         'RelicCompletionBonusRecord': 'relic_bonus_path',
         'EnchantmentRecord': 'augment_path',
         'AscendantAffixNameRecord': 'ascendant_path',
         'AscendantAffix2hNameRecord': 'ascendant_2h_path'}
NUMBERS = {'Seed': 'seed', 'RelicSeed': 'relic_seed',
           'EnchantmentSeed': 'augment_seed',
           'MateriaCombines': 'component_combines', 'StackCount': 'stack',
           'RerollsUsed': 'rerolls_used',
           'AffixRerollsUsed': 'affix_rerolls_used',
           'IsHardcore': 'is_hardcore', 'created_at': 'created_at'}


def _row(item: dict) -> dict:
    out = {'id': item['Id'], 'base_path': item['baserecord'],
           'mod': item['Mod'] or ''}
    for source, column in PATHS.items():
        value = item[source]
        out[column] = str(value) if value not in (None, '') else None
    for source, column in NUMBERS.items():
        out[column] = item[source]
    return out


def refresh(cfg) -> dict[str, int] | None:
    """Rebuild the IAGD collection database, or None if IAGD is unconfigured.

    `iagd` is the one OPTIONAL path in settings. When it is blank there is no
    database at all -- NOT an empty one, which would answer "you hold nothing"
    to a question that was never asked of anything.

    Reads everything before opening the database, so an IAGD caught mid-write
    leaves the previous build intact rather than replacing it with a partial.
    """
    if not cfg.iagd:
        return None
    data = read_collection(cfg.iagd)

    conn = connect(cfg.stash_iagd_db)
    try:
        apply_schema(conn, SCHEMA_PATH)
        row = conn.execute(
            "SELECT value FROM build_meta WHERE key='schema_version'").fetchone()
        if row is not None and row['value'] != SCHEMA_VERSION:
            conn.close()
            for suffix in ('', '-wal', '-shm'):
                if os.path.exists(cfg.stash_iagd_db + suffix):
                    os.remove(cfg.stash_iagd_db + suffix)
            conn = connect(cfg.stash_iagd_db)
            apply_schema(conn, SCHEMA_PATH)

        rows = [_row(item) for item in data['items']]
        columns = list(rows[0]) if rows else []
        wal = cfg.iagd + '-wal'
        stat = os.stat(cfg.iagd)
        with conn:                                   # one transaction, or none
            for table in TABLES:
                conn.execute(f'DELETE FROM {table}')
            conn.execute('INSERT INTO build_meta (key, value) VALUES (?, ?)',
                         ('schema_version', SCHEMA_VERSION))
            conn.execute(
                'INSERT INTO source_file (relpath, size, mtime_ns, wal_size) '
                'VALUES (?, ?, ?, ?)',
                (os.path.basename(cfg.iagd), stat.st_size, stat.st_mtime_ns,
                 os.path.getsize(wal) if os.path.exists(wal) else None))
            if rows:
                conn.executemany(
                    f'INSERT INTO iagd_item ({", ".join(columns)}) VALUES '
                    f'({", ".join(":" + c for c in columns)})', rows)
            conn.executemany(
                'INSERT INTO iagd_item_record (item_id, path) VALUES (?, ?)',
                [(r['PlayerItemId'], r['Record']) for r in data['records']])
        return {'items': len(rows), 'records': len(data['records']),
                'orphan_records_dropped': data['orphan_records']}
    finally:
        conn.close()


def summary(path: str) -> dict:
    """What was read, for `status`."""
    conn = connect(path, create=False, hint='it is rebuilt on every launch')
    try:
        source = conn.execute('SELECT * FROM source_file').fetchone()
        return {
            'items': conn.execute('SELECT count(*) FROM iagd_item').fetchone()[0],
            'records': conn.execute(
                'SELECT count(*) FROM iagd_item_record').fetchone()[0],
            'source': dict(source) if source else None,
        }
    finally:
        conn.close()
