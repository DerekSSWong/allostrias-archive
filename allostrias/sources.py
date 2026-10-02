"""How an item is had, and how many are held: the source rows the Augments &
Components and Gear Catalogue views print, read from the catalogue and the stashes.

  catalogue.sqlite    who sells it at what standing (vendor_stock), the blueprints
                      that make it (recipe, recipe.known), drops, quest rewards
  stash.sqlite        the blueprints unlocked (formula), materials held (reagent)
  stash_iagd.sqlite   anything held in Item Assistant

A SOURCE THE DATA DOES NOT HAVE IS SHOWN AS MISSING by the page, never guessed. A
quest reward (quest_reward) is its own source, never a drop. A drop names who
drops it when that is DROP_NAMED or fewer named holders -- Kilrian's Shattered
Soul, from Kilrian, the Tainted Soul.
"""
import os
import sqlite3

from . import settings as S
from .sheet import build as SB

GAMEFACTIONS = 'records/game/gamefactions.dbr'

# A drop from this many named holders or fewer lists them; more is just "Drops".
DROP_NAMED = 3

# A player's summon wears its gear through a loot table, so the drop walk reaches
# that gear and names the summon as its holder: the revenant Ognapesh's own Cruel
# Edge "dropped" from itempet_revenant_ognapesh.dbr. item_drop is reachability and
# keeps them; a source is a drop from anything else.
SUMMONS = ('Pet', 'PetPlayerScaling', 'Turret')
_DROPS = ('FROM item_drop d JOIN holder h ON h.id = d.holder_id '
          f"WHERE h.class NOT IN ({', '.join(repr(c) for c in SUMMONS)})")

# True for an item row `i` the game data gives any source: a drop, a vendor, a
# quest or a blueprint. Every source row the page prints answers to one of these.
SOURCED = f"""(EXISTS (SELECT 1 {_DROPS} AND d.item_id = i.id)
               OR EXISTS (SELECT 1 FROM vendor_stock WHERE item_id = i.id)
               OR EXISTS (SELECT 1 FROM quest_reward WHERE item_id = i.id)
               OR EXISTS (SELECT 1 FROM recipe WHERE output_item_id = i.id))"""


# Every function below takes `ids`: the records one card stands for -- one for an
# augment, every level of an item for the Gear Catalogue.
def _in(ids):
    return f"({','.join('?' * len(ids))})"


def dropped_by(ca, ids):
    """0 when nothing drops it; else [holders, [names]] -- the names only when
    every holder is named and there are DROP_NAMED or fewer of them."""
    rows = ca.execute(f'SELECT DISTINCT h.name {_DROPS} AND d.item_id IN {_in(ids)}', ids).fetchall()
    if not rows:
        return 0
    names = sorted(r[0] for r in rows if r[0])
    return [len(rows), names if len(names) == len(rows) <= DROP_NAMED else []]


def quest_given(ca, ids):
    return int(bool(ca.execute(f'SELECT 1 FROM quest_reward WHERE item_id IN {_in(ids)}', ids).fetchone()))


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


def check_standings(ca, tiers):
    """Refuses a vendor standing gamefactions.dbr does not price."""
    missing = {r[0] for r in ca.execute('SELECT DISTINCT standing FROM vendor_stock')} \
        - {n for n, _ in tiers}
    if missing:
        raise SystemExit(f'vendor standings gamefactions.dbr does not price: {sorted(missing)}')


def sold_by(ca, ids, tiers):
    """[[faction id, standing]] -- the lowest standing each faction sells it at
    (two vendors of one faction can stock it at different tiers)."""
    rank = [n for n, _ in tiers]
    out = {}
    for f, s in ca.execute('SELECT v.faction_id, s.standing FROM vendor_stock s '
                           f'JOIN vendor v ON v.id = s.vendor_id WHERE s.item_id IN {_in(ids)}', ids):
        out[f] = min(out.get(f, s), s, key=rank.index)
    return sorted([f, s] for f, s in out.items())


def sources(ca, ids, tiers):
    """The item's own source fields as a card ships them."""
    return {'buy': sold_by(ca, ids, tiers), 'drop': dropped_by(ca, ids),
            'quest': quest_given(ca, ids)}


class Blueprints:
    """The blueprints cards point at, each shipped once: `table()` is
    [{k, buy, drop, quest}], and a card's `bp` indexes it."""

    def __init__(self, ca, tiers):
        self.ca, self.tiers = ca, tiers
        self.rows, self.ix = [], {}

    def of(self, ids):
        """Indexes of the blueprints that make any of `ids`."""
        out = []
        for b in self.ca.execute(f"""SELECT DISTINCT b.id, b.path, x.known FROM recipe x
                                     JOIN item b ON b.id = x.blueprint_id
                                     WHERE x.output_item_id IN {_in(ids)} ORDER BY b.path""", ids):
            if b[1] not in self.ix:
                self.ix[b[1]] = len(self.rows)
                self.rows.append({'k': b[2], **sources(self.ca, [b[0]], self.tiers)})
            out.append(self.ix[b[1]])
        return out

    def table(self):
        return self.rows

    def unlocked(self, known):
        """unlocked() as indexes into table(): per core, the blueprints its
        formulas files list; a core with none is absent."""
        return {core: sorted(i for p, i in self.ix.items() if p.lower() in got)
                for core, got in known.items()}


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
