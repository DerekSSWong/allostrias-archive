"""Gate: the Augments & Components bundle.

  - LINES. Augments, components and runes do not roll, so their lines come from
    item_lines.rolled() over the record's stored values (stored_roll). Held,
    per record, to the renderer run on the record text itself: the same lines,
    plus only the ones item_lines.SUPPLEMENT adds on purpose.
  - SOURCES, each derived here from the catalogue by its own query and compared
    card by card: who sells it at what standing, which blueprints make it and how
    each is had, whether it drops -- and the crafting table's default list read
    straight off its record, against recipe.known.
  - WHAT THE ACCOUNT HAS: the unlocked blueprints against stash.sqlite's formula
    table, and the held counts against the materials tab and both stashes.
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
from allostrias import item_lines as IL                 # noqa: E402
from allostrias import item_stats as I                  # noqa: E402
from allostrias.augments import build as AG             # noqa: E402
from allostrias.db.extract import recipes               # noqa: E402
from allostrias.sheet import build as SB                # noqa: E402

cfg = S.load()
ca = sqlite3.connect(cfg.catalogue_db)
ca.row_factory = sqlite3.Row
rows = ca.execute("""SELECT id, path FROM item WHERE class IN ('ItemEnchantment', 'ItemRelic')
                     AND name IS NOT NULL ORDER BY path""").fetchall()

# ---- lines ------------------------------------------------------------------
supplemented = 0
for r in rows:
    txt = I.read_rel(r['path']) or ''
    ours = collections.Counter(l for _, l in IL.rolled(r['path'], {'base': r['path']}, IL.stored_roll(txt)))
    renderer = collections.Counter(l for l in I.effects_of(txt) if l)
    extra = ours - renderer
    added = collections.Counter(IL.supplement(f, float(v)) for f, v in
                                (l.split('=', 1) for l in txt.splitlines() if '=' in l)
                                if f in IL.SUPPLEMENT and float(v))
    assert not renderer - ours, f"{r['path']}: lines the renderer prints are missing: {list(renderer - ours)}"
    assert extra == added, f"{r['path']}: lines beyond the renderer's: {list(extra)}"
    supplemented += bool(added)
print(f'{len(rows)} records: lines equal the renderer\'s, {supplemented} with a SUPPLEMENT line')
assert supplemented, 'no record exercises SUPPLEMENT'

# ---- recipe.known is the crafting table's list -------------------------------
listed = {p.lower() for p in SB.rec(recipes.CRAFTING_TABLE)[recipes.DEFAULTS_FIELD]}
known = {p for (p,) in ca.execute('SELECT b.path FROM recipe x JOIN item b ON b.id = x.blueprint_id '
                                  'WHERE x.known')}
assert known == listed, f'recipe.known differs from {recipes.DEFAULTS_FIELD}: {len(known ^ listed)}'
print(f'recipe.known: the {len(listed)} blueprints the crafting table lists')

# ---- the bundle -------------------------------------------------------------
with tempfile.TemporaryDirectory() as tmp:
    AG.main(out_dir=tmp)
    B = json.load(open(os.path.join(tmp, 'augments.json')))
cards = B['items']
assert len(cards) == len(rows), f'{len(cards)} cards for {len(rows)} named records'

def sold(item_id):
    out = {}
    for f, s in ca.execute('SELECT v.faction_id, s.standing FROM vendor_stock s '
                           'JOIN vendor v ON v.id = s.vendor_id WHERE s.item_id = ?', (item_id,)):
        rank = [n for n, _ in B['standings']].index(s)
        out[f] = min(out.get(f, rank), rank)
    return {f: B['standings'][k][0] for f, k in out.items()}

def drops(item_id):
    names = [n for (n,) in ca.execute('SELECT DISTINCT h.name FROM item_drop d JOIN holder h '
                                      'ON h.id = d.holder_id WHERE d.item_id = ?', (item_id,))]
    if not names:
        return 0
    named = sorted(n for n in names if n)
    return [len(names), named if len(named) == len(names) <= AG.DROP_NAMED else []]

quest = lambda item_id: int(bool(ca.execute('SELECT 1 FROM quest_reward WHERE item_id = ?',
                                            (item_id,)).fetchone()))
routes = collections.Counter()
for r, c in zip(rows, cards):
    assert dict(c['buy']) == sold(r['id']), (c['n'], c['buy'], sold(r['id']))
    assert c['drop'] == drops(r['id']) and c['quest'] == quest(r['id']), c['n']
    bps = ca.execute('SELECT b.id, x.known FROM recipe x JOIN item b ON b.id = x.blueprint_id '
                     'WHERE x.output_item_id = ? ORDER BY b.path', (r['id'],)).fetchall()
    assert len(bps) == len(c['bp']), (c['n'], len(bps), c['bp'])
    for b, i in zip(bps, c['bp']):
        got = B['bps'][i]
        assert got['k'] == b['known'] and dict(got['buy']) == sold(b['id']) \
            and got['drop'] == drops(b['id']) and got['quest'] == quest(b['id']), (c['n'], got)
    route = ('sold' if c['buy'] else '') + ('+blueprint' if c['bp'] else '') \
        + ('+drops' if c['drop'] else '') + ('+quest' if c['quest'] else '')
    routes[(c['t'], route or 'NO SOURCE')] += 1
    assert c['sl'] and c['a'], c['n']
unsourced = [(c['n'], i) for c in cards for i in c['bp']
             if not (B['bps'][i]['k'] or B['bps'][i]['buy'] or B['bps'][i]['drop'] or B['bps'][i]['quest'])]
print(f'blueprints with no source in the data: {len(unsourced)} {unsourced[:5]}')
kilrian = next(c for c in cards if c['n'] == "Kilrian's Shattered Soul")
assert kilrian['drop'] and kilrian['drop'][1] == ['Kilrian, the Tainted Soul'], kilrian['drop']
print('sources, card by card, as the catalogue answers them:')
for k, v in sorted(routes.items()):
    print(f'  {v:4} {k[0]:10} {k[1]}')

# Every standing a vendor sells at is one gamefactions.dbr prices.
standings = {n for n, _ in B['standings']}
assert {s for c in cards for _, s in c['buy']} | {s for b in B['bps'] for _, s in b['buy']} <= standings

# ---- what the account has ------------------------------------------------------
st = sqlite3.connect(cfg.stash_db)
by_core = {}
for mode, p in st.execute('SELECT mode, blueprint_path FROM formula'):
    by_core.setdefault(mode[-1], set()).add(p.lower())
bp_path = {}
for r, c in zip(rows, cards):
    for i, (p,) in zip(c['bp'], ca.execute('SELECT b.path FROM recipe x JOIN item b ON b.id = x.blueprint_id '
                                           'WHERE x.output_item_id = ? ORDER BY b.path', (r['id'],))):
        bp_path[i] = p
assert set(B['unlocked']) == set(by_core), (set(B['unlocked']), set(by_core))
for core, got in by_core.items():
    want = sorted(i for i, p in bp_path.items() if p in got)
    assert B['unlocked'][core] == want, f'core {core}: unlocked blueprints differ'
    print(f"core {core}: {len(want)} of {len(bp_path)} blueprints these need are unlocked")

held = collections.Counter()
for p, n in st.execute('SELECT item_path, count FROM reagent'):
    held[p.lower()] += n
for p, n in st.execute('SELECT base_path, stack FROM stash_item'):
    held[p.lower()] += n
iagd = os.path.join(S.ROOT, 'cache', 'stash_iagd.sqlite')
if cfg.iagd and os.path.exists(iagd):
    for p, n in sqlite3.connect(iagd).execute('SELECT base_path, stack FROM iagd_item'):
        held[p.lower()] += n
for r, c in zip(rows, cards):
    assert sum(n for _, n in c.get('own', [])) == held[r['path'].lower()], (c['n'], c.get('own'))
print(f"held: {sum(1 for c in cards if 'own' in c)} cards, counts as the stashes hold them")
print('\nAUGMENTS OK')
