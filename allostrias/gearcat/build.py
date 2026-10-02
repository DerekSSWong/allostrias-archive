#!/usr/bin/env python3
"""The Gear Catalogue bundle: every Monster Infrequent, Epic and Legendary item and
every relic in the game, each line at the RANGE it rolls between.

    python3 -m allostrias.gearcat.build

  catalogue.sqlite    the records, each stat's band (item_stat.lo/hi, rolls.band),
                      pet and completion bonuses (bonus_stat), sources
  item_lines          the lines, rendered once at each end of every band
  sources.py          how each is had, and how many are held

The user's rules (2026-10-02):
  - An MI is ONE card per name; an Epic or Legendary one per name, style and tier
    (a Mythical is not its base). The card's lines are its HIGHEST-level record's,
    and Required Player Level spans the lowest to the highest.
  - Where several different records share that highest level (Ravager's Gaze's
    three resist variants), they fold into one card: each number at the range it
    rolls across them, and a line not every variant carries says on how many.
  - The item's own stats only: the random affixes an MI rolls are left off.
  - A relic's completion bonus pool is listed in a hover tooltip.
  - Held counts every copy of any record a card stands for.
  - Only records the game data gives a source count (SCOPE).

A STAT THE CATALOGUE CANNOT BAND (item_stat.roll 'unmodeled') prints at its stored
value and SAYS SO; a range would claim it rolls, a bare number that it does not.

What is held and which blueprints are unlocked is the account's, and moves with
every Refresh: it is a second file (account.json, `account()`), so the cards --
which only a new catalogue or new code can change -- are built once and reused.
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
from ..db import catalogue
from ..gearstash import build as GB
from ..sheet import build as SB

OUT = os.path.join(S.ROOT, 'cache', 'gearcat')

# Only records the game data gives a source (sources.SOURCED) -- a drop, a
# vendor, a quest or a blueprint. The user's rule (2026-10-02), after the sourceless ones were found
# skewing the fold: four lvl-30 Will of Bysmiel records that no table names made
# it read "30-58" where the game has one at 58, and Flamebreaker's top level (20)
# belonged to sourceless copies only. A card none of whose records has a source
# is not shown.
SCOPE = """
    SELECT id, path, class, name, coalesce(style, '') style, classification,
           coalesce(level_req, 0) lv, is_mi
    FROM item i
    WHERE name IS NOT NULL
      AND ((is_equipment = 1 AND (is_mi = 1 OR classification IN ('Epic', 'Legendary')))
           OR class = 'ItemArtifact')
      AND """ + SR.SOURCED + """
    ORDER BY path"""

RELIC = 'ItemArtifact'

# Fields the catalogue leaves 'unmodeled' that are known not to roll: a +skill
# level does not jitter (db/extract/bonuses.py), and racialBonus* is printed at the
# record's value (item_lines.rolled). Every other unmodeled field a line prints is
# flagged on the card.
NOT_ROLLING = re.compile(r'^(racialBonus|augmentSkillLevel|augmentMasteryLevel|augmentAllLevel)')
UNBANDED = ' (roll range not modeled)'


def kind(r):
    """The card's type chip: MI, Epic, Legendary or Relic."""
    if r['class'] == RELIC:
        return 'Relic'
    return 'MI' if r['is_mi'] else r['classification']


def groups(ca):
    """[(rows)] per card, in a fixed order: the account file indexes them."""
    out = {}
    for r in ca.execute(SCOPE):
        if r['class'] == RELIC:
            key = ('relic', r['path'])
        elif r['is_mi']:
            key = ('mi', r['name'])
        else:
            key = (r['name'], r['style'], r['classification'])
        out.setdefault(key, []).append(r)
    return list(out.values())


# ---- one record's lines at each end of its bands --------------------------------

def _ends(rows):
    """(lo, hi, unknown) from (field, lo, hi) rows: the value at each end of every
    band, and the fields with none."""
    lo, hi, unknown = {}, {}, set()
    for f, a, b in rows:
        if a is None:
            unknown.add(f)
        else:
            lo[f], hi[f] = a, b
    return lo, hi, unknown


def _pet_ends(ca, item_id):
    """(lo Roll, hi Roll, unknown fields) for the item's pet bonus, or None."""
    row = ca.execute("""SELECT b.id, b.path FROM item_bonus x JOIN bonus b ON b.id = x.bonus_id
                        WHERE x.item_id = ? AND x.relation = 'pet'""", (item_id,)).fetchone()
    if row is None:
        return None
    txt = I.apply_skill_level(I.read_rel(row['path']) or '', 0)
    lo, hi, unknown = _ends(ca.execute(
        'SELECT field, lo, hi FROM bonus_stat WHERE bonus_id = ? AND idx = 0 AND value IS NOT NULL',
        (row['id'],)))
    return (item_lines.stored_roll(AB._with_values(txt, lo)),
            item_lines.stored_roll(AB._with_values(txt, hi)), unknown)


def _pair(lo_lines, hi_lines):
    """[(key, lo text, hi text)]. A damage pair whose Min and Max meet at the low
    end prints one number there and two at the high end, under the Min's key and
    the Max's: the low end then takes the high end's shape, both numbers equal."""
    if len(lo_lines) != len(hi_lines):
        raise ValueError(f'{len(lo_lines)} lines at the low roll, {len(hi_lines)} at the high')
    stem = lambda k: re.sub(r'(Min|Max)$', '', k or '')
    out = []
    for (ka, a), (kb, b) in zip(lo_lines, hi_lines):
        if ka != kb:
            na, nb = AB._NUM.findall(a), AB._NUM.findall(b)
            if stem(ka) != stem(kb) or len(na) != 1 or len(nb) != 2:
                raise ValueError(f'lines differ between the low and the high roll: {a!r} / {b!r}')
            a = AB._NUM.sub(lambda _: na[0], b)
        out.append((kb, a, b))
    return out


def banded(ca, r):
    """(lines, grading) for one record: lines as [(key, lo text, hi text)], an
    unbanded stat's carrying UNBANDED, graded at the high end (the scorer reads
    which lines an item carries, never their values)."""
    path = r['path']
    txt = I.read_rel(path) or ''
    lo, hi, unknown = _ends(ca.execute(
        'SELECT field, lo, hi FROM item_stat WHERE item_id = ? AND idx = 0 AND num IS NOT NULL',
        (r['id'],)))
    pets = _pet_ends(ca, r['id'])
    pet_lo, pet_hi = ({'base': pets[0]}, {'base': pets[1]}) if pets else ({}, {})
    unknown = {f for f in unknown if not NOT_ROLLING.match(f)}
    unknown |= {'pet:' + f for f in (pets[2] if pets else ())}
    roll_hi = item_lines.stored_roll(AB._with_values(txt, hi))
    shown_hi = item_lines.rolled(path, {'base': path}, roll_hi, pets=pet_hi)
    shown_lo = item_lines.rolled(path, {'base': path},
                                 item_lines.stored_roll(AB._with_values(txt, lo)), pets=pet_lo)
    lines = []
    for key, a, b in _pair(shown_lo, shown_hi):
        f = key or ''
        if f in unknown or f + 'Min' in unknown or (f.startswith('pet:') and f[4:] + 'Min' in unknown):
            a, b = a + UNBANDED, b + UNBANDED
        lines.append((key, a, b))
    return lines, (SB.rec(path), roll_hi, shown_hi)


def merge_variants(ix, variants):
    """[[text, verdict key]] from each variant's banded lines: each line once, every
    number at the widest range across the variants, and a line not every variant
    carries saying on how many. One variant is the common case and comes out as
    its own bands."""
    order, got = [], {}
    for lines in variants:
        seen, prev = {}, None
        for key, a, b in lines:
            s = (key, GB.shape(b))
            seen[s] = seen.get(s, 0) + 1
            at = (s, seen[s])
            if at not in got:
                order.insert(order.index(prev) + 1 if prev else 0, at)
                got[at] = []
            got[at].append((a, b))
            prev = at
    out = []
    for at in order:
        ends = got[at]
        if len(ends) == 1:
            text = AB.merge_band(*ends[0])
        else:
            nums = [AB._NUM.findall(t) for pair in ends for t in pair]
            if len({len(n) for n in nums}) != 1:
                raise ValueError(f'variants disagree on the numbers in {ends[0][1]!r}')
            cols = list(zip(*nums))
            lo = iter(min(c, key=float) for c in cols)
            hi = iter(max(c, key=float) for c in cols)
            text = AB.merge_band(AB._NUM.sub(lambda _: next(lo), ends[0][0]),
                                 AB._NUM.sub(lambda _: next(hi), ends[0][1]))
        if len(ends) < len(variants):
            text += f' (on {len(ends)} of {len(variants)} variants)'
        out.append([text, GB._verdict_key(ix, at[0][0])])
    return out


# ---- relic completion bonuses -----------------------------------------------------

class Pools:
    """Completion bonus pools, each shipped once: [[lines] per member]."""

    def __init__(self, ca):
        self.ca, self.rows, self.ix = ca, [], {}

    def of(self, item_id):
        """The pool's index for a relic, or None when it has none."""
        rows = self.ca.execute("""SELECT x.pool_path, b.id, b.path FROM item_bonus x
                                  JOIN bonus b ON b.id = x.bonus_id
                                  WHERE x.item_id = ? AND x.relation = 'completion'
                                  ORDER BY b.path""", (item_id,)).fetchall()
        if not rows:
            return None
        pool = rows[0]['pool_path']
        if pool not in self.ix:
            self.ix[pool] = len(self.rows)
            self.rows.append([self._lines(r['id'], r['path']) for r in rows])
        return self.ix[pool]

    def _lines(self, bonus_id, path):
        stats = {f: (v, lo, hi, txt) for f, v, lo, hi, txt in self.ca.execute(
            'SELECT field, value, lo, hi, txt FROM bonus_stat WHERE bonus_id = ? AND idx = 0',
            (bonus_id,))}
        return [text for _, text, _, _ in AB.display(I.read_rel(path) or '', stats, None, {})]


# ---- the bundle ---------------------------------------------------------------------

def card(ca, ix, icons, pools, bps, tiers, rows):
    top_lv = max(r['lv'] for r in rows)
    top = [r for r in rows if r['lv'] == top_lv]
    faces = [banded(ca, r) for r in top]
    base = SB.rec(top[0]['path'])
    name, rarity, _style, _base_name, badge = SB.item_display(base, top[0]['path'])
    lvs = sorted({r['lv'] for r in rows})
    ids = [r['id'] for r in rows]
    out = {
        'n': name, 'r': rarity, 'b': badge, 't': kind(top[0]),
        'sl': 'Relic' if top[0]['class'] == RELIC else AB.CLASS_TO_LABEL[top[0]['class']],
        'lv': lvs[0] if len(lvs) == 1 else [lvs[0], lvs[-1]],
        'i': icons.want(SB.item_icon(base)),
        'l': merge_variants(ix, [lines for lines, _ in faces]),
        **SR.sources(ca, ids, tiers), 'bp': bps.of(ids),
    }
    grades = [GB.grading(ix, {'base': d}, roll, shown) for _, (d, roll, shown) in faces]
    if len(grades) == 1:
        out['g'] = grades[0]
    else:
        out['gv'] = grades                # the page grades a card by its best variant
    if len(top) > 1:
        out['nv'] = len(top)
    set_path = (base.get('itemSetName') or [None])[0]
    if set_path:
        out['set'] = ix.set(set_path)
    if top[0]['class'] == RELIC:
        pool = pools.of(top[0]['id'])
        if pool is not None:
            out['cb'] = pool
    return out


def account(out_dir=None, gs=None):
    """account.json: per card, how many are held and where; and which blueprints
    each core has unlocked. What a Refresh moves; the cards themselves do not."""
    out_dir = out_dir or OUT
    os.makedirs(out_dir, exist_ok=True)
    cfg = S.load()
    ca = sqlite3.connect(os.path.join(S.ROOT, 'cache', 'catalogue.sqlite'))
    ca.row_factory = sqlite3.Row
    gs = gs or groups(ca)
    have = SR.held(cfg)
    own = {}
    for i, rows in enumerate(gs):
        n = {}
        for r in rows:
            for where, c in have.get(r['path'].lower(), {}).items():
                n[where] = n.get(where, 0) + c
        if n:
            own[i] = sorted(n.items())
    bps = SR.Blueprints(ca, SR.standings())
    for rows in gs:
        bps.of([r['id'] for r in rows])     # the same indexes the cards were given
    data = {'own': own, 'unlocked': bps.unlocked(SR.unlocked())}
    p = os.path.join(out_dir, 'account.json')
    with open(p, 'w') as fh:
        json.dump(data, fh, separators=(',', ':'))
    print(f'{len(own)} cards held -> {p}')


def main(out_dir=None, reuse=False):
    """Build gearcat.json and account.json. `reuse` keeps gearcat.json when it was
    built from the same inputs (the Refresh server's startup); gates never pass it."""
    out_dir = out_dir or OUT
    os.makedirs(out_dir, exist_ok=True)
    cfg = S.load()
    ca = sqlite3.connect(os.path.join(S.ROOT, 'cache', 'catalogue.sqlite'))
    ca.row_factory = sqlite3.Row
    gs = groups(ca)
    p = os.path.join(out_dir, 'gearcat.json')
    stamp_path = p + '.inputs'
    now = AB.inputs(catalogue.connect(cfg.catalogue_db, create=False), cfg)
    if reuse and os.path.isfile(p) and os.path.isfile(stamp_path):
        with open(stamp_path) as fh:
            if fh.read() == now:
                print(f'gearcat.json built from the same inputs, reused -> {p}')
                return account(out_dir, gs)
    # Removed BEFORE the bundle is rewritten, so a write that dies halfway leaves
    # no stamp vouching for it.
    if os.path.exists(stamp_path):
        os.remove(stamp_path)

    icons = SB.Icons(Textures('Items.arc'), Textures('UI.arc'))
    ix = GB.Index()
    tiers = SR.standings()
    SR.check_standings(ca, tiers)
    pools, bps = Pools(ca), SR.Blueprints(ca, tiers)
    items = [card(ca, ix, icons, pools, bps, tiers, rows) for rows in gs]
    sheet, frames = icons.pack()
    bundle = {
        'items': items, 'bps': bps.table(), 'pools': pools.rows, **ix.tables(),
        'factions': {f: n for f, n in ca.execute('SELECT id, name FROM faction')},
        'standings': tiers,
        'coarse': AB.COARSE_SLOT, 'slotGroups': AB.shipped_slot_groups(),
        'frames': frames, 'sheetSize': list(sheet.size),
        'atlas': SB.png_b64(sheet, quantize=255),
    }
    with open(p, 'w') as fh:
        json.dump(bundle, fh, separators=(',', ':'))
    with open(stamp_path, 'w') as fh:
        fh.write(now)
    kinds = {t: sum(1 for c in items if c['t'] == t) for t in ('MI', 'Epic', 'Legendary', 'Relic')}
    print(f"{len(items)} cards ({', '.join(f'{n} {t}' for t, n in kinds.items())}), "
          f"{sum(1 for c in items if 'nv' in c)} folding variants, "
          f"{sum(1 for c in items for l in c['l'] if UNBANDED in l[0])} unbanded lines, "
          f"{len(pools.rows)} completion pools, {len(frames)} icons, "
          f"{os.path.getsize(p) / 1e6:.2f} MB -> {p}")
    account(out_dir, gs)


if __name__ == '__main__':
    sys.exit(main())
