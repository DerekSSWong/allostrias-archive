#!/usr/bin/env python3
"""The copied targets must still equal GD Lens's originals.

⚠️ THE ONLY ASSERTED NUMBERS THIS PAGE SHIPS. Every other figure in the bundle
comes out of a save or the extracted database and is gated against something
derived. `TARGETS` is a judgement about what a character OUGHT to have, which no
record anywhere states, and it is a SECOND COPY of GD Lens's targets.py --
because that page may not be a build dependency of this one.

A copied constant that nothing compares is how two tools start recommending
different things while both look right. This is the comparison. GD Lens is a
TEST ORACLE here, exactly as gd-lib is for gate_seedroll.py: imported by the
gate, never by the build.

SKIPS LOUDLY when GD Lens is not checked out beside this build -- and says so
rather than passing quietly, because a skip that reads like a pass is the
failure this whole file exists to prevent.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from _oracle import sibling                         # noqa: E402
from allostrias import settings as S                  # noqa: E402
from allostrias.sheet import build                    # noqa: E402

LENS = sibling('.gdlens')


def main():
    if not os.path.isfile(os.path.join(LENS, 'targets.py')):
        print(f'SKIPPED -- no GD Lens at {LENS}, so the copied targets are '
              f'UNCHECKED in this tree. Exits 0 on purpose: GD Lens is an '
              f'oracle this gate borrows, never something allostrias needs.')
        return 0
    sys.path.insert(0, LENS)
    import targets as oracle
    theirs, ours = oracle.as_dict(), build.TARGETS

    bad = []
    for k, want in ours.items():
        got = theirs.get(k, '<absent>')
        # diffScale is keyed by the difficulty tier, and JSON has no integer
        # keys -- this copy stores the strings the page will look up with.
        if k == 'diffScale':
            got = {str(a): b for a, b in got.items()}
        if got != want:
            bad.append(f'  {k}: GD Lens {got!r}, this build {want!r}')
    for line in bad:
        print(line)
    # ...and the other direction, for the keys the verdict engine reads. A key
    # GD Lens ADDS is not a failure here -- it also carries the scoring and
    # grading constants this page has no use for -- but a key it RENAMES would
    # leave this copy holding a number nothing upstream defines any more.
    print(f'{len(ours)} target groups compared, {len(bad)} drifted')
    return 1 if bad else 0


if __name__ == '__main__':
    raise SystemExit(main())
