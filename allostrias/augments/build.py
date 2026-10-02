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

The sources and held counts are allostrias/sources.py's, shared with the Gear
Catalogue. Three named augments no vendor stocks say so.
"""
import json
import os
import re
import sqlite3
import sys

from .. import settings as S
from .. import item_lines
from .. import item_stats as I
from .. import sources as SR
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


def item_type(path, cls):
    if cls == 'ItemRelic':
        return 'Component'
    return 'Rune' if path.startswith(RUNE_FOLDER) else 'Augment'


def main(out_dir=None):
    out_dir = out_dir or OUT
    os.makedirs(out_dir, exist_ok=True)
    cfg = S.load()
    ca = sqlite3.connect(os.path.join(S.ROOT, 'cache', 'catalogue.sqlite'))
    ca.row_factory = sqlite3.Row
    icons = SB.Icons(Textures('Items.arc'), Textures('UI.arc'))
    ix = GB.Index()
    tiers = SR.standings()
    SR.check_standings(ca, tiers)
    have = SR.held(cfg)
    bps = SR.Blueprints(ca, tiers)

    items = []
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
            **SR.sources(ca, [r['id']], tiers), 'bp': bps.of([r['id']]),
        }
        if not card['sl']:
            raise SystemExit(f'{path}: no slot flag')
        own = have.get(path.lower())
        if own:
            card['own'] = sorted(own.items())
        items.append(card)

    sheet, frames = icons.pack()
    bundle = {
        'items': items, 'bps': bps.table(), **ix.tables(),
        # Blueprint indexes each core's formulas files list; a core with none is absent.
        'unlocked': bps.unlocked(SR.unlocked()),
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
          f"{len(bundle['bps'])} blueprints, {sum(1 for c in items if 'own' in c)} held, "
          f"unlocked {', '.join(f'{k}: {len(v)}' for k, v in bundle['unlocked'].items())}, "
          f"{len(frames)} icons, {os.path.getsize(p) / 1e6:.2f} MB -> {p}")


if __name__ == '__main__':
    sys.exit(main())
