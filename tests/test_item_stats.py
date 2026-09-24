"""Differential gate: the ported renderer must agree with gd-lib's, exactly.

item_stats.py is a VERBATIM COPY of gd-lib's, with one block changed -- where
records and tags come from. That is deliberate: `diff` is the review, and this
is the proof that the boundary swap changed nothing downstream of it.

gd-lib is the ORACLE and nothing else. It is imported here, never by the build.
⚠️ SKIPS LOUDLY with exit 0 when gd-lib is absent: allostrias has to stand on a
bare game install, and an oracle is a thing a gate borrows.

The comparison is every named equipment item in the catalogue against all four
entry points. A renderer that silently drops a line still returns a plausible
list, so a spot check is not a check -- the count of compared LINES is printed
for the same reason.
"""
import os
import sqlite3
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from _oracle import sibling                         # noqa: E402
from allostrias import settings as S                    # noqa: E402
from allostrias import item_stats as port               # the port, under test
from allostrias.archive.records import Records          # noqa: E402

cfg = S.load()
GDLIB = sibling('.gdlib')
if not os.path.isfile(os.path.join(GDLIB, 'item_stats.py')):
    print(f'SKIPPED -- no gd-lib at {GDLIB}, so the ported renderer is '
          f'UNCHECKED in this tree. The build does not need it; this gate does.')
    raise SystemExit(0)

# gd-lib reads `.extracted` beside itself by default; it is still unpacked in
# the game install, so point it there. Without this every link it follows reads
# as absent and it renders nothing for them.
os.environ.setdefault('GD_EXTRACTED', os.path.join(cfg.game, '.extracted'))
sys.path.insert(0, GDLIB)
import item_stats as oracle                             # noqa: E402

records = Records(cfg.arz_paths)
conn = sqlite3.connect(cfg.catalogue_db)
conn.row_factory = sqlite3.Row
rows = conn.execute("""
    select path from item
    where is_equipment = 1 and name is not null
    order by path""").fetchall()
assert rows, 'no named equipment in the catalogue; the gate would pass on nothing'

CASES = ('process_stats', 'resolve_item_skill', 'base_weapon_damage', 'base_armor')
bad, compared, lines = [], 0, 0
t0 = time.time()
for r in rows:
    txt = records.text(r['path'])
    if txt is None:
        continue
    compared += 1
    for name in CASES:
        mine = getattr(port, name)(txt)
        theirs = getattr(oracle, name)(txt)
        if isinstance(mine, list):
            lines += len(mine)
        if mine != theirs:
            bad.append((r['path'], name, theirs, mine))

print(f'{compared} items x {len(CASES)} entry points, {lines} rendered lines, '
      f'{time.time() - t0:.1f}s')
for path, name, theirs, mine in bad[:6]:
    print(f'  DIFF {path} {name}()')
    print(f'    gd-lib: {theirs}')
    print(f'    port  : {mine}')
assert not bad, f'{len(bad)} of {compared * len(CASES)} comparisons differ'

# The entry points must actually DO something on this corpus, or agreement is
# two empty lists matching forever.
assert lines > 10000, f'only {lines} lines rendered; the corpus is not exercising it'
print('\nITEM STATS OK -- port and oracle agree exactly')
