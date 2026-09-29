#!/usr/bin/env python3
"""The Augments & Components bundle: every augment, component and rune in the
game, with how each is obtained, what the account has unlocked and what is held.

    python3 -m allostrias.augments.build

  catalogue.sqlite    the records, who sells them at what standing (vendor_stock),
                      the blueprints that make them (recipe, recipe.known), drops
  stash.sqlite        the blueprints unlocked (formula), materials held (reagent)
  stash_iagd.sqlite   anything held in Item Assistant
  item_lines          the lines, at the record's stored values: none of these roll

The user's rules (2026-09-29): augments, components and runes (their own chip),
a Personal / Atlas switch, and a source badge on every card -- the faction and
standing that sells it, whether a blueprint is needed and how that blueprint is
had. Personal adds the character's standing against what is needed, whether the
account has unlocked the blueprint, and how many are held; and grades each card
as the Gear Stash grades an item.

What the character has is the PAGE's to compare: standings ship per character in
the sheet bundle, blueprints per core here. Nothing below knows a character.

A SOURCE THE DATA DOES NOT HAVE IS SHOWN AS MISSING, never guessed: three named
augments no vendor stocks say so. A quest reward (quest_reward) is its own
source, never a drop. A drop names who drops it when that is DROP_NAMED or
fewer named holders -- Kilrian's Shattered Soul, from Kilrian, the Tainted Soul.
"""
import json
import os
import re
import sqlite3
import sys

from .. import settings as S
from .. import item_lines
from .. import item_stats as I
from ..affixes import build as AB
from ..archive.textures import Textures
from ..gearstash import build as GB
from ..sheet import build as SB

OUT = os.path.join(S.ROOT, 'cache', 'augments')

# The folder a rune lives in is the game's own grouping: Runes, Glyphs and
# Emblems are ItemEnchantment like augments, and grant a skill instead of stats.
RUNE_FOLDER = 'records/items/enchants/runes/'

# Slot flags on an augment or component record -> the Affixes view's slot labels.
SLOT_FLAGS = {
    'head': 'Helm', 'shoulders': 'Shoulders', 'chest': 'Chest', 'hands': 'Gloves',
    'waist': 'Belt', 'legs': 'Legs', 'feet': 'Boots', 'ring': 'Ring',
    'amulet': 'Amulet', 'medal': 'Medal', 'axe': 'Axe', 'dagger': 'Dagger',
    'mace': 'Mace', 'scepter': 'Scepter', 'sword': 'Sword', 'ranged1h': 'Ranged',
    'shield': 'Shield', 'offhand': 'Off-Hand (Focus)', 'axe2h': 'Axe (2H)',
    'mace2h': 'Mace (2H)', 'sword2h': 'Sword (2H)', 'spear2h': 'Spear (2H)',
    'ranged2h': 'Ranged (2H)',
}

# The game's own "(Applied to ...)" / "(Used in ...)" clause, closing every
# record's itemText. It is the slot line the card prints: the flags above are for
# the chips, and a coarse bucket is never a label (Black Tallow is amulet+medal).
APPLIED = re.compile(r'\(((?:Applied to|Used in)[^)]*)\)\s*$')

GAMEFACTIONS = 'records/game/gamefactions.dbr'

# A drop from this many named holders or fewer lists them; more is just "Drops".
DROP_NAMED = 3


def dropped_by(ca, item_id):
    """0 when nothing drops it; else [holders, [names]] -- the names only when
    every holder is named and there are DROP_NAMED or fewer of them."""
    rows = ca.execute('SELECT DISTINCT h.name FROM item_drop d JOIN holder h ON h.id = d.holder_id '
                      'WHERE d.item_id = ?', (item_id,)).fetchall()
    if not rows:
        return 0
    names = sorted(r[0] for r in rows if r[0])
    return [len(rows), names if len(names) == len(rows) <= DROP_NAMED else []]


def quest_given(ca, item_id):
    return int(bool(ca.execute('SELECT 1 FROM quest_reward WHERE item_id = ?', (item_id,)).fetchone()))


def standings():
    """[[name, reputation it starts at]] for the positive tiers, lowest first, from
    gamefactions.dbr's factionTagN / factionValueN pairs."""
    g = SB.rec(GAMEFACTIONS)
    out = []
    for n in range(1, 9):
        tag, value = g.get(f'factionTag{n}'), g.get(f'factionValue{n}')
        if tag and value and float(value[0]) > 0:
            out.append([SB.tag(tag[0]), int(float(value[0]))])
    return sorted(out, key=lambda t: t[1])


def item_type(path, cls):
    if cls == 'ItemRelic':
        return 'Component'
    return 'Rune' if path.startswith(RUNE_FOLDER) else 'Augment'


def sold_by(ca, item_id, tiers):
    """[[faction id, standing]] -- the lowest standing each faction sells it at
    (two vendors of one faction can stock it at different tiers)."""
    rank = [n for n, _ in tiers]
    out = {}
    for f, s in ca.execute('SELECT v.faction_id, s.standing FROM vendor_stock s '
                           'JOIN vendor v ON v.id = s.vendor_id WHERE s.item_id = ?', (item_id,)):
        out[f] = min(out.get(f, s), s, key=rank.index)
    return sorted([f, s] for f, s in out.items())


def held(cfg):
    """{record path: {where: count}} across the materials tab, the transfer stash
    and Item Assistant. A mode other than the main one is named, as the Gear Stash
    names it."""
    out = {}

    def add(path, where, n):
        spot = out.setdefault(path.lower(), {})
        spot[where] = spot.get(where, 0) + n

    st = sqlite3.connect(os.path.join(S.ROOT, 'cache', 'stash.sqlite'))
    mode = lambda m: '' if m == 'gst' else f' ({m})'
    for path, m, n in st.execute('SELECT item_path, mode, count FROM reagent WHERE count > 0'):
        add(path, 'Materials' + mode(m), n)
    for path, m, n in st.execute('SELECT s.base_path, p.mode, s.stack FROM stash_item s '
                                 'JOIN stash_page p ON p.id = s.page_id'):
        add(path, 'Transfer' + mode(m), n)
    iagd = os.path.join(S.ROOT, 'cache', 'stash_iagd.sqlite')
    if cfg.iagd and os.path.exists(iagd):
        for path, n in sqlite3.connect(iagd).execute('SELECT base_path, stack FROM iagd_item'):
            add(path, 'IAGD', n)
    return out


def unlocked():
    """{'t': [blueprint path], 'h': [...]}: every blueprint any formulas file of
    that core lists (t softcore, h hardcore; gst.MODE_RE's last letter). A core
    with no formulas file is ABSENT, so the page can say "unknown" rather than
    "not unlocked"."""
    st = sqlite3.connect(os.path.join(S.ROOT, 'cache', 'stash.sqlite'))
    out = {}
    for mode, path in st.execute('SELECT mode, blueprint_path FROM formula'):
        out.setdefault(mode[-1], set()).add(path.lower())
    for (mode,) in st.execute("SELECT mode FROM source_file WHERE kind = 'formulas'"):
        out.setdefault(mode[-1], set())
    return out


def main(out_dir=None):
    out_dir = out_dir or OUT
    os.makedirs(out_dir, exist_ok=True)
    cfg = S.load()
    ca = sqlite3.connect(os.path.join(S.ROOT, 'cache', 'catalogue.sqlite'))
    ca.row_factory = sqlite3.Row
    icons = SB.Icons(Textures('Items.arc'), Textures('UI.arc'))
    ix = GB.Index()
    tiers = standings()
    have = held(cfg)
    known = unlocked()

    missing = {r['standing'] for r in ca.execute('SELECT DISTINCT standing FROM vendor_stock')} \
        - {n for n, _ in tiers}
    if missing:
        raise SystemExit(f'vendor standings gamefactions.dbr does not price: {sorted(missing)}')

    bps, bp_ix, items = [], {}, []
    for r in ca.execute("""SELECT id, path, class, coalesce(display_name, name) n, classification,
                                  level_req FROM item
                           WHERE class IN ('ItemEnchantment', 'ItemRelic') AND name IS NOT NULL
                           ORDER BY path"""):
        path, d = r['path'], SB.rec(r['path'])
        txt = SB.tag((d.get('itemText') or [''])[0]) or ''
        applied = APPLIED.search(txt)
        if not applied:
            raise SystemExit(f'{path}: no "(Applied to ...)" clause to name its slots')
        roll = item_lines.stored_roll(I.read_rel(path) or '')
        shown = item_lines.rolled(path, {'base': path}, roll)
        card = {
            'n': r['n'], 't': item_type(path, r['class']), 'r': r['classification'] or 'Common',
            'a': applied.group(1),
            'sl': [lbl for f, lbl in SLOT_FLAGS.items() if (d.get(f) or ['0'])[0] == '1'],
            'lv': r['level_req'] or 0,
            'i': icons.want(SB.item_icon(d) or (d.get('relicBitmap') or [None])[0]),
            'l': [[text, GB._verdict_key(ix, key)] for key, text in shown],
            'g': GB.grading(ix, {'base': d}, roll, shown),
            'buy': sold_by(ca, r['id'], tiers),
            'drop': dropped_by(ca, r['id']), 'quest': quest_given(ca, r['id']),
            'bp': [],
        }
        for b in ca.execute("""SELECT b.id, b.path, x.known FROM recipe x JOIN item b ON b.id = x.blueprint_id
                               WHERE x.output_item_id = ? ORDER BY b.path""", (r['id'],)):
            if b['path'] not in bp_ix:
                bp_ix[b['path']] = len(bps)
                bps.append({
                    'k': b['known'], 'buy': sold_by(ca, b['id'], tiers),
                    'drop': dropped_by(ca, b['id']), 'quest': quest_given(ca, b['id']),
                })
            card['bp'].append(bp_ix[b['path']])
        if not card['sl']:
            raise SystemExit(f'{path}: no slot flag')
        own = have.get(path.lower())
        if own:
            card['own'] = sorted(own.items())
        items.append(card)

    paths = list(bp_ix)
    sheet, frames = icons.pack()
    bundle = {
        'items': items, 'bps': bps, **ix.tables(),
        # Blueprint indexes each core's formulas files list; a core with none is absent.
        'unlocked': {core: sorted(bp_ix[p] for p in paths if p.lower() in got)
                     for core, got in known.items()},
        'factions': {f: n for f, n in ca.execute('SELECT id, name FROM faction')},
        'standings': tiers,
        'coarse': AB.COARSE_SLOT, 'slotGroups': AB.shipped_slot_groups(),
        'frames': frames, 'sheetSize': list(sheet.size),
        'atlas': SB.png_b64(sheet, quantize=255),
    }
    p = os.path.join(out_dir, 'augments.json')
    with open(p, 'w') as fh:
        json.dump(bundle, fh, separators=(',', ':'))
    kinds = {t: sum(1 for c in items if c['t'] == t) for t in ('Augment', 'Component', 'Rune')}
    print(f"{len(items)} cards ({', '.join(f'{n} {t}' for t, n in kinds.items())}), "
          f"{len(bps)} blueprints, {sum(1 for c in items if 'own' in c)} held, "
          f"unlocked {', '.join(f'{k}: {len(v)}' for k, v in bundle['unlocked'].items())}, "
          f"{len(frames)} icons, {os.path.getsize(p) / 1e6:.2f} MB -> {p}")


if __name__ == '__main__':
    sys.exit(main())
