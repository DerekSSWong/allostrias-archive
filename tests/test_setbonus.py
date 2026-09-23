#!/usr/bin/env python3
"""Gate: set_bonus() must decode the tier array RIGHT-aligned.

WHY THIS IS SEPARATE FROM check_sheet.js. That gate can only see what the
bundle contains, and the only set anyone here wears is Daega's Oath: three
members, worn complete, every bonus array as long as the slot count. For that
shape left- and right-alignment produce IDENTICAL output, so flipping the
decode passes check_sheet.js without a murmur. It was verified blind.

Alignment only becomes visible when an array is SHORTER than the slot count.
Explorer's Garments is that case and is the one the notes pinned against a
real in-game block: 4 members, slots (2) (3) (4), with a 3-value array live
from (2), a 2-value array from (3) and a 1-value array at (4) alone.

    python3 tests/test_setbonus.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from allostrias.sheet import build                    # the decoder, under test

# Explorer's Garments, itemset_c002. Ground truth, per the in-game display
# supplied 2026-08-22: field -> the piece count it first becomes active at.
EXPLORERS = 'records/items/lootsets/itemset_c002.dbr'
FIRST_ACTIVE = {
    'characterTotalSpeedModifier': 2,       # 8; 8; 8   -> 3 values, from (2)
    'characterOffensiveAbilityModifier': 3,  # 4; 4     -> 2 values, from (3)
    'characterDefensiveAbilityModifier': 3,  # 4; 4     -> 2 values, from (3)
    'defensiveStun': 4,                      # 50       -> 1 value,  (4) only
    'defensiveFreeze': 4,
    'defensivePetrify': 4,
}


def main():
    rec = build.rec(EXPLORERS)
    if rec is None:
        sys.exit(f'FAIL: {EXPLORERS} is in no game archive')

    members = [m for m in (rec.get('setMembers') or []) if m]
    if len(members) != 4:
        sys.exit(f'FAIL: Explorer\'s Garments has {len(members)} members, expected 4 -- '
                 'this gate is pinned to its shape and has gone stale')

    fail = []
    for field, want_from in sorted(FIRST_ACTIVE.items()):
        for worn in range(2, len(members) + 1):
            stats, _, _ = build.set_bonus(rec, worn)
            got = field in stats
            should = worn >= want_from
            if got != should:
                fail.append(f'{field} at {worn} piece(s): '
                            f'{"present" if got else "absent"}, expected '
                            f'{"present" if should else "absent"} '
                            f'(first active at {want_from})')

    # And the property that makes the direction matter at all: a one-value
    # array is the FULL-SET bonus, never the two-piece one.
    stats2, _, _ = build.set_bonus(rec, 2)
    if 'defensiveStun' in stats2:
        fail.append('a 1-value array landed on the 2-piece tier -- the decode is left-aligned')

    for f in fail:
        print(f'  - {f}')
    if fail:
        sys.exit(f'\nFAIL ({len(fail)})')
    print(f'set_bonus: Explorer\'s Garments decodes right-aligned over '
          f'{len(FIRST_ACTIVE)} fields x {len(members) - 1} tiers\nOK')


if __name__ == '__main__':
    main()
