#!/usr/bin/env python3
"""item_stats.granted_skill_level() against the GAME: a granted skill whose level
is an equation in the item's level (`itemLevel/4+1`, 977 items and 471 affixes).

For every Item Assistant item that carries one, each line of its granted skill
that the level MOVES (it differs from the same skill at level 1) and that the
game prints unscaled -- projectiles, durations, recharge, radius, chances, resist
reduction; not damage, which the game scales by the holder -- must have its
numbers in the game's "Granted Skills" block.

⚠️ AFFIXES ARE ASSUMED, not held to anything yet: an affix has no itemLevel and
is handed its item's. The gate says so loudly until a held item carries an affix
whose skill the level moves (Immovable, Frostborn, of Death's Chill; see TODO.md),
and from then on checks it like any item.

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
NUM = re.compile(r'\d+(?:\.\d+)?')
UNSCALED = re.compile(r'^(?!.*(dmg|Damage)).*(Energy Cost|Skill Recharge|Duration|Projectile'
                      r'|Meter|Chance|Summon|Target Maximum|Radius|Resist|Seconds?$)')


def granted_block(rows):
    """The game's "Granted Skills" block: from its header (36) to the set (21) or
    the requirements (20)."""
    s = next((i for i, (t, _) in enumerate(rows) if t == 36), None)
    if s is None:
        return []
    e = next((i for i, (t, _) in enumerate(rows[s:], s) if t in (21, 20)), len(rows))
    return [x for _, x in rows[s:e]]


def main():
    if not cfg.iagd:
        print('UNCHECKED -- no IAGD configured, so no game tooltips to hold skill levels to')
        return
    rows = collections.defaultdict(list)
    for pid, t, x in iagd._connect(cfg.iagd).execute(
            'SELECT i.playeritemid, r.Type, r.Text FROM ReplicaItemRow r '
            'JOIN ReplicaItem2 i ON i.Id = r.replicaitemid ORDER BY r.Id'):
        rows[pid].append((t, re.sub(r'\^.', '', x)))
    st = sqlite3.connect(os.path.join(S.ROOT, 'cache', 'stash_iagd.sqlite'))
    st.row_factory = sqlite3.Row
    bad, checked = [], collections.Counter()
    for r in st.execute('SELECT * FROM iagd_item'):
        if r['id'] not in rows:
            continue
        base = I.read_rel(r['base_path']) or ''
        m = re.search(r'^itemLevel=(\d+)', base, re.M)
        item_level = int(m.group(1)) if m else None
        for col in ('base_path', 'prefix_path', 'suffix_path'):
            txt = I.read_rel(r[col]) if r[col] else None
            eq = re.search(r'^itemSkillLevelEq=(.+)$', txt or '', re.M)
            if not eq or re.fullmatch(r'[\d.]+', eq.group(1).strip()):
                continue
            ours = [l.split(': ', 1)[1] for l in I.resolve_item_skill(txt, item_level)[1:] if ': ' in l]
            at1 = {l.split(': ', 1)[1] for l in I.resolve_item_skill(
                re.sub(r'^itemSkillLevelEq=.*$', 'itemSkillLevelEq=1', txt, flags=re.M))[1:] if ': ' in l}
            moved = [l for l in ours if l not in at1 and UNSCALED.search(l)]
            if not moved:
                continue
            kind = 'item' if col == 'base_path' else 'affix'
            game = collections.Counter(float(v) for x in granted_block(rows[r['id']]) for v in NUM.findall(x))
            checked[kind] += 1
            for l in moved:
                vals = [float(v) for v in NUM.findall(l)]
                if not all(game[v] > 0 for v in vals):
                    bad.append(f"#{r['id']} {r[col]} ({kind}, level "
                               f"{I.granted_skill_level(txt, item_level)}): {l!r} is not on the game's tooltip")
    print(f"granted skills whose level moves an unscaled line: {checked['item']} on items, "
          f"{checked['affix']} on affixes")
    assert checked['item'], 'no held item carries a level equation that moves a line -- nothing is checked'
    if not checked['affix']:
        print('UNCHECKED -- no held affix grants a skill the item level moves, so the affix rule '
              '(the ITEM\'s itemLevel) is assumed. TODO.md names the affixes that would settle it.')
    if bad:
        print('\nFAIL')
        for b in bad[:20]:
            print('  ', b)
        raise SystemExit(1)
    print('OK')


if __name__ == '__main__':
    main()
