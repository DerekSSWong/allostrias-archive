#!/usr/bin/env python3
"""The Gear Stash bundle: every piece of equipment held, as rolled, and nothing
socketed into it.

  1. Every equipment row in stash.sqlite and stash_iagd.sqlite is a card, and
     nothing else is -- derived from the databases and the catalogue.
  2. The user's rule (2026-09-28): component and augment are LEFT OFF. Every
     card built from an item that carries one equals the card built with them
     removed.
  3. A card's lines ARE item_lines.rolled() -- the composition
     tests/test_seedroll_game.py holds to the game's own tooltips -- so that
     evidence is evidence about what the view prints.
  4. A refused roll shows no numbers and says why. A crafting bonus rolls with
     the item (seedroll.MODIFIER_KINDS), so its card is the roll WITH it.

Reads the live stash databases, which every launch refills; nothing here is a
count typed in.
"""
import os
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from allostrias import settings as S                # noqa: E402
from allostrias import item_lines                   # noqa: E402
from allostrias.archive import seedroll             # noqa: E402
from allostrias.gearstash import build as GB        # noqa: E402
from allostrias.sheet import build as SB            # noqa: E402

cfg = S.load()
CACHE = os.path.join(S.ROOT, 'cache')


class NoArt(SB.Icons):
    """want() only records a path; nothing here packs the sheet."""

    def __init__(self):
        super().__init__(None, None)


def main():
    ca = sqlite3.connect(os.path.join(CACHE, 'catalogue.sqlite'))
    ca.row_factory = sqlite3.Row
    iagd_db = os.path.join(CACHE, 'stash_iagd.sqlite') if cfg.iagd else None
    if not cfg.iagd:
        print('UNCHECKED -- no IAGD configured, so only the transfer stash is covered')
    ix, icons = GB.Index(), NoArt()
    bad, cards, rows = [], [], []
    for source, where, r in GB.held(os.path.join(CACHE, 'stash.sqlite'), iagd_db):
        rows.append(r)
        c = GB.card(ca, ix, icons, source, where, r)
        if c is not None:
            cards.append((r, c))

    # 1. equipment, both halves, nothing else
    equip = 0
    for db, table in (('stash.sqlite', 'stash_item'), ('stash_iagd.sqlite', 'iagd_item')):
        if table == 'iagd_item' and not iagd_db:
            continue
        con = sqlite3.connect(os.path.join(CACHE, db))
        con.execute(f"ATTACH '{os.path.join(CACHE, 'catalogue.sqlite')}' AS ca")
        equip += con.execute(f'SELECT count(*) FROM {table} s JOIN ca.item i '
                             f'ON i.path = s.base_path WHERE i.is_equipment = 1').fetchone()[0]
    if len(cards) != equip:
        bad.append(f'{len(cards)} cards for {equip} equipment rows')
    if len(rows) - len(cards) != sum(1 for r in rows if not ca.execute(
            'SELECT is_equipment FROM item WHERE path = ?', (r['base_path'],)).fetchone()[0]):
        bad.append('a non-equipment row became a card, or equipment was dropped')

    # 2. component and augment change nothing
    socketed = 0
    for r, c in cards:
        if not (r['component_path'] or r['augment_path']):
            continue
        socketed += 1
        bare = dict(r)
        bare['component_path'] = bare['augment_path'] = None
        again = GB.card(ca, ix, icons, c['src'], c['at'], bare)
        if again != c:
            bad.append(f"{c['n']}: its component/augment changed the card")
    if not socketed:
        print('UNCOVERED -- no held item carries a component or augment')

    # 3. lines are the game-checked composition; 4. refusals and crafting bonus
    refused = n_crafted = 0
    for r, c in cards:
        base = SB.rec(r['base_path'])
        paths = {k: r[f'{k}_path'] for k in ('prefix', 'suffix') if r[f'{k}_path']}
        crafted = bool(r['modifier_path']) and base.get('Class', [''])[0] != 'ItemRelic'
        roll = seedroll.compute(base, r['seed'], *(SB.rec(paths.get(k)) for k in ('prefix', 'suffix')),
                                modifier=SB.rec(r['modifier_path']) if crafted else None)
        if roll.unmodeled:
            refused += 1
            if 'l' in c or 'g' in c or not c.get('why'):
                bad.append(f"{c['n']}: refused, yet it carries numbers or no reason")
            continue
        want = [t for _, t in item_lines.rolled(r['base_path'],
                                                {'base': r['base_path'], **paths}, roll)]
        if [t for t, _ in c['l']] != want:
            bad.append(f"{c['n']}: its lines are not item_lines.rolled()")
        n_crafted += crafted
    print(f'{len(cards)} cards ({equip} equipment rows), {socketed} with a component or '
          f'augment, {n_crafted} rolled with a crafting bonus, {refused} not replayed')
    if refused:
        print(f'UNPROVEN -- {refused} item(s) the seed replay does not model yet show no '
              f'stats. Lifting them is pinned in the backlog (the user moves one of each '
              f'into IAGD; test_seedroll_game.py then settles the roll).')
    if bad:
        print('\nFAIL')
        for b in bad[:25]:
            print('  ', b)
        raise SystemExit(1)
    print('OK')


if __name__ == '__main__':
    main()
