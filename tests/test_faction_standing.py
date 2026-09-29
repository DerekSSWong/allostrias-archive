"""Gate: save block 13 -> reputation per faction, and which slot is which.

THE FILE NAMES NO FACTION. gdc.FACTION_SLOTS is GDStash's order, and this holds
it to the game's own rule instead of to itself: gamefactions.dbr's
`noRepGainFactions` can never gain reputation, so none of them may read positive
on any frozen save. The gate is only worth something if a WRONG table would
fail it, so the same rule is run on the table shifted one slot each way and must
fail both.

Runs on the FROZEN saves; skips loudly without them.
"""
import os
import sqlite3
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from allostrias import settings as S                    # noqa: E402
from allostrias.archive import gdc                       # noqa: E402
from allostrias.db import freeze                         # noqa: E402
from allostrias.sheet import build as SB                 # noqa: E402

fixtures = freeze.frozen(ROOT)
if not fixtures:
    print('SKIPPED -- no frozen saves, so the faction slot table is UNCHECKED in this tree.')
    raise SystemExit(0)

cfg = S.load()
ca = sqlite3.connect(cfg.catalogue_db)
ids = {r[0] for r in ca.execute('SELECT id FROM faction')}
named = [f for f in gdc.FACTION_SLOTS if f]
assert set(named) <= ids, f'slots name factions the catalogue lacks: {set(named) - ids}'
assert len(set(named)) == len(named), 'a faction is on two slots'

never = {f.upper() for f in SB.rec('records/game/gamefactions.dbr')['noRepGainFactions']}
assert never, 'gamefactions.dbr lists no noRepGainFactions'


def raw_slots(path):
    """Every slot's value, by position -- before any name is put on it."""
    data = open(path, 'rb').read()

    def dec(r, s, ln):
        r.int(), r.int()
        vals = []
        for _ in range(r.int()):
            r.byte(), r.byte()
            vals.append(r.float())
            r.float(), r.float()
        gdc._end_block(r, s, ln, 'faction block')
        return vals
    return gdc._walk(data, {13: dec})['decoded'][13]


def violations(table, saves):
    return [(name, f, round(vals[i])) for name, vals in saves for i, f in enumerate(table)
            if f and f.upper() in never and i < len(vals) and vals[i] > 0]


saves = [(name, raw_slots(path)) for name, path in fixtures]
bad = violations(gdc.FACTION_SLOTS, saves)
assert not bad, f'a faction that never gains reputation reads positive: {bad[:5]}'
positive = sum(1 for _, vals in saves for i, f in enumerate(gdc.FACTION_SLOTS)
               if f and f.upper() not in never and vals[i] > 0)
assert positive, 'no faction reads positive on any save: the rule tested nothing'
for shift in (-1, 1):
    moved = gdc.FACTION_SLOTS[shift:] + gdc.FACTION_SLOTS[:shift]     # rotated one slot
    assert violations(moved, saves), f'the table shifted {shift:+d} also passes: the gate cannot tell'
print(f'{len(saves)} saves: {len(never)} never-gain factions all <= 0, {positive} positive readings '
      'elsewhere; the table shifted either way fails')

# read_save hands every named slot back, by id, at the value the raw read found.
for name, path in fixtures:
    got = gdc.read_save(path)['factions']
    vals = dict(saves)[name]
    assert set(got) == set(named), (name, set(named) ^ set(got))
    assert all(got[f]['value'] == vals[gdc.FACTION_SLOTS.index(f)] for f in named), name
print(f'read_save: {len(named)} factions per character, values as read')
print("\nFACTION STANDING OK")
