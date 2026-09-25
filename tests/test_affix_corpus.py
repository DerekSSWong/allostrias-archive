#!/usr/bin/env python3
"""The Affixes view's corpus: every record, line, band, slot and card line.

Three oracles, each SKIPPING loudly when its checkout is absent -- gd-lib and
GD Lens are never something allostrias needs, only something this gate borrows:

  gd-lib's affix_lines.csv   the same records, the same lines (named the same
                             way), the same values and bands, the same slots
  gd-lib's affix_corpus.py   the slot vocabulary this copies
  GD Lens's affixes.py       the same LINE COUNT per record -- the denominator
                             of every grade, and the thing its line_key() and
                             is_stat() decide

and two checks of this repo's own, which need no oracle:

  every card line is one the tooltip renderer prints for that record, and every
  line it prints is on the card; and every field the sheet reads that any affix
  carries is scored.
"""
import collections
import csv
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from _oracle import sibling                              # noqa: E402
from allostrias import settings as S                     # noqa: E402
from allostrias import item_stats as I                   # noqa: E402
from allostrias.affixes import build as B                # noqa: E402
from allostrias.db import catalogue                      # noqa: E402

cfg = S.load()
conn = catalogue.connect(cfg.catalogue_db, create=False)
recs = B.load(conn)
corpus, counts = B.build(conn)
by_path = {a['path']: a for a in recs}
PREFIX = 'records/items/lootaffixes/'
print(f"{counts['records']} records, {len(corpus['t'])} tags, "
      f"{len(corpus['f'])} scored fields")
unproven = []

# -- 1. the card shows every line the game prints, and nothing else ----------
# Numbers blanked, ranges included, so a banded card line and the renderer's
# midpoint line compare by their words.
_NUM = re.compile(r'[-+]?\d+(?:\.\d+)?')


def skel(line):
    """Numbers blanked and every range folded to one number, so the renderer's
    own '3–11 Physical Damage' and the card's '(2–4)–(9–13) Physical Damage'
    both read 'N Physical Damage'."""
    s = _NUM.sub('N', line).replace('(', '').replace(')', '')
    while 'N–N' in s:
        s = s.replace('N–N', 'N')
    return s


bad = []
for a in recs:
    txt = I.read_rel(a['path'])
    want = collections.Counter(skel(l) for l in I.effects_of(txt) if l)
    # ...plus the lines the renderer lacks, which the build supplies.
    want.update(skel(B._supplement(f, a['stats'][f][0])) for f in B.SUPPLEMENT if f in a['stats'])
    pet = a['stats'].get('petBonusName', (None,) * 4)[3]
    got = collections.Counter(
        skel(t) for _, t, _, _ in
        B.display(txt, a['stats'], I.read_rel(pet) if pet else None, a['pet']))
    if want != got:
        bad.append(f"  {a['path']}: missing {dict(want - got)} extra {dict(got - want)}")
for line in bad[:5]:
    print(line)
assert not bad, f'{len(bad)} cards disagree with the tooltip renderer'
print(f'  all {len(recs)} cards carry exactly the lines the renderer prints')

# -- 1b. every line the sheet can score is on the card -----------------------
# A scored line with nothing printed for it would be graded unseen, and its
# verdict mark would have no line to sit on.
unprinted = collections.Counter()
for r in corpus['r']:
    shown = {d[0] for d in r[9]}
    for fi, _, _ in r[6]:
        if corpus['lk'][fi] not in shown:
            unprinted[corpus['f'][fi]] += 1
assert not unprinted, f'scored lines no card prints: {dict(unprinted)}'
print('  every scored line is printed on its card')

# -- 2. every field the sheet reads is scored where an affix carries it ------
fr = B.field_to_rows(B.SB.SHEET)
carried = {B.row_key(r) for a in recs for r in B.line_rows(a['stats'], a['pet'])
           if r['lo'] is not None}
missing = sorted((carried & set(fr)) - set(corpus['f']))
assert not missing, f'sheet fields affixes carry but the corpus does not score: {missing}'
print(f'  {len(corpus["f"])} scored fields: every sheet field an affix carries')

# -- 3. slots: total, in the published order --------------------------------
for s in corpus['s']:
    assert s == sorted(s, key=B.SLOT_ORDER.index), s
coarse_reach = {c for s in corpus['s'] for sl in s for c in [B.COARSE_SLOT.get(sl)] if c}
spear_only = [s for s in corpus['s'] if 'Spear (2H)' in s
              and not any(B.COARSE_SLOT.get(x) == '2H Weapon' for x in s)]
assert not spear_only, ('a spear-only affix exists: Spear (2H) needs a coarse '
                        f'bucket now. {spear_only[:3]}')
print(f'  slot families total and ordered; coarse buckets reached: {sorted(coarse_reach)}')

# ⚠️ BOTH ORACLES WERE BUILT FROM `.extracted`, WHICH IS A SNAPSHOT. When the
# game patches a record, they go stale and this repo -- which reads
# the shipped archives -- does not. A disagreement is excused ONLY where the
# record's own text differs between the two, which is derived per record
# rather than allowed as a count.
extracted = os.path.join(cfg.game, '.extracted')

def oracle_is_stale(path):
    p = os.path.join(extracted, path)
    return os.path.isfile(p) and open(p, encoding='utf-8').read() != I.read_rel(path)


# -- 4. vs gd-lib's line table ----------------------------------------------
lines_csv = sibling(os.path.join('.gdlib', 'affix_data', 'affix_lines.csv'))
if not os.path.isfile(lines_csv):
    unproven.append(f'no line table at {lines_csv}')
else:
    theirs = collections.defaultdict(set)
    their_slots = {}
    for r in csv.DictReader(open(lines_csv, encoding='utf-8')):
        path = PREFIX + r['file']
        f = lambda k: round(float(r[k]), 6) if r[k] != '' else None
        theirs[path].add((r['bucket'], r['field'], f('value'), f('lo'), f('hi'),
                          r['source'].strip().lower()))
        their_slots[path] = r['slots']
    assert set(theirs) == set(by_path), (
        f'records: {len(set(theirs) - set(by_path))} only in the table, '
        f'{len(set(by_path) - set(theirs))} only here')
    diffs, stale = [], []
    for path, a in by_path.items():
        rnd = lambda v: round(v, 6) if v is not None else None
        mine = {(r['bucket'], r['field'], rnd(r['value']), rnd(r['lo']), rnd(r['hi']),
                 r['source']) for r in B.line_rows(a['stats'], a['pet'])}
        if mine != theirs[path] and oracle_is_stale(path):
            stale.append(path)
        elif mine != theirs[path]:
            diffs.append(f'  {path}: only here {sorted(mine - theirs[path])[:2]} '
                         f'only there {sorted(theirs[path] - mine)[:2]}')
        slots = '|'.join(sorted(a['slots']))
        if slots != their_slots[path]:
            diffs.append(f'  {path}: slots {slots} vs {their_slots[path]}')
    for line in diffs[:5]:
        print(line)
    assert not diffs, f'{len(diffs)} records disagree with the line table'
    print(f'  vs gd-lib line table: {len(by_path) - len(stale)} records, every '
          f'line, band and slot identical; {len(stale)} differ where the game '
          f'patched the record after the table was built')
    for path in stale:
        print(f'    patched since: {path}')

# -- 5. vs gd-lib's slot vocabulary -----------------------------------------
lib = sibling('.gdlib')
if not os.path.isfile(os.path.join(lib, 'affix_corpus.py')):
    unproven.append(f'no gd-lib at {lib}')
else:
    os.environ.setdefault('GD_EXTRACTED', os.path.join(cfg.game, '.extracted'))
    sys.path.insert(0, lib)
    import affix_corpus as AC
    for name in ('COARSE_SLOT', 'SLOT_ORDER', 'SLOT_GROUPS'):
        assert getattr(AC, name) == getattr(B, name), f'{name} drifted from gd-lib'
    assert set(AC.ENGINE_CLASS_MAP.values()) == set(B.CLASS_TO_LABEL.values()), \
        'slot labels drifted from gd-lib'
    print('  slot vocabulary identical to gd-lib')

# -- 6. vs GD Lens's line count ---------------------------------------------
lens = sibling('.gdlens')
if not os.path.isfile(os.path.join(lens, 'affixes.py')):
    unproven.append(f'no GD Lens at {lens}')
else:
    sys.path.insert(0, lens)
    import affixes as AX
    import sheet as SH
    theirs = {PREFIX + a['file']: a['lines'] for a in AX.load(SH.SHEET)}
    compared, wrong = 0, []
    for path, n in theirs.items():
        a = by_path.get(path)
        assert a is not None, f'{path} is in GD Lens\'s corpus and not here'
        compared += 1
        mine = B.line_count(B.line_rows(a['stats'], a['pet']))
        if mine != n and path in by_path and oracle_is_stale(path):
            continue
        if mine != n:
            wrong.append(f'  {path}: {mine} lines here, {n} in GD Lens')
    for line in wrong[:5]:
        print(line)
    assert not wrong, f'{len(wrong)} line counts disagree'
    print(f'  vs GD Lens: {compared} records, every line count identical')

conn.close()
for u in unproven:
    print(f'SKIPPED PART -- {u}: UNPROVEN in this tree, exits 0 on purpose')
print('\nAFFIX CORPUS OK')
