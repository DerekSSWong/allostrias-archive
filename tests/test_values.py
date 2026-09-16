"""values.py gate: the filter must match the authority EXACTLY.

This rule decides what the entire catalogue contains, so "roughly the same
fields" is not good enough -- a filter that is slightly too eager silently
deletes stats from items. The check is therefore an exact set comparison of
kept field names against .extracted, over a sample large enough to hit the
awkward cases, plus the sizing numbers the schema was designed around.
"""
import collections
import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from allostrias import settings as S             # noqa: E402
from allostrias.archive import arz as A          # noqa: E402
from allostrias.archive import values as V       # noqa: E402

cfg = S.load()

# -- 1. unit behaviour ------------------------------------------------------
attrs = {
    'templateName': ['x.tpl'],       # kept even though it is never default
    'zeroInt': [0],
    'zeroFloat': [0.0],
    'falseBool': [False],
    'emptyStr': [''],
    'attackSpeed': ['CharacterAttackSpeedAverage'],
    'realInt': [42],
    'partlyZero': [0, 12, 0],        # positions are facts; keep all three
    'names': ['a', 'b'],
    'trueBool': [True],
}
kept = V.non_default(attrs)
assert set(kept) == {'templateName', 'realInt', 'partlyZero', 'names', 'trueBool'}, \
    sorted(kept)
assert kept['partlyZero'] == [0, 12, 0], 'a partly-zero array lost positions'
print(f'unit: {len(attrs)} fields -> {len(kept)} kept, positions preserved')

rows = list(V.stat_rows(attrs))
by_field = collections.defaultdict(list)
for row in rows:
    by_field[row.field].append(row)
assert [r.num for r in by_field['partlyZero']] == [0.0, 12.0, 0.0]
assert [r.idx for r in by_field['names']] == [0, 1]
assert [r.txt for r in by_field['names']] == ['a', 'b']
assert by_field['trueBool'][0].num == 1.0, 'True did not survive as 1'
assert all((r.num is None) != (r.txt is None) for r in rows), \
    'num and txt must be exclusive'
print(f'rows: {len(rows)} typed rows, num/txt exclusive')

# -- 2. exact agreement with the authority ---------------------------------
extracted = os.path.join(cfg.game, '.extracted')
if not os.path.isdir(extracted):
    sys.exit(f'FAIL: no {extracted}; the filter is UNPROVEN.')

CRUCIBLE = ('survivalmode1/database/SurvivalMode1.arz',
            'survivalmode2/database/SurvivalMode2.arz',
            'survivalmode3/database/SurvivalMode3.arz')
crucible = set()
for rel in CRUCIBLE:
    path = os.path.join(cfg.game, rel)
    if os.path.isfile(path):
        with A.Arz(path) as ca:
            crucible |= {A.normalise(e.path) for e in ca.records}

with A.Database(cfg.arz_paths) as db:
    random.seed(1)
    picked = [p for p in random.sample(db.paths('records/items/'), 800)
              if p not in crucible]
    compared = mismatched = 0
    examples = []
    for rel in picked:
        disk = os.path.join(extracted, rel)
        if not os.path.isfile(disk):
            continue
        theirs = set()
        with open(disk, encoding='utf-8', errors='replace') as fh:
            for line in fh:
                if '=' in line:
                    theirs.add(line.partition('=')[0])
        mine = set(V.non_default(db.read(rel)))
        compared += 1
        if mine != theirs:
            mismatched += 1
            if len(examples) < 3:
                examples.append(f'  {rel}: {sorted(mine ^ theirs)[:4]}')
    print(f'\nvs authority: {compared} item records, {mismatched} disagreeing')
    for line in examples:
        print(line)
    assert compared >= 600, f'only {compared} compared'
    assert mismatched == 0, f'{mismatched} records where the filter disagrees'
    print('  identical kept-field sets')

    # -- 3. the sizing the schema was designed around ----------------------
    items = all_fields = kept_fields = row_count = 0
    for _path, attrs in db.iter_records('records/items/'):
        items += 1
        all_fields += len(attrs)
        kept = V.non_default(attrs)
        kept_fields += len(kept)
        row_count += sum(len(v) for v in kept.values())
    print(f'\nsizing over {items} item records:')
    print(f'  fields     {all_fields:,} total -> {kept_fields:,} kept '
          f'({kept_fields / all_fields * 100:.1f}%)')
    print(f'  stat rows  {row_count:,}')
    assert items == 26001, items
    assert kept_fields == 962421, kept_fields
    assert row_count < 1_100_000, f'{row_count} rows is larger than planned'
    print(f'  {all_fields - kept_fields:,} template defaults dropped')

print('\nSTEP 5a PASS')
