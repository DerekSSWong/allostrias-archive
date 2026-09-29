#!/usr/bin/env python3
"""item_stats.resolve_skill_modifiers() against the GAME: which skills an item's
modifier blocks name, for every item Item Assistant holds that carries one.

The game's tooltip titles each block with row 81 (over 82/83 lines) or, for a
weapon-attack skill, row 37 (over 26s), before the "Granted Skills" header (36)
and the set block (21). Names only: the game prints a skill's numbers scaled by
the character who held the item.

⚠️ SKIPS LOUDLY WHEN IAGD IS NOT CONFIGURED, exit 0, like every oracle gate here.
"""
import collections
import os
import re
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from allostrias import settings as S                # noqa: E402
from allostrias import item_stats as I              # noqa: E402
from allostrias.db import iagd                      # noqa: E402

cfg = S.load()

# Pinned, (ours, the game's): a modSpawnObjects modifier, for which we print
# "Basic & Special Attack swapped" and the game prints no block. KEPT on purpose
# (user, 2026-09-29): the swapped pets' attacks really change. A change either
# way fails.
KNOWN = {
    'records/items/gearaccessories/necklaces/d303_necklace.dbr': ({'Reap Spirit'}, set()),
    'records/items/gearweapons/caster/d304_scepter.dbr': ({'Raise Skeletons'}, set()),
}


def game_names(rows):
    end = next((i for i, (t, _) in enumerate(rows) if t in (36, 21)), len(rows))
    rows = rows[:end]
    return {x for i, (t, x) in enumerate(rows[:-1])
            if (t == 81 and rows[i + 1][0] in (82, 83) and not re.match(r'^[+-]?\d', x))
            or (t == 37 and rows[i + 1][0] == 26)}


def main():
    if not cfg.iagd:
        print('UNCHECKED -- no IAGD configured, so no game tooltips to hold modifiers to')
        return
    rows = collections.defaultdict(list)
    for pid, t, x in iagd._connect(cfg.iagd).execute(
            'SELECT i.playeritemid, r.Type, r.Text FROM ReplicaItemRow r '
            'JOIN ReplicaItem2 i ON i.Id = r.replicaitemid ORDER BY r.Id'):
        rows[pid].append((t, re.sub(r'\^.', '', x)))
    st = sqlite3.connect(os.path.join(S.ROOT, 'cache', 'stash_iagd.sqlite'))
    st.row_factory = sqlite3.Row
    bad, n, pinned = [], 0, set()
    for r in st.execute('SELECT * FROM iagd_item'):
        texts = [I.read_rel(r[c]) or '' for c in ('base_path', 'prefix_path', 'suffix_path') if r[c]]
        if r['id'] not in rows or not any(re.search(r'^modifierSkillName\d', t, re.M) for t in texts):
            continue
        n += 1
        got = ({l.split(': ', 1)[0] for t in texts for l in I.resolve_skill_modifiers(t)},
               game_names(rows[r['id']]))
        if r['base_path'] in KNOWN and not (r['prefix_path'] or r['suffix_path']):
            pinned.add(r['base_path'])
            if got != KNOWN[r['base_path']]:
                bad.append(f"{r['base_path']}: no longer the pinned case -- update KNOWN: {got}")
        elif got[0] != got[1]:
            bad.append(f"#{r['id']} {r['base_path']}: ours {sorted(got[0])} / game {sorted(got[1])}")
    for p in sorted(pinned):
        print(f'KNOWN (kept by choice) -- {p}: {sorted(KNOWN[p][0])} printed, the game prints no block')
    print(f'{n} IAGD items with a skill modifier')
    assert n, 'no IAGD item carries a modifier -- the gate would pass on nothing'
    if bad:
        print('\nFAIL')
        for b in bad[:30]:
            print('  ', b)
        raise SystemExit(1)
    print('OK')


if __name__ == '__main__':
    main()
