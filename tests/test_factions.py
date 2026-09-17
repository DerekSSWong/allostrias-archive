"""Step 9b gate: factions.

Identity lives in three places that disagree, so each is checked against the
one that actually governs:

  * `myFaction` on the record is the ID an item's factionSource points at.
  * `tagFaction<id>` is the display name -- what the game renders.
  * the FILENAME is neither, and is wrong for two factions. The gate asserts
    that specific disagreement rather than tolerating it, so if a game update
    ever aligns them someone finds out.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from allostrias import settings as S               # noqa: E402
from allostrias.archive import arc as C            # noqa: E402
from allostrias.db import catalogue                # noqa: E402

cfg = S.load()
tags = C.load_tags(cfg.text_arc_paths)
conn = catalogue.connect(cfg.catalogue_db, create=False)
one = lambda sql, *a: conn.execute(sql, a).fetchone()[0]

total = one('SELECT count(*) FROM faction')
named = one('SELECT count(*) FROM faction WHERE name IS NOT NULL')
print(f'{total} factions, {named} with a display name')
assert total == 29, total

# Every id an item points at must resolve, or an augment loses its faction.
missing = [row[0] for row in conn.execute(
    "SELECT DISTINCT s.txt FROM item_stat s LEFT JOIN faction f ON f.id=s.txt "
    "WHERE s.field='factionSource' AND f.id IS NULL")]
print(f'faction ids referenced by items that do not resolve: {len(missing)}')
assert not missing, missing

print('\nfactions that items reference:')
for row in conn.execute("""
        SELECT f.id, f.name, count(DISTINCT s.item_id) n
        FROM item_stat s JOIN faction f ON f.id = s.txt
        WHERE s.field='factionSource' GROUP BY f.id ORDER BY n DESC"""):
    print(f"  {row['id']:10} {row['name']:26} {row['n']:4} items")

# The name comes from the tag, never the filename. Pinned as the specific
# disagreement it is: if an update aligns these, the gate should say so.
for faction_id, filename_says, tag_says in (('User19', 'dread', 'Traps'),
                                            ('User20', 'traps', 'The Dread')):
    row = conn.execute('SELECT name, path FROM faction WHERE id=?',
                       (faction_id,)).fetchone()
    assert row['name'] == tag_says, f'{faction_id}: {dict(row)}'
    assert filename_says in row['path'], f'{faction_id} path changed: {dict(row)}'
print(f'\nfilename/tag disagreement intact: User19 is "{tags["tagFactionUser19"]}" '
      f'in factiongdx3_dread.dbr')

# Noktukari, named in the vendor rules, must resolve -- the exclusion cannot
# be applied to a faction that does not exist.
noktukari = conn.execute("SELECT id, name FROM faction WHERE name='Noktukari'").fetchone()
assert noktukari, 'Noktukari does not resolve; the vendor exclusion has no target'
items = one("SELECT count(DISTINCT item_id) FROM item_stat "
            "WHERE field='factionSource' AND txt=?", noktukari['id'])
print(f'Noktukari = {noktukari["id"]}, referenced by {items} items via factionSource')

conn.close()
print('\nSTEP 9b PASS')
