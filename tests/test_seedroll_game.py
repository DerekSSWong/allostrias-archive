#!/usr/bin/env python3
"""Seed replay against the GAME: every rolled number must be on the game's own tooltip.

Item Assistant keeps, for every item it holds, the tooltip the game itself
rendered (`ReplicaItemRow`, colour codes and all). That is the one oracle here
that is not a port of this code, so it is what settled the corrections in
seedroll.CORRECTIONS / ADDITIONS, seedroll.roll_pet and item_lines.py. Checks:

  1. Every item IAGD holds ROLLS -- a refusal is a gap to close, not a result.
  2. Every number on its rolled lines (item_lines.rolled, the lines the Gear
     Stash view prints) is on the game's tooltip, as a multiset: a number used
     by one line is not available to the next. And the REVERSE: every line of
     the game's tooltip has its numbers on ours, so a line the renderer does not
     print fails here too (399 did, on 333 items, before 2026-09-28).
  3. Every pet bonus record an item or affix names rolls (item_lines.pet_rolls
     raises on a refusal), and the two items whose base AND affix each name
     one match the game, pinned from in-game tooltips.
  4. Each ADDITION is placed but not pinned. For every record in the catalogue
     that carries the field, every placement inside its span must roll the same
     numbers over a spread of seeds; a record that could tell them apart fails
     here instead of rolling on a guess.

Items with a component or augment are left out of 2: their tooltips merge that
record's numbers into the item's lines, and those records are not rolled. A
crafting bonus IS rolled (seedroll.MODIFIER_KINDS), so crafted items are in.

⚠️ SKIPS LOUDLY WHEN IAGD IS NOT CONFIGURED, exit 0, like every oracle gate here:
checks 3 and 4 still run, 1 and 2 print UNCHECKED.
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
# armour and block (18), stat lines (19), pet bonus lines (71), "+N to <skill>"
# (81). The tooltip's "Granted Skills" header (36) starts the granted skill's own
# block, whose numbers are the skill's, so reading stops there.
ROWS, STOP = (18, 19, 71, 81), 36


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


def game_rows(conn):
    """{item id: [(row type, text)]}, the tooltip's own lines up to STOP."""
    out = collections.defaultdict(list)
    for pid, typ, text in conn.execute(
            'SELECT i.playeritemid, r.Type, r.Text FROM ReplicaItemRow r '
            'JOIN ReplicaItem2 i ON i.Id = r.replicaitemid ORDER BY r.Id'):
        out[pid].append((typ, re.sub(r'\^.', '', text)))
    for pid, rows in out.items():
        cut = next((i for i, (t, _) in enumerate(rows) if t == STOP), len(rows))
        out[pid] = [(t, x) for t, x in rows[:cut] if t in ROWS]
    return out


def against_the_game():
    if not cfg.iagd:
        print('UNCHECKED -- no IAGD configured, so no game tooltips to hold rolls to')
        return []
    db = os.path.join(S.ROOT, 'cache', 'stash_iagd.sqlite')
    st = sqlite3.connect(db)
    st.row_factory = sqlite3.Row
    game = game_rows(iagd._connect(cfg.iagd))
    items = st.execute('SELECT * FROM iagd_item').fetchall()
    assert items, 'no IAGD items -- the gate would pass on nothing'

    bad, compared, attached, lines, crafted, pets = [], 0, 0, 0, 0, collections.Counter()
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
        pets.update(w for w in item_lines.pet_rolls(sources(r), r['seed']))
        shown = item_lines.rolled(r['base_path'], sources(r), roll)
        have = collections.Counter(float(v) for _, x in game[r['id']] for v in NUM.findall(x))
        for key, line in shown:
            if key is None or key == 'granted':
                continue                    # read off the record, not rolled
            lines += 1
            for v in map(float, NUM.findall(line)):
                if have[v] > 0:
                    have[v] -= 1
                else:
                    bad.append(f"#{r['id']} {r['base_path']}: {line!r} -- {v:g} is not on "
                               f"the game's tooltip")
        # The reverse: each game line's numbers, all of them, on some line of ours.
        ours = collections.Counter(float(v) for _, l in shown for v in NUM.findall(l))
        for _, text in game[r['id']]:
            vals = [float(v) for v in NUM.findall(text)]
            if all(ours[v] > 0 for v in vals):
                ours.subtract(vals)
            else:
                bad.append(f"#{r['id']} {r['base_path']}: the game prints {text!r}; we do not")
    print(f'{len(items)} IAGD items: {compared} compared on {lines} rolled lines, '
          f'{attached} left out for an attached record, {crafted} crafted')
    print(f'pet bonuses compared, by the record naming them: {dict(pets)}')
    if not pets['base'] or not (pets['prefix'] or pets['suffix']):
        bad.append(f'no base or no affix pet bonus compared ({dict(pets)}): '
                   'seedroll.roll_pet is held to the game on one carrier only')
    if not crafted:
        print('UNCOVERED -- no crafted item in IAGD, so seedroll.MODIFIER_SLOT is held to nothing')
    return bad


def every_pet_record_rolls():
    """Every pet bonus record an equipment item or an affix names rolls."""
    ca = sqlite3.connect(os.path.join(S.ROOT, 'cache', 'catalogue.sqlite'))
    carriers = [p for (p,) in ca.execute(
        "SELECT i.path FROM item_stat s JOIN item i ON i.id = s.item_id "
        "WHERE s.field = 'petBonusName' AND i.is_equipment = 1")]
    affixes = [p for (p,) in ca.execute(
        "SELECT DISTINCT a.path FROM affix_stat s JOIN affix a ON a.id = s.affix_id "
        "WHERE s.field = 'petBonusName'")]
    assert carriers and affixes, 'no pet bonus in the catalogue -- the check would pass on nothing'
    bad = []
    for which, paths in (('base', carriers), ('suffix', affixes)):
        for path in paths:
            try:
                item_lines.pet_rolls({which: path}, 1)
            except ValueError as e:
                bad.append(str(e))
    print(f'{len(carriers)} items and {len(affixes)} affixes name a pet bonus; all roll'
          if not bad else f'{len(bad)} pet bonus records refuse to roll')
    return bad


# Items whose base AND affix each name a pet bonus: none in IAGD, so these are
# pinned from the game's own tooltips (_Nazeem's worn head and main hand,
# screenshots 2026-09-30). One stream shared by the two records, in either
# order, misses both; each record on its own fresh stream matches both.
TWO_PET_SOURCES = [
    (54545303, {'base': 'records/items/gearhead/b015e_head.dbr',
                'prefix': 'records/items/lootaffixes/prefix/b_ar034_ar_f.dbr'},
     {'offensiveTotalDamageModifier': 40, 'characterLifeModifier': 14,
      'characterOffensiveAbilityModifier': 4, 'defensiveAether': 20, 'defensiveChaos': 22}),
    (765158018, {'base': 'records/items/gearweapons/caster/b308f_dagger.dbr',
                 'suffix': 'records/items/lootaffixes/suffix/b_wpn104_melee1h_g.dbr'},
     {'offensiveChaosModifier': 100, 'offensiveTotalDamageModifier': 82,
      'characterOffensiveAbilityModifier': 7}),
]


def two_pet_sources():
    bad = []
    for seed, srcs, want in TWO_PET_SOURCES:
        got = {}
        for roll in item_lines.pet_rolls(srcs, seed).values():
            for f, v in roll.stats.items():
                assert f not in got, f'{f} on both pet records: the pin cannot tell them apart'
                got[f] = v
        for f, v in want.items():
            if got.get(f) != v:
                bad.append(f"seed {seed}: pet {f} rolls {got.get(f)}, the game shows {v}")
    print(f'{len(TWO_PET_SOURCES)} items with two pet sources pinned to the game')
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


def base_only_is_refused():
    """Every affix carrying a BASE_ONLY field is refused, on a bare base."""
    ca = sqlite3.connect(os.path.join(S.ROOT, 'cache', 'catalogue.sqlite'))
    bad = []
    for field in seedroll.BASE_ONLY:
        affixes = ca.execute(
            'SELECT DISTINCT a.path FROM affix_stat s JOIN affix a ON a.id = s.affix_id '
            'WHERE s.field = ?', (field,)).fetchall()
        for (apath,) in affixes:
            slot = {'prefix': rec(apath)} if '/prefix/' in apath else {'suffix': rec(apath)}
            if not seedroll.compute({'Class': ['WeaponMelee_Mace2h']}, 1, **slot).unmodeled:
                bad.append(f'{field}: {apath} rolls although BASE_ONLY says refuse')
        print(f'{field}: BASE_ONLY, {len(affixes)} affix(es) refused')
    return bad


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
                'WHERE s.field IN (?, ?) AND i.is_equipment = 1', names)]
            # Equipment only: an augment or component carrying the field is an
            # attachment, and attachments are never rolled from the item's seed.
            assert paths or affixes, f'{field}: no record carries it -- drop it from ADDITIONS'
            # An affix rolls onto hundreds of bases, so the catalogue cannot be
            # walked pair by pair. What stands in for it is compute()'s own span
            # guard, checked both ways: a base that draws INSIDE the span is
            # refused, a base that does not rolls.
            inside = next(e for e in seedroll.ORDER[seedroll.ORDER.index(
                next(o for o in seedroll.ORDER if o[1] == span[0])) + 1:]
                if e[1] not in seedroll.ADDITIONS and e[0] in ('Def', 'Dmg', 'Char'))
            for (apath,) in affixes:
                slot = {'prefix': rec(apath)} if '/prefix/' in apath else {'suffix': rec(apath)}
                bare = {'Class': ['WeaponMelee_Mace2h']}
                if field in seedroll.BASE_ONLY:
                    continue                # base_only_is_refused()
                clash = dict(bare, **{inside[1]: ['10']})
                if not any('placement unpinned' in u for u in seedroll.compute(clash, 1, **slot).unmodeled):
                    bad.append(f'{field}: {apath} on a base drawing {inside[1]} inside the span '
                               f'is not refused')
                if seedroll.compute(bare, 1, **slot).unmodeled:
                    bad.append(f'{field}: {apath} on a bare base is refused -- the guard is too wide')
            alts = placements(field, span)
            if not paths:
                print(f'{field}: carried by {len(affixes)} affix(es) only; span guard checked')
                continue
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
    bad = (against_the_game() + every_pet_record_rolls() + two_pet_sources()
           + base_only_is_refused() + additions_are_unpinned())
    if bad:
        print(f'\nFAIL ({len(bad)})')
        for b in bad[:30]:
            print('  ', b)
        raise SystemExit(1)
    print('OK -- every rolled number is on the game\'s own tooltip, and every line of it on ours')


if __name__ == '__main__':
    main()
