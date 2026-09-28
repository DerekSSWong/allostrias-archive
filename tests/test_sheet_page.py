"""The page's own script, executed against the FROZEN saves, and its sheet
asserted.

⚠️ THE FROZEN SAVES, NOT THE LIVE ONES. check.js pins _Nurgle's Offensive
Ability at 1975 and Defensive Ability at 2399 -- numbers read off the character
sheet the game itself was showing. Those are properties of a character at a
moment, and the character gets played: run this against the live save directory
and it goes red the first time he buys a devotion node, for a reason that is
not a bug. `python3 main.py freeze` is what moves the reference deliberately.

Everything is built from scratch here -- profile, bundle, page -- because the
whole point is to gate the pipeline rather than whatever happens to be sitting
in cache/. It takes a few seconds. The frozen profile and bundle go to their
own paths under cache/ so that running the gate never overwrites what the live
build is serving.

SKIPS LOUDLY, exiting 0, when there is nothing frozen or no node: neither is
something allostrias needs in order to build a page, and a skip that reads like
a pass is the failure this file exists to prevent.
"""
import dataclasses
import os
import shutil
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from allostrias import settings as S                    # noqa: E402
from allostrias.db import character, freeze             # noqa: E402
from allostrias.sheet import assemble, build            # noqa: E402
from allostrias.affixes import build as affix_build     # noqa: E402
from allostrias.gearstash import build as stash_build   # noqa: E402

CHECK = os.path.join(ROOT, 'allostrias', 'sheet', 'check.js')
OUT = os.path.join(S.ROOT, 'cache', 'sheet-frozen')
PROFILE = os.path.join(OUT, 'profile.sqlite')

cfg = S.load()
fixtures = freeze.frozen(ROOT)
if not fixtures:
    print('SKIPPED -- no frozen saves, so the page is UNCHECKED in this tree. '
          'Run `python3 main.py freeze` to take the reference.')
    raise SystemExit(0)
if shutil.which('node') is None:
    print('SKIPPED -- no node on this machine, so the page script is UNCHECKED '
          'in this tree. Exits 0 on purpose: node runs this gate, it does not '
          'build the page.')
    raise SystemExit(0)

print(f'{len(fixtures)} frozen save(s): '
      f'{", ".join(n for n, _ in fixtures)}')

os.makedirs(OUT, exist_ok=True)
frozen_cfg = dataclasses.replace(cfg, saves=freeze.fixture_dir(ROOT))
counts = character.refresh(frozen_cfg, profile_db=PROFILE)
assert counts['unreadable'] == 0, f'{counts["unreadable"]} frozen save(s) would not read'
assert counts['characters'] == len(fixtures), counts
print(f"  read {counts['characters']} characters, {counts['skills']} skills, "
      f"{counts['items']} items")

build.main(profile_db=PROFILE, out_dir=OUT)
affix_build.main(out_dir=OUT)
# The stash is not a character's: it is read from the live stash databases,
# which every launch refills, and check.js derives what it expects from the
# bundle rather than pinning a count.
stash_build.main(out_dir=OUT)
assemble.main(out_dir=OUT, affixes_dir=OUT, gearstash_dir=OUT)

# Every "+N to <skill>" a worn PREFIX or SUFFIX grants reaches that skill's
# effective level -- summed straight off the affix records, so a build that
# reads only the base record falls short here. A lower bound: the base and
# attachments may add more.
import json, sqlite3                                     # noqa: E402
bundle = json.load(open(os.path.join(OUT, 'sheet.json')))
pr = sqlite3.connect(PROFILE)
pr.row_factory = sqlite3.Row
granted, short = 0, []
for c in bundle['characters']:
    want = {}
    for r in pr.execute('select prefix_path, suffix_path from character_worn where dir_name=?', (c['dir'],)):
        for p in (r['prefix_path'], r['suffix_path']):
            d = build.rec(p) if p else None
            for i in range(1, 9):
                n, l = (d or {}).get(f'augmentSkillName{i}'), (d or {}).get(f'augmentSkillLevel{i}')
                if n and l:
                    want[n[0]] = want.get(n[0], 0) + int(float(l[0]))
    for s_ in c['tree']:
        if s_['path'] in want and not s_['dev'] and s_['cls'] != 'Skill_Mastery':
            granted += 1
            if s_['eff'] - s_['lv'] < want[s_['path']]:
                short.append(f"{c['name']}: {s_['n']} eff {s_['eff']} from {s_['lv']}, affixes grant +{want[s_['path']]}")
print(f'affix skill grants: {granted} invested skill(s) granted ranks by a worn prefix/suffix')
assert granted, 'no frozen character has an invested skill an affix grants -- the check ran on nothing'
assert not short, 'affix grants missing from effective levels:\n  ' + '\n  '.join(short)

page = os.path.join(OUT, 'character_sheet.html')
r = subprocess.run(['node', CHECK, page], cwd=ROOT, capture_output=True, text=True)
print(r.stdout.rstrip())
if r.returncode != 0:
    print(r.stderr.rstrip())
assert r.returncode == 0, 'check.js failed against the frozen saves'
print('\nSHEET PAGE OK')
