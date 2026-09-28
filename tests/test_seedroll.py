#!/usr/bin/env python3
"""Differential gate: seedroll.py must agree with gd-lib's rolls.py exactly,
once seedroll.CORRECTIONS are applied to the oracle.

A correction is a place where the GAME settled that gd-lib is wrong
(tests/test_seedroll_game.py is that evidence). Each is applied to the oracle
in-process, and each must still be a real difference -- a correction gd-lib
has since adopted, or one the port has quietly dropped, fails here.

gd-lib is the ORACLE here and nothing else. It is imported by this gate, never
by the build -- that is the whole point of the port. Run after any edit to
seedroll.py: a transcription slip in an order table desyncs the MINSTD stream
and returns plausible numbers, so reading the diff is not a check and this is.

⚠️ SKIPS LOUDLY WHEN gd-lib IS NOT PRESENT, and exits 0 so that a machine with
no gd-lib does not report a failure it cannot fix. allostrias must run on a
bare game install; an oracle is a thing a gate borrows, never a dependency.
The skip says the port is UNCHECKED in this tree rather than printing OK.
"""
import os
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from _oracle import sibling                         # noqa: E402
from allostrias import settings as S                # noqa: E402
from allostrias.archive.records import Records      # noqa: E402
from allostrias.archive import seedroll               # the port, under test

cfg = S.load()
GDLIB = sibling('.gdlib')
RECORDS = Records(cfg.arz_paths)


def rec(path):
    return RECORDS.get(path) if path else None


def main():
    if not os.path.isfile(os.path.join(GDLIB, 'rolls.py')):
        print(f'SKIPPED -- no gd-lib at {GDLIB}, so seedroll.py is UNCHECKED '
              f'in this tree. The build does not need it; this gate does.')
        return
    sys.path.insert(0, GDLIB)
    import rolls as oracle                          # gd-lib, the oracle

    for f in seedroll.CORRECTIONS:
        assert f in oracle.NON_SCALING and f not in seedroll.NON_SCALING, \
            f'correction {f} is no longer a difference between port and oracle'
        oracle.NON_SCALING.discard(f)
    oracle.ORDER[:] = oracle._build_order()
    # ADDITIONS are fields the oracle refuses and the port models; they are the
    # only entries the port's order may have that the oracle's lacks.
    added = set(seedroll.ADDITIONS)
    assert [o for o in seedroll.ORDER if o[1] not in added] == oracle.ORDER, \
        'corrected oracle order differs from the port'
    assert all(any(o[1] == f for o in oracle.ORDER) is False for f in added), \
        'an addition is in the oracle now: drop it from seedroll.ADDITIONS'

    con = sqlite3.connect(os.path.join(S.ROOT, 'cache', 'profile.sqlite'))
    con.row_factory = sqlite3.Row
    items = con.execute('select * from character_worn').fetchall()
    assert items, 'no worn items -- the gate would pass on nothing'

    bad, fields = [], 0
    for r in items:
        base = rec(r['base_path'])
        if base is None:
            continue
        pfx = rec(r['prefix_path']) if r['prefix_path'] else None
        sfx = rec(r['suffix_path']) if r['suffix_path'] else None
        mine = seedroll.compute(base, r['seed'], pfx, sfx)
        theirs = oracle.compute(base, r['seed'], pfx, sfx)

        theirs_unmodeled = {f for f in theirs.unmodeled
                            if not any(f.startswith(a) for a in added)}
        if set(mine.unmodeled) != theirs_unmodeled:
            bad.append(f"{r['dir_name']}/{r['slot']}: refusal differs")
        keys = set(mine.stats) | set(theirs.stats)
        for k in keys:
            fields += 1
            a, b = mine.stats.get(k), theirs.stats.get(k)
            if a != b:
                bad.append(f"{r['dir_name']}/{r['slot']} {k}: port={a} oracle={b}")
        # parts must agree too: the sheet attributes a value to base/prefix/suffix
        if mine.parts != theirs.parts:
            bad.append(f"{r['dir_name']}/{r['slot']}: per-source split differs")

    print(f'{len(items)} items, {fields} field comparisons')
    if bad:
        print('\nFAIL')
        for b in bad[:25]:
            print('  ', b)
        raise SystemExit(1)
    print('OK -- port and oracle agree exactly')


if __name__ == '__main__':
    main()
