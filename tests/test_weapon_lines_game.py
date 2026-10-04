#!/usr/bin/env python3
"""A weapon's own lines against the GAME: its base damage and its attack speed.

Item Assistant keeps the tooltip the game rendered for every item it holds
(`ReplicaItemRow`). For every weapon among them, item_lines.rolled -- the lines
every view prints -- must carry, word for word:
  - the game's base damage line, "70-91 Physical Damage": a weapon's own
    Physical damage, with no "+" (item_lines.weapon_damage);
  - the game's "1.82 Attacks per Second" (item_lines.attacks_per_second, whose
    per-kind bases are FITTED -- this is the gate that fitted them).
Items with a component or augment are left out: the game merges that record's
numbers into the lines. Exits 0 and says UNCHECKED when no IAGD is configured.
"""
import os
import re
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from allostrias import settings as S                # noqa: E402
from allostrias import item_lines                   # noqa: E402
from allostrias.archive import seedroll             # noqa: E402
from allostrias.archive.records import Records      # noqa: E402
from allostrias.db import iagd                      # noqa: E402

cfg = S.load()
if not cfg.iagd:
    print('UNCHECKED -- no IAGD configured, so no game tooltips to hold weapon lines to')
    raise SystemExit(0)
RECORDS = Records(cfg.arz_paths)
rec = lambda p: RECORDS.get(p) if p else None

game = {}
for pid, typ, text in iagd._connect(cfg.iagd).execute(
        'SELECT i.playeritemid, r.Type, r.Text FROM ReplicaItemRow r '
        'JOIN ReplicaItem2 i ON i.Id = r.replicaitemid ORDER BY r.Id'):
    game.setdefault(pid, []).append((typ, re.sub(r'\^.', '', text)))

st = sqlite3.connect(os.path.join(S.ROOT, 'cache', 'stash_iagd.sqlite'))
st.row_factory = sqlite3.Row
bad, speeds, bases = [], 0, 0
for r in st.execute('SELECT * FROM iagd_item'):
    base = rec(r['base_path'])
    cls = (base.get('Class') or [''])[0]
    if not cls.startswith('Weapon') or r['component_path'] or r['augment_path'] or r['id'] not in game:
        continue
    crafted = r['modifier_path'] and cls != 'ItemRelic'
    roll = seedroll.compute(base, r['seed'], rec(r['prefix_path']), rec(r['suffix_path']),
                            modifier=rec(r['modifier_path']) if crafted else None)
    if roll.unmodeled:
        continue                          # test_seedroll_game.py reports a refusal
    srcs = {k: r[c] for k, c in (('base', 'base_path'), ('prefix', 'prefix_path'),
                                 ('suffix', 'suffix_path')) if r[c]}
    ours = [l.replace('–', '-') for _, l in item_lines.rolled(r['base_path'], srcs, roll)]
    theirs = game[r['id']]
    aps = [t for _, t in theirs if t.endswith('Attacks per Second')]
    if aps:
        speeds += 1
        if aps[0] not in ours:
            bad.append(f"#{r['id']} {r['base_path']}: the game prints {aps[0]!r}, "
                       f"we print {[l for l in ours if 'Attacks' in l]}")
    own = [t for typ, t in theirs if typ == 18 and t.endswith(' Physical Damage')]
    if own:
        bases += 1
        if own[0] not in ours:
            bad.append(f"#{r['id']} {r['base_path']}: the game's base line {own[0]!r} is not ours")
        if any(l.endswith('Physical dmg') and l.startswith('+') and
               l[1:].replace(' Physical dmg', ' Physical Damage') == own[0] for l in ours):
            bad.append(f"#{r['id']} {r['base_path']}: base damage printed as a bonus too")

print(f'{speeds} weapons\' attack speed and {bases} weapons\' base damage held to the game')
assert speeds > 100 and bases > 100, 'too few weapons compared to mean anything'
for b in bad[:20]:
    print('  ' + b)
assert not bad, f'{len(bad)} weapon lines disagree with the game'
print('\nPASS')
