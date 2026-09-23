"""Filling profile.sqlite's character tables from the save directory.

REBUILT ON EVERY LAUNCH, like the stash and for the same reason: the saves move
every time the game is played, and reading all six of them costs ~30 ms. These
tables are a MIRROR of the save directory -- see character.sql for what that
rules out.

THE ONE STRUCTURAL DIFFERENCE FROM THE STASH: these tables live in the file
that is never deleted. A schema change therefore drops the tables rather than
the database, because dropping the database would take the user's own data with
it.

PER-CHARACTER FAILURE, NOT ALL-OR-NOTHING. The stash refuses the whole build
when one file will not parse, because its four files are four views of one
collection. Characters are independent, and the save most likely to be caught
mid-write is the one being played right now -- refusing the other five would
empty the database exactly when it is most in use. So a character that fails is
recorded as failed, in its own table, and the launch still exits non-zero.
"""
import os

from . import apply_schema, connect
from ..archive import gdc
from ..archive.savecrypt import SaveError

SCHEMA_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           'character.sql')
SCHEMA_VERSION = '1'

# Emptied and refilled on every build, children first so the foreign keys never
# dangle mid-transaction.
TABLES = ('character_item', 'character_skill', 'character_read_error',
          'character', 'character_meta')
# Dropped and rebuilt when SCHEMA_VERSION moves. The view goes first: it
# depends on two of the tables under it.
DROP_ORDER = ('character_worn',) + TABLES


def _blank(value: str) -> str | None:
    """'' means "nothing here". Stored as NULL so the fact has one spelling."""
    return value or None


def _read_all(saves_dir: str) -> tuple[list, list]:
    """(parsed, failed) over every character directory.

    Reading happens BEFORE anything is written, so a save that raises cannot
    leave a half-filled table behind it.
    """
    parsed, failed = [], []
    for dir_name, path in gdc.character_dirs(saves_dir):
        stat = os.stat(path)
        source = (stat.st_size, stat.st_mtime_ns)
        try:
            parsed.append((dir_name, source, gdc.read_save(path)))
        except (SaveError, OSError) as exc:
            failed.append((dir_name, str(exc), *source))
    return parsed, failed


def _character_row(dir_name: str, source: tuple, save: dict) -> tuple:
    head, bio, info = save['header'], save['bio'], save['info']
    inventory, layout = save['inventory'], save['layout']
    return (
        dir_name, head['name'], head['uid'], head['class_tag'], head['level'],
        int(head['hardcore']), int(head['male']), head['expansion'],
        info['last_difficulty'], gdc.difficulty_tier(info['last_difficulty']),
        info['greatest_difficulty_unlocked'], info['money'],
        bio['experience'], bio['attribute_points'], bio['skill_points'],
        bio['devotion_points'], bio['total_devotion'],
        bio['physique'], bio['cunning'], bio['spirit'],
        bio['health'], bio['energy'],
        inventory['active_weapon_set'], save['skills']['masteries_allowed'],
        int(head['header_checksum_ok']), layout['tail_ints'],
        int(layout['tail_byte']), int(layout['ascended']),
        save['skills']['tail_bytes'], source[0], source[1],
    )


def _item_rows(dir_name: str, save: dict):
    """One row per slot: the twelve armour slots, then both weapon sets.

    Both sets are stored. Which one is worn is character.active_weapon_set, and
    the character_worn view is where that rule lives.
    """
    slots = [(item, None) for item in save['inventory']['equipment']]
    for index, weapons in enumerate(save['inventory']['weapon_sets']):
        slots.extend((item, index) for item in weapons)
    for item, weapon_set in slots:
        yield (dir_name, item['slot'], weapon_set,
               _blank(item['base']), _blank(item['prefix']),
               _blank(item['suffix']), _blank(item['modifier']),
               _blank(item['transmute']),
               item['seed'] if item['base'] else None,
               _blank(item['component']), _blank(item['relic_bonus']),
               _blank(item['augment']))


def refresh(cfg, profile_db: str = None) -> dict[str, int]:
    """Rebuild the character tables. Returns counts, for the caller to show.

    `profile_db` overrides where they are written. It exists for the frozen
    fixtures: a gate reads saves that are NOT the live ones and must not write
    its answer over the profile the live ones filled. Everything else leaves it
    alone and gets cfg.profile_db.
    """
    parsed, failed = _read_all(cfg.saves)

    conn = connect(profile_db or cfg.profile_db)
    try:
        apply_schema(conn, SCHEMA_PATH)
        row = conn.execute("SELECT value FROM character_meta "
                           "WHERE key='schema_version'").fetchone()
        if row is not None and row['value'] != SCHEMA_VERSION:
            # The tables, never the file: profile.sqlite holds things nothing
            # here can rebuild.
            with conn:
                for name in DROP_ORDER:
                    kind = 'VIEW' if name == 'character_worn' else 'TABLE'
                    conn.execute(f'DROP {kind} IF EXISTS {name}')
            apply_schema(conn, SCHEMA_PATH)

        counts = {'characters': len(parsed), 'skills': 0, 'items': 0,
                  'unreadable': len(failed)}
        with conn:                                # one transaction, or none
            for table in TABLES:
                conn.execute(f'DELETE FROM {table}')
            conn.execute('INSERT INTO character_meta (key, value) VALUES (?, ?)',
                         ('schema_version', SCHEMA_VERSION))
            conn.executemany(
                'INSERT INTO character_read_error (dir_name, error, '
                'source_size, source_mtime_ns) VALUES (?, ?, ?, ?)', failed)
            for dir_name, source, save in parsed:
                conn.execute(
                    'INSERT INTO character ('
                    'dir_name, name, uid, class_tag, level, hardcore, male, '
                    'expansion, difficulty_raw, difficulty_tier, '
                    'difficulty_unlocked, money, experience, attribute_points, '
                    'skill_points, devotion_points, devotion_total, physique, '
                    'cunning, spirit, health_base, energy_base, '
                    'active_weapon_set, masteries_allowed, header_checksum_ok, '
                    'layout_tail_ints, layout_tail_byte, layout_ascended, '
                    'skills_tail_bytes, source_size, source_mtime_ns '
                    ') VALUES (' + ','.join('?' * 31) + ')',
                    _character_row(dir_name, source, save))
                skills = [(dir_name, s['name'], s['level'], s['devotion_group'],
                           s['devotion_experience'], _blank(s['auto_cast_skill']))
                          for s in save['skills']['skills']]
                conn.executemany(
                    'INSERT INTO character_skill (dir_name, skill_path, level, '
                    'devotion_group, devotion_experience, auto_cast_skill) '
                    'VALUES (?, ?, ?, ?, ?, ?)', skills)
                items = list(_item_rows(dir_name, save))
                conn.executemany(
                    'INSERT INTO character_item (dir_name, slot, weapon_set, '
                    'base_path, prefix_path, suffix_path, modifier_path, '
                    'transmute_path, seed, component_path, relic_bonus_path, '
                    'augment_path) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
                    items)
                counts['skills'] += len(skills)
                counts['items'] += sum(1 for row in items if row[3])
    finally:
        conn.close()
    return counts


def summary(path: str) -> list[dict]:
    """One row per character, with what was read out of its save. For `status`.

    Unreadable characters come back too, as rows carrying `error`. A caller
    that prints only the readable ones would show a shorter list than the save
    directory holds and say nothing about why.
    """
    conn = connect(path, create=False, hint='it is rebuilt on every launch')
    try:
        rows = []
        for character in conn.execute(
                'SELECT * FROM character ORDER BY dir_name'):
            row = dict(character)
            row['error'] = None
            row['invested'] = conn.execute(
                'SELECT count(*) FROM character_skill WHERE dir_name = ? '
                'AND level > 0 AND devotion_group = 0',
                (row['dir_name'],)).fetchone()[0]
            row['worn'] = conn.execute(
                'SELECT count(*) FROM character_worn WHERE dir_name = ?',
                (row['dir_name'],)).fetchone()[0]
            rows.append(row)
        for failure in conn.execute(
                'SELECT * FROM character_read_error ORDER BY dir_name'):
            rows.append(dict(failure) | {'error': failure['error']})
        return sorted(rows, key=lambda r: r['dir_name'])
    finally:
        conn.close()
