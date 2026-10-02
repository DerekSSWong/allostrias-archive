"""Gate: the Gear Catalogue bundle.

  - THE FOLD, derived here by its own queries over the catalogue: an MI is one
    card per name, an Epic or Legendary one per name, style and tier; only records
    with a source count; the card's level span is theirs, its variants the ones at
    the top level.
  - THE GAME'S OWN TEXT, read off grimtools by the user (2026-10-02), pinned line
    by line: the banded numbers, the levels, which records exist at all.
  - RELICS: every one with a source, each with its completion bonus pool.
  - A STAT THE CATALOGUE CANNOT BAND prints its stored value, flagged, never a range.
  - HELD: the account file's counts against the stashes, summed per card.
"""
import collections
import json
import os
import sqlite3
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from allostrias import settings as S                    # noqa: E402
from allostrias import sources as SR                    # noqa: E402
from allostrias.gearcat import build as GC              # noqa: E402

cfg = S.load()
ca = sqlite3.connect(cfg.catalogue_db)
ca.row_factory = sqlite3.Row

with tempfile.TemporaryDirectory() as tmp:
    GC.main(out_dir=tmp)
    B = json.load(open(os.path.join(tmp, 'gearcat.json')))
    A = json.load(open(os.path.join(tmp, 'account.json')))
items = B['items']
by_name = collections.defaultdict(list)
for i, it in enumerate(items):
    by_name[it['n']].append(i)

# ---- the fold ------------------------------------------------------------------
rows = ca.execute(f"""
    SELECT i.id, i.path, i.name, coalesce(i.style, '') style, i.classification, i.class,
           i.is_mi, coalesce(i.level_req, 0) lv, {SR.SOURCED} sourced
    FROM item i WHERE i.name IS NOT NULL
      AND ((i.is_equipment = 1 AND (i.is_mi = 1 OR i.classification IN ('Epic', 'Legendary')))
           OR i.class = 'ItemArtifact')""").fetchall()
groups = collections.defaultdict(list)
for r in rows:
    if r['sourced']:
        key = (('relic', r['path']) if r['class'] == 'ItemArtifact'
               else ('mi', r['name']) if r['is_mi'] else (r['name'], r['style'], r['classification']))
        groups[key].append(r)
assert len(items) == len(groups), f'{len(items)} cards for {len(groups)} sourced groups'
spans = collections.Counter()
variants = 0
for key, rs in groups.items():
    lvs = sorted({r['lv'] for r in rs})
    want = lvs[0] if len(lvs) == 1 else [lvs[0], lvs[-1]]
    top = [r for r in rs if r['lv'] == lvs[-1]]
    kind = 'Relic' if key[0] == 'relic' else 'MI' if key[0] == 'mi' else key[2]
    spans[kind] += isinstance(want, list)
    variants += len(top) > 1
mi_names = {k[1] for k in groups if k[0] == 'mi'}
mi_cards = [it for it in items if it['t'] == 'MI']
assert len(mi_cards) == len(mi_names), f'{len(mi_cards)} MI cards for {len(mi_names)} names'
assert sum('nv' in it for it in items) == variants, \
    f"{sum('nv' in it for it in items)} cards fold variants, {variants} groups have several at the top"
assert sum(isinstance(it['lv'], list) for it in items) == sum(spans.values())
# Sourceless records exist, and none reaches a card.
dead = [r for r in rows if not r['sourced']]
assert dead, 'every record has a source, so the SOURCED rule is untested'
print(f'{len(items)} cards from {len(groups)} sourced groups ({len(mi_names)} MI names), '
      f'{variants} folding variants, {sum(spans.values())} spanning levels; '
      f'{len(dead)} sourceless records left out')

# ---- the game's own text ---------------------------------------------------------
def card(name):
    found = by_name.get(name, [])
    assert len(found) == 1, f'{name}: {len(found)} cards'
    return items[found[0]]


def has(name, *lines):
    got = [t for t, _ in card(name)['l']]
    for l in lines:
        assert l in got, f'{name}: no line {l!r} in {got}'


# Four sourceless lvl-30 records made Will of Bysmiel read 30-58.
assert card('Will of Bysmiel')['lv'] == 58, card('Will of Bysmiel')['lv']
assert card('Mythical Will of Bysmiel')['lv'] == 84
has('Will of Bysmiel', '+27–40% Chaos dmg', '+96–144 Health', '+18–26 Defensive Ability',
    '+13–19% Chaos Resist', 'Pet: +20–30% Health', 'Pet: +5–7% Defensive Ability')
has('Mythical Will of Bysmiel', '+54–79% Chaos dmg', '+480–720 Health', '+64–96 Defensive Ability')
# A damage pair is the Min's band plus the spread's: the game's "3-4/5-8".
has("Beast Slayer's Mark", '(+3–5)–(4–8) Physical dmg', '+15–21% Physical dmg', '+36–54 Offensive Ability')
has("Empowered Beast Slayer's Mark", '(+3–6)–(4–9) Physical dmg')
has("Mythical Beast Slayer's Mark", '(+14–19)–(17–24) Physical dmg')
has("Alazra's Ruby", '(+1–3)–(2–6) Fire dmg', '+20–28% Fire Resist')
has("Empowered Alazra's Ruby", '(+6–9)–(8–13) Fire dmg')
has("Mythical Alazra's Ruby", '(+11–16)–(14–21) Fire dmg')
has('Cruel Edge', '(2–4)–(9–13) Physical Damage', '+20–28 Offensive Ability',
    '30% Chance of +56–84% Physical dmg')
# Cruel Edge's other records: sourceless, and a summon's own weapon.
assert 'nv' not in card('Cruel Edge') and card('Cruel Edge')['lv'] == 14
assert card('Flamebreaker')['lv'] == 17, card('Flamebreaker')['lv']
for name, lv in (("Alazra's Ruby", 15), ("Beast Slayer's Mark", 22), ('Mythical Cruel Edge', 82)):
    assert card(name)['lv'] == lv, f"{name}: level {card(name)['lv']}, the game {lv}"
print('the game\'s text: 12 cards, every pinned line and level exact')

# ---- relics ------------------------------------------------------------------------
relics = [it for it in items if it['t'] == 'Relic']
assert len(relics) == sum(1 for k in groups if k[0] == 'relic')
pools = dict(ca.execute("""SELECT x.item_id, count(*) FROM item_bonus x
                           WHERE x.relation = 'completion' GROUP BY x.item_id"""))
relic_ids = [rs[0]['id'] for k, rs in groups.items() if k[0] == 'relic']
assert sum(1 for i in relic_ids if i in pools) == sum('cb' in it for it in relics)
assert all(len(B['pools'][it['cb']]) >= 1 for it in relics if 'cb' in it)
has('Dirge of Arkovia', '+23–33% Vitality Resist', '+15–21% Elemental Resist', 'Pet: +40–60% All Damage')
print(f"{len(relics)} relics, {sum('cb' in it for it in relics)} with a completion pool, "
      f"{len(B['pools'])} distinct pools; Dirge of Arkovia equals grimdb")

# ---- an unbanded stat ----------------------------------------------------------------
flagged = [t for it in items for t, _ in it['l'] if GC.UNBANDED in t]
assert flagged, 'no line is flagged unbanded, so the flag is untested'
assert all('–' not in t for t in flagged), [t for t in flagged if '–' in t]
print(f'{len(flagged)} unbanded lines, each a single stored value')

# ---- held ------------------------------------------------------------------------------
have = SR.held(cfg)
want = 0
for rs in groups.values():
    want += sum(c for r in rs for c in have.get(r['path'].lower(), {}).values())
got = sum(c for own in A['own'].values() for _, c in own)
assert got == want, f'account.json holds {got}, the stashes {want}'
print(f"held: {len(A['own'])} cards, {got} copies")
print('\nPASS')
