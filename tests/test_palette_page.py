"""The UI palette builds, assembles, and its page script finds every tile.

Needs no other project: the gd-lib path its build used to add was never used
for anything, and went with the move. It DOES need the item browser's bundle --
the two pages share a frame and only the browser assembles it -- so the browser
build runs first here.
"""
import os
import shutil
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from allostrias import settings as S               # noqa: E402

cfg = S.load()
CHECK = os.path.join(ROOT, 'allostrias', 'palette', 'check.js')
PAGE = os.path.join(S.ROOT, 'cache', 'palette', 'palette.html')
CHROME = os.path.join(S.ROOT, 'cache', 'browser', 'bundle.json')

if shutil.which('node') is None:
    print('SKIPPED -- no node, so the palette page script is UNCHECKED here.')
    raise SystemExit(0)
if not os.path.isfile(CHROME):
    print(f'SKIPPED -- no {CHROME}: the palette wears the browser\'s frame, and '
          f'the browser build needs gd-lib until the renderer is ported. '
          f'The palette itself needs nothing but this repo.')
    raise SystemExit(0)

for step in ('allostrias.palette.build', 'allostrias.palette.assemble'):
    r = subprocess.run([sys.executable, '-m', step], cwd=ROOT,
                       capture_output=True, text=True)
    assert r.returncode == 0, f'{step} failed:\n{r.stdout}\n{r.stderr}'
    print(f'  {step}: {r.stdout.strip().splitlines()[-1]}')

r = subprocess.run(['node', CHECK, PAGE], cwd=ROOT, capture_output=True, text=True)
print(r.stdout.rstrip())
if r.returncode != 0:
    print(r.stderr.rstrip())
assert r.returncode == 0, 'palette check.js failed'
print('\nPALETTE PAGE OK')
