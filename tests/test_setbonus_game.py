#!/usr/bin/env python3
"""item_lines.set_block() against the GAME: every set Item Assistant holds a piece of.

IAGD keeps the tooltip the game rendered for each item it holds; a set piece's
carries the set block -- a "(N) Set" header over that tier's lines (rows 23/28 on
a Legendary, 24/26 on an Epic), then, untiered, one block per skill modifier (its
name, 82, over 83s) and the skill the full set grants (82 or 38). For every set
with a piece held:

  1. the tiers are the game's tiers, in its order;
  2. each tier's numbers are the game's numbers for it, as a multiset, both ways;
  3. what follows the tiers names the game's modified skills and granted skill.
     Only the names: the game prints a skill's numbers scaled by the character
     who held the item, so they are not the record's.

⚠️ SKIPS LOUDLY WHEN IAGD IS NOT CONFIGURED, exit 0, like every oracle gate here.
"""
import collections
import os
import re
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from allostrias import settings as S                # noqa: E402
from allostrias import item_lines                   # noqa: E402
from allostrias.db import iagd                      # noqa: E402
from allostrias.sheet import build as SB            # noqa: E402

cfg = S.load()
NUM = re.compile(r'\d+(?:\.\d+)?')
HEAD = re.compile(r'^\((\d+)\) Set$')



def nums(lines):
    return collections.Counter(float(v) for l in lines for v in NUM.findall(l))


def game_sets(conn):
    """{item id: ([(pieces, [line])], {skill name})} for every held set piece."""
    rows = collections.defaultdict(list)
    for pid, typ, text in conn.execute(
            'SELECT i.playeritemid, r.Type, r.Text FROM ReplicaItemRow r '
            'JOIN ReplicaItem2 i ON i.Id = r.replicaitemid ORDER BY r.Id'):
        rows[pid].append((typ, re.sub(r'\^.', '', text)))
    out = {}
    for pid, rs in rows.items():
        start = next((i for i, (t, _) in enumerate(rs) if t == 21), None)
        if start is None:
            continue
        tiers, names, open_ = [], set(), False
        rs = rs[start:] + [(0, ''), (0, '')]
        for i, (t, x) in enumerate(rs[:-2]):
            m = HEAD.match(x) if t in (23, 24) else None
            if m:
                tiers.append((int(m.group(1)), []))
                open_ = True
            elif open_ and t in (26, 28):
                tiers[-1][1].append(x)
            elif t in (0, 1):
                continue
            else:
                open_ = False
            if rs[i - 1][0] not in (0, 1) or x.endswith(':'):
                continue
            # a modifier: its name over 83s; the granted skill: its name over its description
            if t == 82 and rs[i + 1][0] == 83:
                names.add(x)
            elif t == 38 or (t == 82 and rs[i + 1][0] == 82):
                names.add(x)
                break
        out[pid] = (tiers, names)
    return out


def our_names(after):
    """The skills named in set_block()'s `after`: "Grants: X" and every "X: ..." prefix."""
    return {l[len('Grants: '):] if l.startswith('Grants: ') else l.split(': ', 1)[0]
            for l in after if l.startswith('Grants: ') or ': ' in l}


def main():
    if not cfg.iagd:
        print('UNCHECKED -- no IAGD configured, so no game tooltips to hold set bonuses to')
        return
    game = game_sets(iagd._connect(cfg.iagd))
    st = sqlite3.connect(os.path.join(S.ROOT, 'cache', 'stash_iagd.sqlite'))
    bad, seen = [], set()
    for pid, base_path in st.execute('SELECT id, base_path FROM iagd_item'):
        set_path = ((SB.rec(base_path) or {}).get('itemSetName') or [None])[0]
        if not set_path or pid not in game:
            if set_path:
                bad.append(f'#{pid} {base_path}: a set piece with no set block in its game tooltip')
            continue
        if set_path in seen:
            continue
        seen.add(set_path)
        tiers, after = item_lines.set_block(SB.rec(set_path))
        g_tiers, g_names = game[pid]
        if [n for n, _ in tiers] != [n for n, _ in g_tiers]:
            bad.append(f'{set_path}: tiers {[n for n, _ in tiers]}, the game {[n for n, _ in g_tiers]}')
            continue
        for (n, ours), (_, theirs) in zip(tiers, g_tiers):
            if nums(ours) != nums(theirs):
                bad.append(f'{set_path} ({n}): {ours} / game {theirs}')
        if our_names(after) != g_names:
            bad.append(f'{set_path}: names {sorted(our_names(after))} / game {sorted(g_names)}')
    print(f'{len(seen)} sets held to the game')
    assert seen, 'no set piece held -- the gate would pass on nothing'
    if bad:
        print('\nFAIL')
        for b in bad[:40]:
            print('  ', b)
        print(f'  ({len(bad)} in all)')
        raise SystemExit(1)
    print('OK')


if __name__ == '__main__':
    main()
