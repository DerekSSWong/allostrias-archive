"""The .arz record reader reproduces `.extracted`, and owes it nothing.

allostrias must run on a bare game install. The character sheet was written
against gd-lib's `.extracted/` tree, so the risk in cutting that dependency is
not that records go missing -- it is that they come back subtly different:
defaults swept in that the authored .dbr never wrote, floats printed at float32
precision instead of the two decimals the game shows. Both would move numbers
on the sheet without breaking anything loudly.

So this compares the two sources record for record. `.extracted` is the ORACLE
here, not an input: when it is absent the comparison SKIPS LOUDLY and the rest
of the file still runs, because a gate that silently passes on a machine
without the oracle is the failure it was written to prevent.
"""
import os
import random
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from allostrias import settings as S                        # noqa: E402
from allostrias.archive.arz import Arz, Database, normalise  # noqa: E402
from allostrias.archive.records import Records              # noqa: E402

cfg = S.load()
records = Records(cfg.arz_paths)
print(f'{len(records.db)} records in {len(cfg.arz_paths)} campaign archives')

# ---- 1. SurvivalMode is excluded, and nothing the sheet reads needs it -----
# `.extracted` merges the Crucible archives last, so they win there. Reading
# them into a campaign character's sheet would show Crucible balance. They are
# excluded -- and this asserts the exclusion is currently free, rather than
# assuming it. A character who invests in an overridden skill fails here.
SURVIVAL = ('survivalmode1/database/SurvivalMode1.arz',
            'survivalmode2/database/SurvivalMode2.arz',
            'survivalmode3/database/SurvivalMode3.arz')
overridden = set()
for rel in SURVIVAL:
    p = os.path.join(cfg.game, rel)
    if os.path.isfile(p):
        with Arz(p) as a:
            overridden |= {normalise(e.path) for e in a.records}
if not overridden:
    print('  SKIP  no SurvivalMode archives on this install')
else:
    profile = os.path.join(S.ROOT, 'cache', 'profile.sqlite')
    if not os.path.isfile(profile):
        print('  SKIP  no profile.sqlite yet; run a build first')
    else:
        pr = sqlite3.connect(profile)
        read = {normalise(r[0]) for r in pr.execute(
            'select distinct skill_path from character_skill where level > 0')}
        for col in ('base_path', 'prefix_path', 'suffix_path', 'component_path',
                    'augment_path', 'relic_bonus_path', 'modifier_path'):
            read |= {normalise(r[0]) for r in pr.execute(
                f'select distinct {col} from character_item where {col} is not null')}
        clash = sorted(read & overridden)
        print(f'  {len(read)} records the characters actually read, '
              f'{len(overridden)} SurvivalMode redefines, {len(clash)} in both')
        assert not clash, (
            f'{len(clash)} record(s) a character reads are redefined by the '
            f'Crucible archives, so campaign and Crucible now disagree: '
            f'{clash[:3]}')

# ---- 2. Identical to `.extracted`, field for field ------------------------
EXTRACTED = os.path.join(cfg.game, '.extracted')
if not os.path.isdir(EXTRACTED):
    print('\n  SKIP  no .extracted/ on this install -- the oracle is absent, so '
          'the reproduction check did NOT run. It is gd-lib output and NOT '
          'required to run allostrias; this file is the only thing that wants it.')
else:
    def from_extracted(path):
        p = os.path.join(EXTRACTED, path)
        if not os.path.isfile(p):
            return None
        d = {}
        for line in open(p, encoding='utf-8', errors='replace'):
            if '=' in line:
                k, _, v = line.partition('=')
                d[k.strip()] = [x.strip() for x in v.strip().split(';')
                                if x.strip() != ''] or ['']
        return d

    everything = records.paths()
    random.seed(20260923)                      # a fixed sample, not a lucky one
    sample = random.sample(everything, 4000)
    # Every record the six characters read, on top of the random draw: those
    # are the ones a difference would actually be visible in.
    profile = os.path.join(S.ROOT, 'cache', 'profile.sqlite')
    if os.path.isfile(profile):
        pr = sqlite3.connect(profile)
        sample += [r[0] for r in pr.execute(
            'select distinct skill_path from character_skill where level > 0')]
        sample += [r[0] for r in pr.execute(
            'select distinct base_path from character_item '
            'where base_path is not null')]

    # `.extracted` is a SNAPSHOT and the archives are live, so a game patch
    # after the last extraction makes the oracle wrong rather than this reader.
    # Which one is stale is derivable, so derive it instead of allowing a
    # magic number of differences: while the snapshot predates the archives,
    # drift is reported; the moment it does not, any difference is a real bug
    # and fails.
    newest_arz = max(os.path.getmtime(p) for p in cfg.arz_paths)
    snapshot = os.path.getmtime(EXTRACTED)
    stale = snapshot < newest_arz

    checked = skipped = crucible = 0
    bad, drift = [], []
    read_by_characters = set()
    profile = os.path.join(S.ROOT, 'cache', 'profile.sqlite')
    if os.path.isfile(profile):
        pr = sqlite3.connect(profile)
        read_by_characters = {normalise(r[0]) for r in pr.execute(
            'select distinct skill_path from character_skill where level > 0')}
        read_by_characters |= {normalise(r[0]) for r in pr.execute(
            'select distinct base_path from character_item '
            'where base_path is not null')}

    for path in sample:
        # A record the Crucible archives redefine is EXPECTED to differ: that
        # is the exclusion this file asserts above, and comparing it here would
        # be asserting the bug. Counted, not silently dropped.
        if normalise(path) in overridden:
            crucible += 1
            continue
        want = from_extracted(path)
        if want is None:              # written by neither
            skipped += 1
            continue
        got = records.get(path) or {}
        checked += 1
        if got == want:
            continue
        only_want = {k: want[k] for k in set(want) - set(got)}
        only_got = {k: got[k] for k in set(got) - set(want)}
        differ = {k: (want[k], got[k]) for k in set(got) & set(want)
                  if got[k] != want[k]}
        entry = (path, only_want, only_got, differ)
        # A record a character actually reads must match whatever the snapshot's
        # age -- those are the ones a silent difference would move a number in.
        if stale and normalise(path) not in read_by_characters:
            drift.append(entry)
        else:
            bad.append(entry)

    print(f'\n  {checked} records compared against .extracted '
          f'({skipped} not written there, {crucible} redefined by the Crucible '
          f'archives and excluded on purpose)')
    if stale:
        import time
        print(f'  .extracted was written {time.strftime("%Y-%m-%d", time.localtime(snapshot))}, '
              f'the archives patched {time.strftime("%Y-%m-%d", time.localtime(newest_arz))} '
              f'-- the SNAPSHOT is the stale side')
        print(f'  {len(drift)} record(s) drifted since; '
              f'{len(read_by_characters)} character-read records still held to exact')
        for path, ow, og, df in drift[:3]:
            print(f'    drift {path}: {list(df.items())[:1]}')
    for path, ow, og, df in bad[:5]:
        print(f'    DIFF {path}')
        if ow:
            print(f'      missing here : {list(ow.items())[:2]}')
        if og:
            print(f'      extra here   : {list(og.items())[:2]}')
        if df:
            print(f'      differing    : {list(df.items())[:2]}')
    assert not bad, (
        f'{len(bad)} of {checked} records differ from .extracted for a reason '
        f'staleness does not explain')
    print('  identical, field for field, everywhere the snapshot is current')

    # ---- 3. and the TEXT form, byte for byte ------------------------------
    # The stat-line renderers are regex-over-text, so Records.text() is what
    # they get fed. Comparing the parsed dicts would not catch a join that puts
    # the right values on the line in the wrong shape, which is exactly the
    # mistake available here: `get()` has already split on ";" and rebuilding
    # from it would widen one stored string into four values.
    tsame = tdiff = tskip = 0
    tbad = []
    for path in sample:
        if normalise(path) in overridden:
            tskip += 1
            continue
        f = os.path.join(EXTRACTED, path)
        if not os.path.isfile(f):
            tskip += 1
            continue
        want = open(f, encoding='utf-8', errors='replace').read()
        got = records.text(path) or ''
        if got == want:
            tsame += 1
        elif stale and normalise(path) not in read_by_characters:
            tdiff += 1                      # the snapshot drifted; see above
        else:
            tbad.append(path)
    print(f'  Records.text(): {tsame} byte-identical to the .extracted file, '
          f'{tdiff} drifted, {tskip} skipped')
    assert not tbad, (f'{len(tbad)} record(s) render to different TEXT for a '
                      f'reason staleness does not explain: {tbad[:3]}')

print('\nRECORDS OK')
