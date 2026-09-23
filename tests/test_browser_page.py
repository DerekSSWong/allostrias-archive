"""The item browser builds, assembles, and its page script computes the grid.

This used to skip without gd-lib, because the tooltip prose was gd-lib's
renderer and the page could not be BUILT without it. The renderer is ported
(`allostrias/item_stats.py`, held to the original by tests/test_item_stats.py),
so the browser now builds on a bare game install like everything else and this
is an ordinary gate.

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
