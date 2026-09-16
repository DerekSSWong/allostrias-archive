"""arz.py gate: the four archives, stacked, diffed against the old extraction.

A parser that returns *something* for every record is not evidence -- a wrong
string-table index yields plausible garbage. So this diffs against gd-lib's
unpacked .dbr tree, which is the working authority.

Two things make that diff non-trivial, and both are properties of the
authority rather than of this parser:

  * .extracted is LOSSY ON PURPOSE. extract_all.py omits any field whose
    values are all default (0/False/''), mirroring how hand-authored .dbr
    files only list overrides. This parser keeps them, because a stat of zero
    and a stat that is absent are different facts once they are columns. The
    diff therefore applies the authority's own filter before comparing.
  * .extracted also folded in SurvivalMode1-3 (Crucible). This catalogue does
    not, so records Crucible overrides are excluded from the diff rather than
    counted as disagreements.

When the extraction is absent the diff SKIPS LOUDLY and the gate fails. A
parser whose correctness was never checked must not report success.
"""
import os
import random
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from allostrias import settings as S            # noqa: E402
from allostrias.archive import arz as A         # noqa: E402

# The union of the four shipped archives, and how many records an expansion
# restates. Both are pinned: a change in either means the game was updated or
# the load order broke, and both want looking at rather than absorbing.
EXPECTED_RECORDS = 82448
EXPECTED_OVERRIDES = 11097

# extract_all.py's own filter, copied verbatim so the diff compares like with
# like. Not used anywhere outside this test -- the catalogue keeps zeroes.
DEFAULT_VALUES = {0.0, 0, False, '', 'CharacterAttackSpeedAverage'}
CRUCIBLE = ('survivalmode1/database/SurvivalMode1.arz',
            'survivalmode2/database/SurvivalMode2.arz',
            'survivalmode3/database/SurvivalMode3.arz')

cfg = S.load()

# -- 1. record table, stacked in load order ---------------------------------
t0 = time.time()
with A.Database(cfg.arz_paths) as db:
    print(f'archives {len(db.archives)}  unique records {len(db)}  '
          f'overridden by an expansion {db.override_count}  '
          f'({time.time() - t0:.2f}s)')
    for archive in db.archives:
        print(f'  {os.path.relpath(archive.path, cfg.game):34} {len(archive.records):6}')
    assert len(db) == EXPECTED_RECORDS, f'expected {EXPECTED_RECORDS}, got {len(db)}'
    assert db.override_count == EXPECTED_OVERRIDES, \
        f'expected {EXPECTED_OVERRIDES} overrides, got {db.override_count}'

    # -- 2. a known record, straight from the .arz, no intermediate files ---
    faction = db.paths('records/items/faction/')
    assert faction, 'no records/items/faction/** records'
    sample = faction[0]
    attrs = db.read(sample)
    print(f'\n{sample}')
    for key in ('Class', 'itemClassification', 'itemNameTag', 'levelRequirement'):
        if key in attrs:
            print(f'  {key} = {attrs[key]}')
    assert 'Class' in attrs
    print(f'  ({len(attrs)} attributes, {len(faction)} faction records)')

    # -- 3. diff against the unpacked authority ----------------------------
    extracted = os.path.join(cfg.game, '.extracted')
    if not os.path.isdir(extracted):
        sys.exit(f'\nFAIL: no {extracted}; parser correctness is UNPROVEN.')

    crucible_paths = set()
    for rel in CRUCIBLE:
        path = os.path.join(cfg.game, rel)
        if os.path.isfile(path):
            with A.Arz(path) as ca:
                crucible_paths |= {A.normalise(e.path) for e in ca.records}

    def fmt(value):
        if isinstance(value, bool):
            return '1' if value else '0'
        if isinstance(value, float):
            return f'{value:g}'
        return str(value)

    def as_authority(attrs):
        """Render parsed attrs the way extract_all.py wrote them."""
        out = {}
        for key, values in attrs.items():
            if key == 'templateName':
                out[key] = fmt(values[0])
                continue
            kept = [v for v in values if v not in DEFAULT_VALUES]
            if kept:
                out[key] = '; '.join(fmt(v) for v in kept)
        return out

    def parse_dbr(path):
        out = {}
        with open(path, encoding='utf-8', errors='replace') as fh:
            for line in fh:
                if '=' in line:
                    key, _, value = line.rstrip('\n').partition('=')
                    out[key] = value
        return out

    random.seed(0)
    picked = [p for p in random.sample(db.paths(), 600) if p not in crucible_paths]
    compared = key_diff = value_diff = absent = 0
    examples = []
    for rel in picked:
        disk = os.path.join(extracted, rel)
        if not os.path.isfile(disk):
            absent += 1
            continue
        mine, theirs = as_authority(db.read(rel)), parse_dbr(disk)
        compared += 1
        if set(mine) != set(theirs):
            key_diff += 1
            if len(examples) < 3:
                examples.append(f'  keys {rel}: {sorted(set(mine) ^ set(theirs))[:4]}')
            continue
        for key, got in mine.items():
            if got != theirs[key]:
                value_diff += 1
                if len(examples) < 3:
                    examples.append(f'  {rel} [{key}]: got {got!r} want {theirs[key]!r}')
                break

    print(f'\ndiff vs unpacked authority: {compared} compared, {absent} absent, '
          f'{len(picked)} sampled after excluding {len(crucible_paths)} Crucible paths')
    for line in examples:
        print(line)
    assert compared >= 500, f'only {compared} records compared; too few to mean anything'
    assert key_diff == 0, f'{key_diff} records with differing key sets'
    assert value_diff == 0, f'{value_diff} records with differing values'
    print('  identical: every key, every value')

    # -- 4. throughput ------------------------------------------------------
    t0 = time.time()
    scanned = sum(1 for _ in db.iter_records('records/items/'))
    dt = time.time() - t0
    print(f'\nitems/ scan: {scanned} records in {dt:.1f}s ({scanned / dt:,.0f} rec/s)')

print('\nSTEP 2 PASS')
