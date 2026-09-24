#!/usr/bin/env python3
"""The loot filter the Affixes view downloads, held to GD Lens's generator.

allostrias/affixes/filter.py ports raynbow.py's character-independent half and
the page renders the rest (affixes.js renderFilter). Against GD Lens, when it is
checked out beside this repo:

  - the palette, the grade colours and the ungraded colour are the same;
  - the 481 affix names are the same;
  - the base, style and quality lines are the same, save for tags whose records
    the game added or patched after GD Lens's `.extracted` snapshot -- excused
    per tag by comparing the records themselves, never by a count;
  - and the WHOLE FILE is byte-identical to what raynbow.render() writes for the
    same grades, except the one title line that names the tool.

SKIPS the GD Lens half loudly when it is absent. The format itself -- CRLF,
ASCII, sorted, one reset per line -- is asserted by allostrias/sheet/check.js
against the file the page actually hands over.
"""
import os
import shutil
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from _oracle import ROOT, sibling                        # noqa: E402
from allostrias import settings as S                     # noqa: E402
from allostrias import item_stats as I                   # noqa: E402
from allostrias.affixes import filter as F               # noqa: E402
from allostrias.db import catalogue                      # noqa: E402

cfg = S.load()
conn = catalogue.connect(cfg.catalogue_db, create=False)
data = F.build(conn)
names, bases = data['names'], {t: tuple(v) for t, v in data['bases'].items()}
print(f'{len(names)} affix names, {len(bases)} base lines')
assert len(names) == len({n for n in names}), 'a tag is listed twice'

lens, lib = sibling('.gdlens'), sibling('.gdlib')
if not (os.path.isfile(os.path.join(lens, 'raynbow.py')) and os.path.isdir(lib)):
    print(f'SKIPPED -- no GD Lens / gd-lib beside this repo: the filter is '
          f'UNCOMPARED in this tree. Exits 0 on purpose.')
    raise SystemExit(0)
extracted = os.path.join(cfg.game, '.extracted')
os.environ.setdefault('GD_EXTRACTED', extracted)
sys.path[:0] = [lens, lib]
import raynbow as R                                      # noqa: E402
import palette as P                                      # noqa: E402

assert F.PALETTE == P.PALETTE and F.CONFIRMED == P.CONFIRMED, 'the palette drifted from gd-lib'
assert F.GRADE_COLOUR == R.GRADE_COLOUR, 'the grade colours drifted from GD Lens'
assert F.UNGRADED_COLOUR == R.UNGRADED_COLOUR, 'the ungraded colour drifted from GD Lens'
assert (F.FILENAME, F.EOL.encode(), F.RESET) == (R.FILENAME, R.EOL, R.RESET), \
    'the file name, line ending or reset drifted from GD Lens'
print('  palette, grade colours, file name, line ending and reset identical')

theirs_names = R.affix_names()
assert names == theirs_names, (
    f'affix names: {len(set(names) ^ set(theirs_names))} tags differ, '
    f'{sum(names.get(t) != n for t, n in theirs_names.items())} names differ')
print(f'  all {len(names)} affix names identical')

# ⚠️ GD Lens walks `.extracted`, a snapshot. A base line may differ only where
# every record carrying the tag is missing from it or differs in it.
theirs_bases = R.base_names()
carriers = {}
for item_id, path, n, st in conn.execute('SELECT id, path, name_tag, style_tag FROM item'):
    for t in (n, st):
        if t:
            carriers.setdefault(t, []).append(path)
for item_id, t in conn.execute("SELECT i.path, s.txt FROM item_stat s JOIN item i "
                               "ON i.id=s.item_id WHERE s.field='itemQualityTag'"):
    carriers.setdefault(t, []).append(item_id)


def patched(path):
    p = os.path.join(extracted, path)
    return not os.path.isfile(p) or open(p, encoding='utf-8').read() != I.read_rel(path)


differ = [t for t in set(bases) | set(theirs_bases) if bases.get(t) != theirs_bases.get(t)]
unexplained = [t for t in differ if not all(patched(p) for p in carriers.get(t, []))]
assert not unexplained, (f'{len(unexplained)} base lines differ from GD Lens on records '
                         f'the game has not changed: {unexplained[:5]}')
print(f'  {len(bases) - len(differ)} base lines identical; {len(differ)} differ, '
      f'each carried only by records added or patched since the snapshot')

# The whole file, both engines, same grades. The grades are arbitrary but
# cover every colour, including ungraded.
cycle = ['S', 'A', 'B', 'C', 'F', None]
grades = {t: cycle[i % len(cycle)] for i, t in enumerate(sorted(names))}
best = {t: g for t, g in grades.items() if g}
theirs, _ = R.render(lambda t: R.UNGRADED_COLOUR if grades[t] is None
                     else R.GRADE_COLOUR[grades[t]], 'Test Character',
                     names=names, bases=bases)
if shutil.which('node') is None:
    print('SKIPPED PART -- no node: the page renderer is UNCOMPARED')
    raise SystemExit(0)
corpus = {'filter': data}
script = ("require(process.argv[1]);"
          "const [c, b]=JSON.parse(require('fs').readFileSync(0, 'utf8'));"
          "const A=globalThis.GDAffixes; A.load(c, {});"
          "process.stdout.write(A.renderFilter(b, 'Test Character').text);")
import json                                              # noqa: E402
r = subprocess.run(['node', '-e', script, os.path.join(ROOT, 'allostrias', 'affixes', 'affixes.js')],
                   input=json.dumps([corpus, best]).encode(), capture_output=True)
assert r.returncode == 0, r.stderr.decode()
mine = r.stdout
ours_lines, their_lines = mine.split(b'\r\n'), theirs.split(b'\r\n')
assert len(ours_lines) == len(their_lines), f'{len(ours_lines)} lines vs {len(their_lines)}'
diff = [(a, b) for a, b in zip(ours_lines, their_lines) if a != b]
assert diff == [(b"# ### Allostria's Archive loot filter", b'# ### GD Lens loot filter')], \
    f'{len(diff)} lines differ from raynbow.render(), e.g. {diff[:3]}'
print(f'  the page\'s file is byte-identical to raynbow.render() for the same grades, '
      f'{len(ours_lines)} lines, bar the title')
print('\nAFFIX FILTER OK')
