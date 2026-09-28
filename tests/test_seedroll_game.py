#!/usr/bin/env python3
"""Seed replay against the GAME: every rolled number must be on the game's own tooltip.

Item Assistant keeps, for every item it holds, the tooltip the game itself
rendered (`ReplicaItemRow`, colour codes and all). That is the one oracle here
that is not a port of this code, so it is what settled the corrections in
seedroll.CORRECTIONS / ADDITIONS and item_lines.py. Three checks:

  1. Every item IAGD holds ROLLS -- a refusal is a gap to close, not a result.
  2. Every number on its rolled lines (item_lines.rolled, the lines the Gear
     Stash view prints) is on the game's tooltip, as a multiset: a number used
     by one line is not available to the next.
  3. Each ADDITION is placed but not pinned. For every record in the catalogue
     that carries the field, every placement inside its span must roll the same
     numbers over a spread of seeds; a record that could tell them apart fails
     here instead of rolling on a guess.

Items with a component or augment are left out of 2: their tooltips merge that
record's numbers into the item's lines, and those records are not rolled. A
crafting bonus IS rolled (seedroll.MODIFIER_KINDS), so crafted items are in.

⚠️ SKIPS LOUDLY WHEN IAGD IS NOT CONFIGURED, exit 0, like every oracle gate here:
check 3 still runs, 1 and 2 print UNCHECKED.
"""
import collections
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
RECORDS = Records(cfg.arz_paths)
NUM = re.compile(r'\d+(?:\.\d+)?')
# Rows of the game's tooltip that carry the item's own numbers: base damage,
# armour and block (18), stat lines (19), "+N to <skill>" (81). The tooltip's
# "Granted Skills" header (36) starts the granted skill's own block, whose
# numbers are the skill's, so reading stops there.
ROWS, STOP = (18, 19, 81), 36


def rec(path):
    return RECORDS.get(path) if path else None


def sources(r):
    return {k: r[c] for k, c in (('base', 'base_path'), ('prefix', 'prefix_path'),
                                 ('suffix', 'suffix_path')) if r[c]}


def roll_of(r):
    base = rec(r['base_path'])
    crafted = r['modifier_path'] and base.get('Class', [''])[0] != 'ItemRelic'
    return seedroll.compute(base, r['seed'], rec(r['prefix_path']), rec(r['suffix_path']),
                            modifier=rec(r['modifier_path']) if crafted else None)


def game_numbers(conn):
    out = collections.defaultdict(list)
    for pid, typ, text in conn.execute(
            'SELECT i.playeritemid, r.Type, r.Text FROM ReplicaItemRow r '
            'JOIN ReplicaItem2 i ON i.Id = r.replicaitemid ORDER BY r.Id'):
        out[pid].append((typ, re.sub(r'\^.', '', text)))
    nums = {}
    for pid, rows in out.items():
        c = collections.Counter()
        for typ, text in rows:
            if typ == STOP:
                break
            if typ in ROWS:
                c.update(float(v) for v in NUM.findall(text))
        nums[pid] = c
    return nums


def against_the_game():
    if not cfg.iagd:
        print('UNCHECKED -- no IAGD configured, so no game tooltips to hold rolls to')
        return []
    db = os.path.join(S.ROOT, 'cache', 'stash_iagd.sqlite')
    st = sqlite3.connect(db)
    st.row_factory = sqlite3.Row
    game = game_numbers(iagd._connect(cfg.iagd))
    items = st.execute('SELECT * FROM iagd_item').fetchall()
    assert items, 'no IAGD items -- the gate would pass on nothing'

    bad, compared, attached, lines, crafted = [], 0, 0, 0, 0
    for r in items:
        roll = roll_of(r)
        if roll.unmodeled:
            bad.append(f"#{r['id']} {r['base_path']}: refused ({', '.join(roll.unmodeled)})")
            continue
        if r['component_path'] or r['augment_path']:
            attached += 1
            continue
        if r['id'] not in game:
            bad.append(f"#{r['id']}: IAGD holds no game tooltip for it")
            continue
        compared += 1
        crafted += bool(r['modifier_path'])
        have = game[r['id']].copy()
        for key, line in item_lines.rolled(r['base_path'], sources(r), roll):
            if key is None:
                continue                    # read off the record, not rolled
            lines += 1
            for v in map(float, NUM.findall(line)):
                if have[v] > 0:
                    have[v] -= 1
                else:
                    bad.append(f"#{r['id']} {r['base_path']}: {line!r} -- {v:g} is not on "
                               f"the game's tooltip")
    print(f'{len(items)} IAGD items: {compared} compared on {lines} rolled lines, '
          f'{attached} left out for an attached record, {crafted} crafted')
    if not crafted:
        print('UNCOVERED -- no crafted item in IAGD, so seedroll.MODIFIER_SLOT is held to nothing')
    return bad


def placements(field, span):
    """Every ORDER that places `field` inside its span, plus no draw at all
    when that is how it is modelled -- as (order, fixed) pairs."""
    after, before = span
    kinds = [o for o in seedroll.ORDER if o[1] == field]
    rest = [o for o in seedroll.ORDER if o[1] != field]
    lo = next(i for i, o in enumerate(rest) if o[1] == after) + 1
    hi = next(i for i, o in enumerate(rest) if o[1] == before) if before else len(rest)
    entry = kinds[0] if kinds else ('Def', field, False)
    out = [(rest[:i] + [entry] + rest[i:], False) for i in range(lo, hi + 1)]
    if field in seedroll.FIXED:
        out.append((rest, True))
    return out


def additions_are_unpinned():
    ca = sqlite3.connect(os.path.join(S.ROOT, 'cache', 'catalogue.sqlite'))
    order, fixed = list(seedroll.ORDER), set(seedroll.FIXED)
    bad = []
    try:
        for field, span in seedroll.ADDITIONS.items():
            names = (field, field + 'Min')
            affixes = ca.execute(
                'SELECT DISTINCT a.path FROM affix_stat s JOIN affix a ON a.id = s.affix_id '
                'WHERE s.field IN (?, ?)', names).fetchall()
            paths = [p for (p,) in ca.execute(
                'SELECT DISTINCT i.path FROM item_stat s JOIN item i ON i.id = s.item_id '
                'WHERE s.field IN (?, ?)', names)]
            assert paths, f'{field}: no record carries it -- drop it from ADDITIONS'
            # Only the base's own draw is proven. An affix carrying the field
            # must be refused, which is what BASE_ONLY promises.
            for (apath,) in affixes:
                if field not in seedroll.BASE_ONLY:
                    bad.append(f'{field}: carried by affix {apath} -- base x affix pairs '
                               f'are not proven here; add it to BASE_ONLY or prove them')
                elif not seedroll.compute(rec(paths[0]), 1, rec(apath)).unmodeled:
                    bad.append(f'{field}: {apath} rolls although BASE_ONLY says refuse')
            alts = placements(field, span)
            for path in paths:
                base = rec(path)
                for seed in range(1, 2 ** 31, 2 ** 31 // 40):
                    seen = set()
                    for alt, is_fixed in alts:
                        seedroll.ORDER[:] = alt
                        seedroll.FIXED.discard(field)
                        if is_fixed:
                            seedroll.FIXED.add(field)
                        seedroll.MODELED.clear()
                        seedroll.MODELED.update(seedroll._build_modeled())
                        roll = seedroll.compute(base, seed)
                        # Where no draw is one of the placements, the field's
                        # OWN value is the record's in one and a jittered draw
                        # in the rest; that is only sound because the game
                        # prints nothing for it (see ADDITIONS). Every OTHER
                        # number must still agree.
                        seen.add(tuple(sorted(
                            (k, v) for k, v in roll.stats.items()
                            if isinstance(v, (int, float))
                            and not (field in fixed and k == field))))
                    if len(seen) != 1:
                        bad.append(f'{field}: {path} seed {seed} rolls differently across '
                                   f'the span -- this record pins the placement')
                        break
            print(f'{field}: {len(paths)} record(s) x {len(alts)} placements agree')
    finally:
        seedroll.ORDER[:] = order
        seedroll.FIXED.clear()
        seedroll.FIXED.update(fixed)
        seedroll.MODELED.clear()
        seedroll.MODELED.update(seedroll._build_modeled())
    return bad


def main():
    bad = against_the_game() + additions_are_unpinned()
    if bad:
        print(f'\nFAIL ({len(bad)})')
        for b in bad[:30]:
            print('  ', b)
        raise SystemExit(1)
    print('OK -- every rolled number is on the game\'s own tooltip')


if __name__ == '__main__':
    main()
