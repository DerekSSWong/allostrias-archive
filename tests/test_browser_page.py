"""The item browser builds, assembles, and its page script computes the grid.

⚠️ SKIPS WITHOUT gd-lib, and that is not the usual oracle skip. Every other
gate here borrows another project only to CHECK an answer; this one cannot
produce the page at all without `item_stats`, because the tooltip prose is
still gd-lib's renderer. It is the last thing in the repo that needs another
project present. When the port lands, the gd-lib branch below goes with it and
this becomes an ordinary gate.

Builds from scratch rather than checking whatever is in cache/: the point is to
gate the pipeline, not an artifact someone may have left lying there.
"""
import os
import shutil
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from allostrias import settings as S               # noqa: E402

cfg = S.load()
CHECK = os.path.join(ROOT, 'allostrias', 'browser', 'check.js')
PAGE = os.path.join(S.ROOT, 'cache', 'browser', 'archive.html')

if not os.path.isfile(os.path.join(cfg.game, '.gdlib', 'item_stats.py')):
    print('SKIPPED -- no gd-lib, and the item browser cannot BUILD without it: '
          'the tooltip prose is still its renderer. This is the one remaining '
          'cross-project dependency, not an unchecked oracle.')
    raise SystemExit(0)
if shutil.which('node') is None:
    print('SKIPPED -- no node, so the browser page script is UNCHECKED here.')
    raise SystemExit(0)
if not os.path.isfile(cfg.catalogue_db):
    print('SKIPPED -- no catalogue.sqlite; run `python3 main.py rebuild` first.')
    raise SystemExit(0)

for step in ('allostrias.browser.build', 'allostrias.browser.assemble'):
    r = subprocess.run([sys.executable, '-m', step], cwd=ROOT,
                       capture_output=True, text=True)
    assert r.returncode == 0, f'{step} failed:\n{r.stdout}\n{r.stderr}'
    print(f'  {step}: {r.stdout.strip().splitlines()[-1]}')

r = subprocess.run(['node', CHECK, PAGE], cwd=ROOT, capture_output=True, text=True)
print(r.stdout.rstrip())
if r.returncode != 0:
    print(r.stderr.rstrip())
assert r.returncode == 0, 'browser check.js failed'
print('\nBROWSER PAGE OK')
