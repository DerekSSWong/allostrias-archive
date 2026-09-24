"""Where a sibling project's checkout lives, for the tests that borrow one as an oracle.

gd-lib and GD Lens are checked out BESIDE this repo, as siblings under their
dot-names -- not inside the game install. Looking under settings.ini's `game`
found stale copies left there by the old layout, so those tests compared against
old code instead of skipping or checking the live one.
"""
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def sibling(name):
    return os.path.join(os.path.dirname(ROOT), name)
