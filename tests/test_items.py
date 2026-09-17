"""Step 5b gate: the item spine.

What is checked, and why each one is here:

  * The class split is EXHAUSTIVE. Every Class in the archives is on exactly
    one of the three lists, derived from the archives themselves rather than
    from a list copied into the test -- a gate that hardcodes the same list
    the code uses agrees with the code's bugs instead of catching them.
  * Faction gear classified Rare is NOT marked as a Monster Infrequent. That
    mislabelling is the known trap in this dataset, and the structural defence
    is that no is_mi column exists yet at all.
  * Stats round-trip from the archive through the table unchanged, arrays and
    positions included.
  * Nothing obtainable ends up nameless.
"""
import collections
import os
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from allostrias import settings as S               # noqa: E402
from allostrias.archive import arc as C             # noqa: E402
from allostrias.archive import arz as A            # noqa: E402
from allostrias.archive import values as V         # noqa: E402
from allostrias.db import catalogue                # noqa: E402
from allostrias.db.extract import items            # noqa: E402

cfg = S.load()
conn = catalogue.connect(cfg.catalogue_db, create=False)


def one(sql, *args):
    return conn.execute(sql, args).fetchone()[0]


# -- 1. the split is exhaustive, and derived from the archives -------------
with A.Database(cfg.arz_paths) as db:
    seen = {V.first_str(attrs, 'Class') or ''
            for _p, attrs in db.iter_records(items.ITEM_PREFIX)}
unhandled = []
for record_class in sorted(seen):
    try:
        items.classify(record_class)
    except items.UnknownItemClass:
        unhandled.append(record_class)
print(f'{len(seen)} distinct Class values in the archives, '
      f'{len(unhandled)} unhandled')
assert not unhandled, f'classes on none of the three lists: {unhandled}'

# The lists must not overlap either; a class on two lists is ambiguous.
overlap = items.CARRIED_CLASSES & items.MACHINERY_CLASSES
assert not overlap, f'classes on both lists: {sorted(overlap)}'
print('  every Class lands on exactly one list')

# -- 2. counts ------------------------------------------------------------
total = one('SELECT count(*) FROM item')
equipment = one('SELECT count(*) FROM item WHERE is_equipment=1')
slots = one('SELECT count(DISTINCT class) FROM item WHERE is_equipment=1')
print(f'\nitems {total}  equipment {equipment}  carried {total - equipment}  '
      f'slot classes {slots}')
assert total == 9891, total
assert equipment == 7628, equipment
assert slots == 23, slots

print('\nby classification:')
for row in conn.execute(
        'SELECT coalesce(classification,"(none)") c, count(*) n FROM item '
        'GROUP BY c ORDER BY n DESC'):
    print(f'  {row["c"]:12} {row["n"]:5}')

# -- 3. the faction-Rare trap ---------------------------------------------
faction_rare = one("SELECT count(*) FROM item "
                   "WHERE folder='faction' AND classification='Rare'")
columns = {r[1] for r in conn.execute('PRAGMA table_info(item)')}
print(f'\nfaction gear classified Rare: {faction_rare}')
assert faction_rare > 0, 'expected some; the trap needs to exist to be trapped'
assert not {'is_craftable', 'is_vendor'} & columns, \
    'craftability/vendor flags cannot be derived from the item record'

# `is_mi` DOES exist now -- extract/mi.py fills it once the drop graph is
# built, because the craftable exclusion it needs depends on the loot-table
# walk. What must stay true is that THIS extractor cannot set it: nothing in
# an item record says whether a monster drops it, and faction vendor gear is
# Rare-classified proof of that. Checked by running the extractor into a
# scratch database rather than by reading the code.
scratch = os.path.join(cfg.cache_dir, 'test_items_scratch.sqlite')
for suffix in ('', '-wal', '-shm'):
    if os.path.exists(scratch + suffix):
        os.remove(scratch + suffix)
scratch_conn = catalogue.connect(scratch)
try:
    catalogue.apply_schema(scratch_conn)
    with A.Database(cfg.arz_paths) as db:
        items.extract(scratch_conn, db, C.load_tags(cfg.text_arc_paths))
    total_scratch = scratch_conn.execute(
        'SELECT count(*) FROM item').fetchone()[0]
    set_by_items = scratch_conn.execute(
        'SELECT count(*) FROM item WHERE is_mi IS NOT NULL').fetchone()[0]
finally:
    scratch_conn.close()
    for suffix in ('', '-wal', '-shm'):
        if os.path.exists(scratch + suffix):
            os.remove(scratch + suffix)
print(f'  items.extract alone: {total_scratch} items, {set_by_items} with is_mi set')
assert set_by_items == 0, \
    'the item extractor set is_mi -- MI-ness is not in the item record'
print('  no is_craftable / is_vendor column; is_mi left for extract/mi.py')

# -- 4. stats round-trip --------------------------------------------------
with A.Database(cfg.arz_paths) as db:
    checked = 0
    for row in conn.execute(
            'SELECT id, path FROM item ORDER BY id LIMIT 400 OFFSET 3000'):
        expected = {(r.field, r.idx, r.num, r.txt)
                    for r in V.stat_rows(db.read(row['path']))}
        stored = {(r['field'], r['idx'], r['num'], r['txt'])
                  for r in conn.execute(
                      'SELECT field, idx, num, txt FROM item_stat '
                      'WHERE item_id=?', (row['id'],))}
        assert stored == expected, \
            f'{row["path"]}: {sorted(stored ^ expected)[:3]}'
        checked += 1
print(f'\nstats round-trip: {checked} items identical to the archive')

# An array field must keep every position, or the join graph is broken.
arrays = conn.execute(
    'SELECT item_id, field, count(*) n FROM item_stat GROUP BY item_id, field '
    'HAVING n > 1 ORDER BY n DESC LIMIT 1').fetchone()
print(f'  longest array stored: {arrays["field"]} with {arrays["n"]} values')
assert arrays['n'] > 1

# -- 5. names -------------------------------------------------------------
nameless = conn.execute(
    'SELECT class, count(*) n FROM item WHERE name IS NULL '
    'GROUP BY class ORDER BY n DESC').fetchall()
missing = sum(r['n'] for r in nameless)
print(f'\nnameless items: {missing}')
for row in nameless[:6]:
    print(f'  {row["class"]:24} {row["n"]:4}')
# Namelessness is allowed only for a REASON that can be demonstrated, never
# tolerated as a count. Every nameless item must either carry no name tag at
# all, or carry one the game itself never defines -- both are properties of
# the archives, so this proves the cause rather than accepting a threshold.
#
# The two real causes here, found by checking rather than assumed:
#   * monster-worn gear under enemygear/ that has no itemNameTag. NOT
#     excluded from the catalogue: 219 of those 347 records ARE named and 110
#     are referenced by loot tables, so the folder is droppable and dropping
#     it would lose real items.
#   * ~115 records pointing at a tag (tagTorsoA001, tagMedalB101) that is
#     defined in no archive, console files included. Dangling references in
#     the game data; nothing to resolve them to.
#   * a tag that IS defined but whose text is EMPTY (tagTorsoB004=''). The key
#     exists and the name does not. Previously this stored as an empty-string
#     name, which is a name as far as any query is concerned; clean_name now
#     turns it into NULL, which is what it always was.
# Kept as a MAP, not a set: "the key exists" and "the key has text" are
# different facts here, and only the second makes an unresolved name a bug.
all_tags = dict(C.load_tags(cfg.text_arc_paths))
for path in cfg.text_arc_paths:
    with C.Arc(path) as archive:
        for _name, text in archive.iter_text_files(skip_console=False):
            for tag, value in C.parse_tag_lines(text):
                all_tags.setdefault(tag, value)

unexplained = [
    row['path'] for row in conn.execute(
        'SELECT path, name_tag FROM item WHERE name IS NULL')
    if row['name_tag'] is not None
    and (all_tags.get(row['name_tag']) or '').strip()]
no_tag = one('SELECT count(*) FROM item '
             'WHERE name IS NULL AND name_tag IS NULL')
dangling = missing - no_tag
print(f'  {no_tag} carry no name tag, {dangling} point at a tag '
      f'defined in no archive')
assert not unexplained, \
    f'{len(unexplained)} items are nameless but their tag DOES exist: ' \
    f'{unexplained[:3]} -- the lookup is wrong, not the data'
print('  every nameless item has a demonstrated cause')

sample = conn.execute(
    "SELECT name, class, classification, level_req FROM item "
    "WHERE classification='Legendary' AND is_equipment=1 "
    "ORDER BY level_req DESC LIMIT 3").fetchall()
for row in sample:
    print(f'  {row["name"]!r} {row["class"]} lvl {row["level_req"]}')

conn.close()
print('\nSTEP 5b PASS')
