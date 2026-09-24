"""Step 7b gate: which item classes each affix can roll onto.

The oracle is the `slots` column of affix_lines.csv, produced by gd-lib's own
four-layer walk. Agreement is checked as an EXACT SET per record, not as a
coverage percentage: the failure this guards against -- matching only capital
"Prefix" in the pool field names, which drops every Magical-tier pool -- shows
up as high coverage with the wrong contents, so a count would have passed it.

The two vocabularies are different by design. This repo stores the engine's
item Class; the oracle stores display labels. The map below is 1:1 across all
23 equipment classes and is asserted to be total in both directions, so a
class added by a game update fails here rather than being quietly unmapped.
"""
import collections
import csv
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from _oracle import sibling                         # noqa: E402
from allostrias import settings as S               # noqa: E402
from allostrias.db import catalogue                # noqa: E402

ORACLE_RELPATH = os.path.join('.gdlib', 'affix_data', 'affix_lines.csv')
PREFIX = 'records/items/lootaffixes/'

CLASS_TO_LABEL = {
    'ArmorJewelry_Amulet': 'Amulet',
    'ArmorJewelry_Medal': 'Medal',
    'ArmorJewelry_Ring': 'Ring',
    'ArmorProtective_Chest': 'Chest',
    'ArmorProtective_Feet': 'Boots',
    'ArmorProtective_Hands': 'Gloves',
    'ArmorProtective_Head': 'Helm',
    'ArmorProtective_Legs': 'Legs',
    'ArmorProtective_Shoulders': 'Shoulders',
    'ArmorProtective_Waist': 'Belt',
    'WeaponArmor_Offhand': 'Off-Hand (Focus)',
    'WeaponArmor_Shield': 'Shield',
    'WeaponHunting_Ranged1h': 'Ranged',
    'WeaponHunting_Ranged2h': 'Ranged (2H)',
    'WeaponMelee_Axe': 'Axe',
    'WeaponMelee_Axe2h': 'Axe (2H)',
    'WeaponMelee_Dagger': 'Dagger',
    'WeaponMelee_Mace': 'Mace',
    'WeaponMelee_Mace2h': 'Mace (2H)',
    'WeaponMelee_Scepter': 'Scepter',
    'WeaponMelee_Spear2h': 'Spear (2H)',
    'WeaponMelee_Sword': 'Sword',
    'WeaponMelee_Sword2h': 'Sword (2H)',
}

cfg = S.load()
oracle_path = sibling(ORACLE_RELPATH)
conn = catalogue.connect(cfg.catalogue_db, create=False)
one = lambda sql, *a: conn.execute(sql, a).fetchone()[0]

# -- 1. the map is total in both directions -------------------------------
equipment = {row[0] for row in conn.execute(
    'SELECT DISTINCT class FROM item WHERE is_equipment=1')}
unmapped = equipment - set(CLASS_TO_LABEL)
assert not unmapped, f'equipment classes with no label: {sorted(unmapped)}'
stray = set(CLASS_TO_LABEL) - equipment
assert not stray, f'labels for classes that do not exist: {sorted(stray)}'
print(f'class/label map covers all {len(equipment)} equipment classes, both ways')

# -- 2. both tiers are populated ------------------------------------------
# The regex bug this gate exists for leaves 'rare' healthy and 'magical'
# nearly empty, so the two are compared rather than summed.
tiers = dict(conn.execute(
    'SELECT tier, count(DISTINCT affix_id) FROM affix_eligibility GROUP BY tier'))
print(f'\naffixes reachable by tier: {tiers}')
assert set(tiers) == {'magical', 'rare'}, tiers
ratio = min(tiers.values()) / max(tiers.values())
assert ratio > 0.25, (
    f'one tier is {ratio:.0%} the size of the other -- the lowercase '
    'prefixTableName/suffixTableName pools are probably not being matched')

# -- 3. exact slot sets vs the oracle -------------------------------------
if not os.path.isfile(oracle_path):
    # SKIPS, and says so at the top of its voice. This used to exit FAIL,
    # which made gd-lib a requirement of allostrias's own test suite on every
    # machine -- and allostrias has to stand alone. The distinction that
    # mattered is kept: this is not a pass, it is an UNPROVEN, and the word is
    # in the output either way.
    print(f'SKIPPED -- no oracle at {oracle_path}, so eligibility is UNPROVEN '
          f'in this tree. Exits 0 on purpose: gd-lib is an oracle this gate '
          f'borrows, never something allostrias needs.')
    sys.exit(0)

oracle = {}
for row in csv.DictReader(open(oracle_path, encoding='utf-8')):
    slots = {s for s in row['slots'].split('|') if s}
    if slots:
        oracle[PREFIX + row['file']] = slots

mine = collections.defaultdict(set)
for row in conn.execute(
        'SELECT a.path, e.item_class FROM affix a '
        'JOIN affix_eligibility e ON e.affix_id=a.id'):
    mine[row['path']].add(CLASS_TO_LABEL[row['item_class']])

shared = set(oracle) & set(mine)
exact = sum(1 for p in shared if oracle[p] == mine[p])
differing = [p for p in shared if oracle[p] != mine[p]]
print(f'\n{len(oracle)} oracle records carry slots, {len(mine)} resolved here, '
      f'{len(shared)} in both')
print(f'  identical slot set: {exact}/{len(shared)}')
for path in differing[:3]:
    print(f"  {os.path.basename(path)}: mine-only {sorted(mine[path] - oracle[path])} "
          f"oracle-only {sorted(oracle[path] - mine[path])}")
missing = sorted(set(oracle) - set(mine))
for path in missing[:3]:
    print(f'  unresolved here: {os.path.basename(path)} -> {sorted(oracle[path])}')
assert not missing, \
    f'{len(missing)} affixes the oracle resolves and this does not'
assert not differing, f'{len(differing)} records with a different slot set'
print('  every slot set identical')

# -- 4. the worked example ------------------------------------------------
print("\n'Impervious' on a Belt (ArmorProtective_Waist):")
rows = conn.execute("""
    SELECT a.path, a.level_req, a.jitter,
           group_concat(DISTINCT e.tier) tiers
    FROM affix a
    JOIN affix_eligibility e ON e.affix_id=a.id
    WHERE a.name='Impervious' AND e.item_class='ArmorProtective_Waist'
    GROUP BY a.id ORDER BY a.path""").fetchall()
for row in rows:
    print(f"  {os.path.basename(row['path']):34} lvl {row['level_req'] or '-':>3} "
          f"tier {row['tiers']}")
belt = len(rows)
allimp = one("SELECT count(*) FROM affix WHERE name='Impervious'")
print(f'  {belt} of {allimp} "Impervious" records can roll on a Belt')
assert 0 < belt < allimp, (belt, allimp)
# The *a families are Boots/Gloves/Helm/Legs and must NOT appear on a belt.
assert not [r for r in rows if '_res_' in r['path'] and 'a_res_' in r['path']], \
    'an *a-family Impervious resolved onto a Belt'
print('  no *a-family record leaked onto a Belt')

conn.close()
print('\nSTEP 7b PASS')
