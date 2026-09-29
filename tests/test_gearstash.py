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
  5. The user's rule (2026-09-29): Epic/Legendary copies of one base record are
     one card. Every copy's every number lies inside its merged line, and every
     range's ends were rolled by some copy. A crafting bonus not of one stat on
     every copy is taken out and named instead.
  6. A card's required level is the game's "Required Player Level" on every
     IAGD item (ReplicaItemRow). It is the one thing a component DOES move.

Reads the live stash databases, which every launch refills; nothing here is a
count typed in.
"""
import os
import re
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from allostrias import settings as S                # noqa: E402
from allostrias import item_lines                   # noqa: E402
from allostrias.archive import seedroll             # noqa: E402
from allostrias.db import iagd                      # noqa: E402
from allostrias.gearstash import build as GB        # noqa: E402
from allostrias.sheet import build as SB            # noqa: E402

cfg = S.load()
CACHE = os.path.join(S.ROOT, 'cache')


class NoArt(SB.Icons):
    """want() only records a path; nothing here packs the sheet."""

    def __init__(self):
        super().__init__(None, None)


_TOKEN = re.compile(r'\[(\d+(?:\.\d+)?)–(\d+(?:\.\d+)?)\]|(\d+(?:\.\d+)?)')
_ON = re.compile(r' \(on (\d+) of (\d+) copies\)$')


def _spans(text):
    """(shape, [(lo, hi)]) of a merged line; a plain number is lo == hi."""
    text = _ON.sub('', text)
    spans = [(float(a), float(b)) if a else (float(n), float(n)) for a, b, n in _TOKEN.findall(text)]
    return GB.shape(_TOKEN.sub('0', text)), spans


def merged(ca, ix, cards):
    """5: the merge, re-derived from the per-copy cards."""
    bad, groups, order = [], {}, []
    for r, c in cards:
        k = r['base_path'] if c['r'] in GB.MERGED and 'why' not in c else id(c)
        if k not in groups:
            groups[k] = []
            order.append(k)
        groups[k].append((r, c))
    out = GB.merge(ca, ix, cards)
    if len(out) != len(order):
        return [f'{len(out)} cards after merging, {len(order)} distinct items']
    n_merged = 0
    for k, m in zip(order, out):
        members = groups[k]
        if len(members) == 1:
            if m is not members[0][1]:
                bad.append(f"{m['n']}: a single copy was changed by the merge")
            continue
        n_merged += 1
        name = members[0][1]['n']
        if m['n'] != name or m['x'] != [c['x'][0] for _, c in members]:
            bad.append(f'{name}: the merged card is not its {len(members)} copies')
            continue
        replays = [GB._roll(ca, r)[1] for r, _ in members]
        kinds = [GB.bonus_kind(rp.roll) for rp in replays]
        if len(set(kinds)) == 1:
            copies = [c['l'] for _, c in members]
        else:
            copies = [GB._face_uncrafted(ix, rp)[0] for rp in replays]
            n_kinds, crafted = len({x for x in kinds if x}), sum(1 for x in kinds if x)
            want = ('crafting bonus' if n_kinds == 1 else f'{n_kinds} different crafting bonuses') + (
                f' on {crafted} of {len(members)} copies' if crafted < len(members) else '')
            if m['l'][-1] != [f'({want})', 0]:
                bad.append(f'{name}: its crafting bonuses differ, yet it says {m["l"][-1][0]!r}')
            only = {f for rp in replays for f, per in rp.roll.parts.items()
                    if set(per) == {'modifier'}}
            if {GB._verdict_key(ix, f) for f in only} & {kk for _, kk in m['l']}:
                bad.append(f'{name}: a differing crafting bonus is still printed')
        lines = [(_spans(t), kk, t) for t, kk in m['l']]
        hit = [[] for _ in lines]
        for cl in copies:
            for t, kk in cl:
                sh = GB.shape(t)
                nums = [float(x) for x in GB._NUM.findall(t)]
                at = next((i for i, ((s2, sp), k2, _) in enumerate(lines)
                           if k2 == kk and s2 == sh and len(sp) == len(nums)
                           and all(lo <= v <= hi for v, (lo, hi) in zip(nums, sp))), None)
                if at is None:
                    bad.append(f'{name}: {t!r} lies in no merged line')
                else:
                    hit[at].append(nums)
        for ((_, sp), _, t), got in zip(lines, hit):
            if not got:
                continue            # the crafting-bonus note
            if any(not any(g[i] == lo for g in got) or not any(g[i] == hi for g in got)
                   for i, (lo, hi) in enumerate(sp)):
                bad.append(f'{name}: {t!r} has an end no copy rolled')
            on = _ON.search(t)
            if (int(on.group(1)) if on else len(members)) != len(got) or (on and len(got) == len(members)):
                bad.append(f'{name}: {t!r} is on {len(got)} of {len(members)} copies')
    print(f'{n_merged} merged cards, {len(out)} cards in all')
    return bad


_REQ = re.compile(r'Required Player Level: (\d+)')


def required(cards):
    """6: every IAGD card's lv is the level the game's tooltip requires."""
    if not cfg.iagd:
        print('UNCHECKED -- no IAGD configured, so no game tooltip to hold required levels to')
        return []
    game = {}
    for pid, x in iagd._connect(cfg.iagd).execute(
            'SELECT i.playeritemid, r.Text FROM ReplicaItemRow r '
            'JOIN ReplicaItem2 i ON i.Id = r.replicaitemid WHERE r.Type = 20'):
        m = _REQ.search(x)
        if m:
            game[pid] = int(m.group(1))
    bad, n, raised = [], 0, 0
    for r, c in cards:
        if c['x'][0][0] != 'IAGD' or r['id'] not in game:
            continue
        n += 1
        raised += bool(r['component_path']) and c['lv'] > GB.required_level(dict(r, component_path=None))
        if c['lv'] != game[r['id']]:
            bad.append(f"{c['n']}: requires level {c['lv']}, the game says {game[r['id']]}")
    print(f'required level: {n} IAGD items against the game, {raised} raised by a component')
    if not n:
        bad.append('no IAGD item has a game tooltip to hold its required level to')
    if not raised:
        print('UNCOVERED -- no held component raises a required level')
    return bad


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

    # 0. The Refresh server's case: a second build in one process reuses every
    # replay and must give the same cards. Fresh tables, so the slot numbers are
    # assigned again from nothing, as on every click. A card that edited a shared
    # replay would show up here too.
    replayed = len(GB._REPLAYS)
    ix2, icons2 = GB.Index(), NoArt()
    again = [GB.card(ca, ix2, icons2, s, w, r)
             for s, w, r in GB.held(os.path.join(CACHE, 'stash.sqlite'), iagd_db)]
    if len(GB._REPLAYS) != replayed:
        bad.append(f'the second build replayed {len(GB._REPLAYS) - replayed} items again')
    if [c for c in again if c is not None] != [c for _, c in cards] or ix2.tables() != ix.tables():
        bad.append('a build from cached replays differs from the first build')
    print(f'second build from {replayed} cached replays: identical')

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
        again = GB.card(ca, ix, icons, *c['x'][0], bare)
        if dict(again, lv=0) != dict(c, lv=0):
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
    bad += merged(ca, ix, cards)
    bad += required(cards)
    if bad:
        print('\nFAIL')
        for b in bad[:25]:
            print('  ', b)
        raise SystemExit(1)
    print('OK')


if __name__ == '__main__':
    main()
