#!/usr/bin/env python3
"""Differential gate: seedroll.py must agree with gd-lib's rolls.py exactly.

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
from allostrias import settings as S                # noqa: E402
from allostrias.archive.records import Records      # noqa: E402
from allostrias.sheet import seedroll               # the port, under test

cfg = S.load()
GDLIB = os.path.join(cfg.game, '.gdlib')
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

        if set(mine.unmodeled) != set(theirs.unmodeled):
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
