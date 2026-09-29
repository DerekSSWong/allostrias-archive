#!/usr/bin/env python3
"""The Gear Stash bundle: every piece of equipment held in the transfer stash and
in Item Assistant's collection, with its stats AS ROLLED.

  stash.sqlite, stash_iagd.sqlite   what is held -- record paths and the seed
  catalogue.sqlite                  classes, affix names
  archive/seedroll.py               the seed -> the value each stat rolled
  item_lines.py                     the rolled values -> the lines the game prints

The user's rules (2026-09-28): the component and the augment are LEFT OFF -- the
card is the item, not what was socketed into it. The crafting bonus is part of a
crafted item: it rolls with it (seedroll.MODIFIER_KINDS) and its value is merged
into the item's lines, as the game prints it. A relic's is not applied by the game
and is left off like a component.

Epic and Legendary copies of one base record are then folded into one card, each
number at the range it rolled across them (merge(), the user's rule of 2026-09-29).

An item seedroll refuses is shown with its stats withheld and the reason, never
with its unrolled record values: a desynced roll and a record centre both look
like real numbers.

Grading is the page's, by the Affixes scorer (affixes.js) over this bundle's own
field index; each item ships what the scorer reads -- its line count, the fields
the sheet reads, and its skill grants -- and nothing is graded here.
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
from ..archive import seedroll
from ..archive.textures import Textures
from ..sheet import build as SB

OUT = os.path.join(S.ROOT, 'cache', 'gearstash')

# Text fields line_rows() reads; every other text field on a record is not a
# line and is not handed to it.
_TEXT_OWNED = AB.TEXT_OWNED


def _stats_of(values, record):
    """{field: (v, v, v, txt)} in the shape affixes.build.line_rows reads: the
    numeric fields at `values`, the text-owned fields off the record, and the
    +skill levels (which do not roll) off the record too."""
    out = {f: (v, v, v, None) for f, v in values.items()}
    for f, vs in (record or {}).items():
        v = vs[0] if vs else ''
        if _TEXT_OWNED.match(f) and v:
            out[f] = (None, None, None, v)
        elif f.startswith(('augmentSkillLevel', 'racialBonusPercent')) and v:
            out[f] = (float(v),) * 3 + (None,)
        elif f.startswith('conversionPercentage') and v and f not in out:
            # seedroll credits a conversion's parts to the FIRST pair only; a
            # second pair's source still carries a line, which is all the
            # grading reads (it counts lines, not how high they rolled).
            out[f] = (float(v),) * 3 + (None,)
    return out


def _pet_stats(record):
    """The pet bonus a record grants via petBonusName, at level 0, as the
    Affixes corpus reads it."""
    path = ((record or {}).get('petBonusName') or [None])[0]
    if not path:
        return {}
    txt = I.apply_skill_level(I.read_rel(path) or '', 0)
    out = {}
    for line in txt.splitlines():
        f, _, v = line.partition('=')
        try:
            out[f] = (float(v),) * 3 + (None,)
        except ValueError:
            pass
    return out


class Index:
    """The interned tables the page reads: for the scorer, fields the sheet reads,
    their line keys and sheet rows, and granted skills; and each set's block,
    once however many of its pieces are held."""

    def __init__(self):
        self.fr = AB.field_to_rows(SB.SHEET)
        self.fields, self.skills, self.sets = [], [], []
        self._f, self._k, self._s = {}, {}, {}

    def field(self, key):
        if key not in self._f:
            self._f[key] = len(self.fields)
            self.fields.append(key)
        return self._f[key]

    def skill(self, key):
        if key not in self._k:
            self._k[key] = len(self.skills)
            self.skills.append(key)
        return self._k[key]

    def set(self, path):
        """The set at `path` as the card prints it: name, pieces for the full set,
        members, tiers and what follows them (item_lines.set_block)."""
        if path not in self._s:
            srec = SB.rec(path) or {}
            tiers, after = item_lines.set_block(srec)
            self._s[path] = len(self.sets)
            self.sets.append({
                'n': SB.tag((srec.get('setName') or [None])[0]) or 'Set',
                'total': item_lines.set_size(srec),
                'members': [SB.item_display(SB.rec(m) or {}, m)[0]
                            for m in srec.get('setMembers') or [] if m],
                'tiers': tiers, 'after': after})
        return self._s[path]

    def tables(self):
        return {'f': self.fields, 'lk': [AB.line_key(f) for f in self.fields],
                'fr': [self.fr[f] for f in self.fields], 'k': self.skills, 'sets': self.sets}


def grant_key(key):
    """What a `skill:`/`mastery:` line from item_lines is graded as: a skill by
    its record path (the sheet's skill window lists records), a mastery by its
    NAME (the sheet lists masteries by name, not by record)."""
    kind, _, path = key.partition(':')
    if kind == 'skill':
        return path
    txt = I.read_rel(path) or ''
    enum = next((l.split('=', 1)[1] for l in txt.splitlines()
                 if l.startswith('MasteryEnumeration=')), None)
    name = I.MASTERY_NAMES.get(enum)
    if not name:
        raise ValueError(f'{path} names no mastery')
    return 'mastery:' + name


def grading(ix, recs, roll, shown):
    """[lines, scored, grants] -- the three things affixes.js's score() reads,
    in its record positions 5, 6 and 7."""
    rows = []
    for which, d in recs.items():
        vals = {f: per[which] for f, per in roll.parts.items() if which in per}
        rows += AB.line_rows(_stats_of(vals, d), _pet_stats(d))
    scored, seen = [], set()
    for r in rows:
        k = AB.row_key(r)
        if k in ix.fr and r['lo'] is not None and AB.is_stat(r['field']) and k not in seen:
            seen.add(k)
            scored.append([ix.field(k), r['lo'], r['hi']])
    grants = []
    for key, _ in shown:
        if key and key.startswith(('skill:', 'mastery:')):
            ki = ix.skill(grant_key(key))
            if all(g[0] != ki for g in grants):
                grants.append([ki, f'k{ki}', 0, 0])
    # A mastery grant is a line line_rows() does not know; count it here.
    extra = sum(1 for key, _ in shown if key and key.startswith('mastery:'))
    return [AB.line_count(rows) + extra, scored, grants]


def held(st_db, iagd_db):
    """(source, where, row) for every item held, transfer stash first."""
    st = sqlite3.connect(st_db)
    st.row_factory = sqlite3.Row
    for r in st.execute('SELECT s.*, p.mode, p.idx FROM stash_item s '
                        'JOIN stash_page p ON p.id = s.page_id ORDER BY p.mode, p.idx, s.y, s.x'):
        where = f"Tab {r['idx'] + 1}" + ('' if r['mode'] == 'gst' else f" ({r['mode']})")
        yield 'Transfer', where, r
    if iagd_db and os.path.exists(iagd_db):
        ia = sqlite3.connect(iagd_db)
        ia.row_factory = sqlite3.Row
        for r in ia.execute('SELECT * FROM iagd_item ORDER BY id'):
            tags = [t for t, on in (('Hardcore', r['is_hardcore']), (r['mod'], r['mod'])) if on]
            yield 'IAGD', ' · '.join(tags), r


def _roll(ca, r):
    """(class row, recs, paths, roll) for one held row: the records it rolls
    from -- a crafting bonus among them, a relic's excepted -- and the roll."""
    cls = ca.execute('SELECT class, is_equipment FROM item WHERE path = ?',
                     (r['base_path'],)).fetchone()
    if cls is None:
        raise SystemExit(f"{r['base_path']} is in no catalogue record: rebuild the catalogue")
    recs = {'base': SB.rec(r['base_path'])}
    paths = {'base': r['base_path']}
    for which in ('prefix', 'suffix'):
        if r[f'{which}_path']:
            recs[which] = SB.rec(r[f'{which}_path'])
            paths[which] = r[f'{which}_path']
    if r['modifier_path'] and cls['class'] != 'ItemRelic':
        recs['modifier'] = SB.rec(r['modifier_path'])
    roll = seedroll.compute(recs['base'], r['seed'], recs.get('prefix'), recs.get('suffix'),
                            modifier=recs.get('modifier'))
    return cls, recs, paths, roll


def _face(ix, recs, paths, roll):
    """[l, g]: a rolled item's lines with their verdict keys, and its grading."""
    shown = item_lines.rolled(paths['base'], paths, roll)
    return [[text, _verdict_key(ix, key)] for key, text in shown], grading(ix, recs, roll, shown)


def card(ca, ix, icons, source, where, r):
    """One item's card, or None when it is not equipment."""
    cls, recs, paths, roll = _roll(ca, r)
    if not cls['is_equipment']:
        return None
    base = recs['base']
    pfx = SB.affix_of(ca, r['prefix_path'], 'prefix')
    sfx = SB.affix_of(ca, r['suffix_path'], 'suffix')
    name, rarity, _style, _base_name, badge = SB.item_display(base, r['base_path'], pfx, sfx)
    out = {
        'n': name, 'r': rarity, 'b': badge,
        'sl': AB.CLASS_TO_LABEL.get(cls['class'], cls['class']),
        'lv': int(float((base.get('levelRequirement') or [0])[0])),
        'x': [[source, where]], 'i': icons.want(SB.item_icon(base)),
    }
    set_path = (base.get('itemSetName') or [None])[0]
    if set_path:
        out['set'] = ix.set(set_path)
    if roll.unmodeled:
        out['why'] = 'not replayed: ' + ', '.join(roll.unmodeled)
        return out
    out['l'], out['g'] = _face(ix, recs, paths, roll)
    return out


# ---- duplicates ---------------------------------------------------------------
# The user's rule (2026-09-29): Epic and Legendary copies of one item are ONE card,
# each stat at the range it rolled across them. "One item" is one base record: a
# Mythical and an Empowered share a name but not a record (see item.style_tag).
# A crafting bonus of the same stat on every copy merges like any stat; otherwise
# the bonus is taken out of every copy and the card says so instead.
MERGED = ('Epic', 'Legendary')

_NUM = re.compile(r'\d+(?:\.\d+)?')


def shape(text):
    """A line with its numbers taken out, and a unit's plural with them: "for 1
    Second" and "for 2 Seconds" are one line."""
    return re.sub(r'(#\s+\w+?)s\b', r'\1', _NUM.sub('#', text))


def merge_lines(copies):
    """[[text, key]] for several copies' lines: each line once, every number that
    differs as "[lo–hi]". A line not every copy carries says on how many."""
    order, texts = [], {}
    for lines in copies:
        seen, prev = {}, None
        for text, key in lines:
            s = (key, shape(text))
            seen[s] = seen.get(s, 0) + 1
            at = (s, seen[s])
            if at not in texts:
                order.insert(order.index(prev) + 1 if prev else 0, at)
                texts[at] = []
            texts[at].append(text)
            prev = at
    out = []
    for at in order:
        ts = texts[at]
        cols = list(zip(*(_NUM.findall(t) for t in ts)))
        spans = [(min(c, key=float), max(c, key=float)) for c in cols]
        it = iter(spans)
        text = _NUM.sub(lambda _: (lambda lo, hi: lo if float(lo) == float(hi)
                                   else f'[{lo}–{hi}]')(*next(it)),
                        max(ts, key=len))            # the plural, where one differs
        if len(ts) < len(copies):
            text += f' (on {len(ts)} of {len(copies)} copies)'
        out.append([text, at[0][0]])
    return out


def merge_grading(name, gs):
    """One grading for the copies. The scorer reads which lines an item carries,
    never how high they rolled, so the copies must agree on all but the values;
    each value becomes the span it rolled across them."""
    if len({json.dumps([g[0], [s[0] for s in g[1]], g[2]]) for g in gs}) != 1:
        raise ValueError(f'{name}: copies carry different graded lines')
    scored = [[f, min(g[1][i][1] for g in gs), max(g[1][i][2] for g in gs)]
              for i, (f, _, _) in enumerate(gs[0][1])]
    return [gs[0][0], scored, gs[0][2]]


def without_bonus(roll):
    """The roll with the crafting bonus's draws taken back out. The bonus still
    moved every draw after it, so this is NOT the roll of the item uncrafted."""
    parts = {f: {w: v for w, v in per.items() if w != 'modifier'} for f, per in roll.parts.items()}
    stats = dict(roll.stats)
    for f, per in roll.parts.items():
        if 'modifier' in per:
            if parts[f]:
                stats[f] = sum(parts[f].values())
            else:
                del stats[f]
    return seedroll.Roll(stats, {f: p for f, p in parts.items() if p},
                         roll.unmodeled, roll.proc_lines, roll.conversions)


def bonus_kind(roll):
    """The stats a crafting bonus rolled on this copy, or None."""
    return tuple(sorted(f for f, per in roll.parts.items() if 'modifier' in per)) or None


def merge(ca, ix, held_cards):
    """The cards the page shows, from (row, card) per held item: Epic and
    Legendary copies of one base record folded into one card. A refused copy
    stays its own card: it has no numbers to fold."""
    groups, order = {}, []
    for r, c in held_cards:
        key = r['base_path'] if c['r'] in MERGED and 'why' not in c else id(c)
        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].append((r, c))
    out = []
    for key in order:
        members = groups[key]
        if len(members) == 1:
            out.append(members[0][1])
            continue
        rolls = [_roll(ca, r) for r, _ in members]
        kinds = [bonus_kind(roll) for _, _, _, roll in rolls]
        merged = dict(members[0][1], x=[c['x'][0] for _, c in members])
        if len(set(kinds)) == 1:
            faces = [(c['l'], c['g']) for _, c in members]
        else:
            faces = [_face(ix, {k: v for k, v in recs.items() if k != 'modifier'}, paths,
                           without_bonus(roll)) for _, recs, paths, roll in rolls]
        merged['l'] = merge_lines([l for l, _ in faces])
        merged['g'] = merge_grading(merged['n'], [g for _, g in faces])
        if len(set(kinds)) > 1:
            n_kinds = len({k for k in kinds if k})
            crafted = sum(1 for k in kinds if k)
            note = 'crafting bonus' if n_kinds == 1 else f'{n_kinds} different crafting bonuses'
            if crafted < len(members):
                note += f' on {crafted} of {len(members)} copies'
            merged['l'].append([f'({note})', 0])
        out.append(merged)
    return out


def _verdict_key(ix, key):
    """The key the scorer's match() reports this line's verdict under, or 0: a
    stat line by its line key ('f' + line key), a grant by its skill slot."""
    if not key or key == 'granted':
        return 0
    if key.startswith(('skill:', 'mastery:')):
        return f'sk{ix.skill(grant_key(key))}'
    if key.startswith('conversion'):
        return 'f' + key
    return 'f' + AB.line_key(key)


def main(out_dir=None):
    out_dir = out_dir or OUT
    os.makedirs(out_dir, exist_ok=True)
    cfg = S.load()
    ca = sqlite3.connect(os.path.join(S.ROOT, 'cache', 'catalogue.sqlite'))
    ca.row_factory = sqlite3.Row
    icons = SB.Icons(Textures('Items.arc'), Textures('UI.arc'))
    ix = Index()
    each, skipped = [], 0
    iagd_db = os.path.join(S.ROOT, 'cache', 'stash_iagd.sqlite') if cfg.iagd else None
    for source, where, r in held(os.path.join(S.ROOT, 'cache', 'stash.sqlite'), iagd_db):
        c = card(ca, ix, icons, source, where, r)
        if c is None:
            skipped += 1
        else:
            each.append((r, c))
    items = merge(ca, ix, each)
    sheet, frames = icons.pack()
    bundle = {
        'items': items, **ix.tables(),
        'coarse': AB.COARSE_SLOT, 'slotGroups': AB.shipped_slot_groups(),
        'iagd': bool(cfg.iagd),
        'frames': frames, 'sheetSize': list(sheet.size),
        'atlas': SB.png_b64(sheet, quantize=255),
    }
    p = os.path.join(out_dir, 'gearstash.json')
    with open(p, 'w') as fh:
        json.dump(bundle, fh, separators=(',', ':'))
    refused = sum(1 for c in items if 'why' in c)
    held_n = [x[0] for c in items for x in c['x']]
    print(f"{len(items)} cards for {len(held_n)} items ({held_n.count('Transfer')} transfer, "
          f"{held_n.count('IAGD')} IAGD), {skipped} not equipment, "
          f"{refused} not replayed, {len(frames)} icons, "
          f"{os.path.getsize(p) / 1e6:.2f} MB -> {p}")


if __name__ == '__main__':
    sys.exit(main())
