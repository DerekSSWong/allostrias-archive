"""Step 9e gate: the skills items reference.

Scoped to referenced records, not the whole 13,993-record tree. What is
checked is that the scoping is COMPLETE for its own purpose -- every skill any
item, set or stat field points at resolves -- and that the two shapes which
look like gaps are not:

  * Skill_Modifier records carry no display name by design; a NULL there is
    correct, and 1,936 of the referenced set are modifiers.
  * Skill values are PER-LEVEL ARRAYS -- skillManaCost runs to index 99 --
    so `idx` carries the skill level and collapsing it would reduce every
    skill to its rank-1 numbers.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from allostrias import settings as S               # noqa: E402
from allostrias.db import catalogue                # noqa: E402
from allostrias.db.extract import skills           # noqa: E402

cfg = S.load()
conn = catalogue.connect(cfg.catalogue_db, create=False)
one = lambda sql, *a: conn.execute(sql, a).fetchone()[0]

total = one('SELECT count(*) FROM skill')
stats = one('SELECT count(*) FROM skill_stat')
named = one('SELECT count(*) FROM skill WHERE name IS NOT NULL')
print(f'{total} skills, {stats} stat rows, {named} named')
assert total > 3000, total

# COMPLETE FOR ITS SCOPE: nothing the catalogue references may be missing.
wanted = skills.referenced_paths(conn)
stored = {row[0] for row in conn.execute('SELECT path FROM skill')}
missing = sorted(wanted - stored)
print(f'referenced: {len(wanted)}, stored: {len(stored)}, missing: {len(missing)}')
assert not missing, f'referenced skills absent from the table: {missing[:3]}'

# Namelessness must be the modifier case, not a lookup failure.
by_class = dict(conn.execute(
    "SELECT coalesce(class,'(none)'), count(*) FROM skill WHERE name IS NULL "
    'GROUP BY class ORDER BY 2 DESC'))
print(f'\nunnamed skills by class: {dict(list(by_class.items())[:4])}')
non_modifier = one("SELECT count(*) FROM skill WHERE name IS NULL "
                   "AND class NOT LIKE '%Modifier%' AND name_tag IS NOT NULL")
assert non_modifier == 0, (
    f'{non_modifier} non-modifier skills declare a name tag that did not '
    'resolve -- that is a lookup failure, not the modifier case')
print('  every unnamed skill either is a modifier or declares no name tag')

# Per-level arrays must survive. A skill's cost and damage are stated once
# per rank, so keeping only index 0 would silently describe every skill at
# rank 1. (charLevel expressions do NOT appear here -- those live on creature
# records, not skill records, which is why this checks arrays instead.)
levelled = one('SELECT count(*) FROM skill_stat WHERE idx > 0')
deepest = one('SELECT max(idx) FROM skill_stat')
print(f'\nper-level rows beyond rank 1: {levelled}, deepest index: {deepest}')
assert levelled > 1000, 'per-level arrays were collapsed to a single value'
assert deepest > 10, deepest

# -- the worked examples ---------------------------------------------------
for name in ('Blade Barricade', 'Gavel of Justice'):
    row = conn.execute(
        'SELECT id, class, description, max_level FROM skill WHERE name=?',
        (name,)).fetchone()
    assert row, f'{name} not found'
    print(f"\n{name}  [{row['class']}]  max level {row['max_level']}")
    print(f"  {row['description'][:96]!r}")
    for stat in conn.execute(
            'SELECT field, num, txt FROM skill_stat WHERE skill_id=? '
            "AND (field LIKE 'skillMana%' OR field LIKE 'skillCooldown%' "
            "OR field LIKE 'skillActive%' OR field LIKE 'defensive%' "
            "OR field LIKE 'retaliation%') ORDER BY field", (row['id'],)):
        value = stat['txt'] if stat['num'] is None else f"{stat['num']:g}"
        print(f"    {stat['field']:36} {value}")

conn.close()
print('\nSTEP 9e PASS')
