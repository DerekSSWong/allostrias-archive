"""Step 9d gate: recipes, reagents, item sets.

Three things that are easy to get wrong and were:

  1. `artifactName` names an ITEM in 727 of 927 blueprints and a loot table in
     exactly one. Treating it as "usually a loot table" left 727 recipes with
     no output -- the count looked like missing data rather than a reversed
     assumption.
  2. The base reagent slot accepts ALTERNATIVES, up to seven. Flattening them
     turns one requirement into seven.
  3. Set bonus arrays are RIGHT-ALIGNED. [0,0,0,3] on a six-piece set is +3 at
     SIX pieces. Read from the left it would be +3 at four -- a full-set bonus
     handed to someone wearing two thirds of it.
"""
import collections
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from allostrias import settings as S               # noqa: E402
from allostrias.archive import arz as A            # noqa: E402
from allostrias.archive import values as V         # noqa: E402
from allostrias.db import catalogue                # noqa: E402

cfg = S.load()
conn = catalogue.connect(cfg.catalogue_db, create=False)
one = lambda sql, *a: conn.execute(sql, a).fetchone()[0]

# -- 1. outputs ------------------------------------------------------------
total = one('SELECT count(*) FROM recipe')
concrete = one('SELECT count(*) FROM recipe WHERE output_item_id IS NOT NULL')
unresolved = one('SELECT count(*) FROM recipe '
                 'WHERE output_item_id IS NULL AND output_table IS NULL')
print(f'{total} recipes, {concrete} with a concrete output, {unresolved} with none')
assert total == 927, total
assert concrete > 900, f'only {concrete} recipes resolve an output'

# The handful that resolve nothing must have a demonstrable reason, not a
# tolerated count: their artifactName points at something that is not an item.
item_paths = {row[0] for row in conn.execute('SELECT path FROM item')}
with A.Database(cfg.arz_paths) as db:
    causes = collections.Counter()
    for row in conn.execute(
            'SELECT i.path FROM recipe r JOIN item i ON i.id=r.blueprint_id '
            'WHERE r.output_item_id IS NULL AND r.output_table IS NULL'):
        target = (V.first_str(V.non_default(db.read(row[0])),
                              'artifactName') or '').lower()
        if not target:
            causes['no artifactName']+= 1
        elif target not in db:
            causes['artifactName dangles']+= 1
        elif target not in item_paths:
            causes[f'points at a non-item '
                   f'({V.first_str(db.read(target), "Class")})'] += 1
        else:
            causes['UNEXPLAINED']+= 1
print(f'  causes: {dict(causes)}')
assert causes['UNEXPLAINED'] == 0, causes

# -- 2. reagent alternatives ----------------------------------------------
alt = conn.execute("""
    SELECT r.recipe_id, count(*) n FROM recipe_reagent r
    WHERE r.slot='base' GROUP BY r.recipe_id, r.slot
    ORDER BY n DESC LIMIT 1""").fetchone()
numbered_alt = one("SELECT count(*) FROM recipe_reagent "
                   "WHERE slot != 'base' AND alternative > 0")
print(f'\nlargest base slot: {alt["n"]} alternatives; '
      f'numbered slots with alternatives: {numbered_alt}')
assert alt['n'] > 1, 'reagent alternatives were flattened away'
assert numbered_alt == 0, 'a numbered reagent slot has alternatives; unexpected'

# -- 3. right-aligned set tiers -------------------------------------------
print('\nset bonus tiers:')
for row in conn.execute('SELECT pieces, count(*) n FROM set_bonus '
                        'GROUP BY pieces ORDER BY pieces'):
    print(f"  {row['pieces']} pieces: {row['n']:5} bonuses")
assert one('SELECT count(*) FROM set_bonus WHERE pieces < 1') == 0, \
    'a bonus was attributed to zero pieces'
over = one('SELECT count(*) FROM set_bonus b JOIN item_set s ON s.id=b.set_id '
           'WHERE b.pieces > s.members')
assert over == 0, f'{over} bonuses apply at more pieces than the set has'

# The specific short-array case, checked by value.
row = conn.execute("""
    SELECT b.pieces, b.value, s.members FROM set_bonus b
    JOIN item_set s ON s.id = b.set_id
    WHERE s.path LIKE '%itemset_d116%' AND b.field='augmentSkillLevel1'
      AND b.value > 0""").fetchone()
print(f"\nitemset_d116 augmentSkillLevel1: +{row['value']:.0f} at "
      f"{row['pieces']} of {row['members']} pieces")
assert row['pieces'] == row['members'], (
    f'a 4-entry array on a {row["members"]}-piece set put its last bonus at '
    f'{row["pieces"]} pieces -- right-alignment is not being applied')

# -- 4. the worked example -------------------------------------------------
print('\nBlueprint: Relic - Dirge of Arkovia ->')
for row in conn.execute("""
        SELECT o.name output, r.cost,
               g.slot, g.quantity, coalesce(m.name, g.item_path) reagent
        FROM item b JOIN recipe r ON r.blueprint_id = b.id
        LEFT JOIN item o ON o.id = r.output_item_id
        JOIN recipe_reagent g ON g.recipe_id = r.id
        LEFT JOIN item m ON m.id = g.item_id
        WHERE b.name LIKE '%Dirge of Arkovia%' ORDER BY g.slot"""):
    print(f"  output {row['output']!r} cost {row['cost']}  "
          f"slot {row['slot']}: {row['quantity']} x {row['reagent']}")

conn.close()
print('\nSTEP 9d PASS')
