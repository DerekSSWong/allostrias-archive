#!/usr/bin/env python3
"""The Gear Stash bundle: every piece of equipment held in the transfer stash and
in Item Assistant's collection, with its stats AS ROLLED.

  stash.sqlite, stash_iagd.sqlite   what is held -- record paths and the seed
  catalogue.sqlite                  classes, affix names
  archive/seedroll.py               the seed -> the value each stat rolled
  item_lines.py                     the rolled values -> the lines the game prints

The user's rules (2026-09-28): the component and the augment are LEFT OFF -- the
card is the item, not what was socketed into it. The crafting bonus is part of a
crafted item and is shown, as its own block, at its record value: whether it
jitters is NOT verified, and the block says so.

An item seedroll refuses is shown with its stats withheld and the reason, never
with its unrolled record values: a desynced roll and a record centre both look
like real numbers.

Grading is the page's, by the Affixes scorer (affixes.js) over this bundle's own
field index; each item ships what the scorer reads -- its line count, the fields
the sheet reads, and its skill grants -- and nothing is graded here.
"""
import json
import os
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
    """The interned tables the page's scorer reads: fields the sheet reads, their
    line keys and sheet rows, and granted skills."""

    def __init__(self):
        self.fr = AB.field_to_rows(SB.SHEET)
        self.fields, self.skills = [], []
        self._f, self._k = {}, {}

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

    def tables(self):
        return {'f': self.fields, 'lk': [AB.line_key(f) for f in self.fields],
                'fr': [self.fr[f] for f in self.fields], 'k': self.skills}


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


def grading(ix, recs, roll, modifier, shown):
    """[lines, scored, grants] -- the three things affixes.js's score() reads,
    in its record positions 5, 6 and 7."""
    rows = []
    for which, d in recs.items():
        vals = {f: per[which] for f, per in roll.parts.items() if which in per}
        rows += AB.line_rows(_stats_of(vals, d), _pet_stats(d))
    if modifier:
        mvals = {f: float(v[0]) for f, v in modifier.items()
                 if v and not _TEXT_OWNED.match(f) and SB._num(v[0])}
        rows += AB.line_rows(_stats_of(mvals, modifier), _pet_stats(modifier))
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


def card(ca, ix, icons, source, where, r):
    """One item's card, or None when it is not equipment."""
    cls = ca.execute('SELECT class, is_equipment FROM item WHERE path = ?',
                     (r['base_path'],)).fetchone()
    if cls is None:
        raise SystemExit(f"{r['base_path']} is in no catalogue record: rebuild the catalogue")
    if not cls['is_equipment']:
        return None
    base = SB.rec(r['base_path'])
    recs = {'base': base}
    paths = {'base': r['base_path']}
    for which in ('prefix', 'suffix'):
        if r[f'{which}_path']:
            recs[which] = SB.rec(r[f'{which}_path'])
            paths[which] = r[f'{which}_path']
    pfx = SB.affix_of(ca, r['prefix_path'], 'prefix')
    sfx = SB.affix_of(ca, r['suffix_path'], 'suffix')
    name, rarity, _style, _base_name, badge = SB.item_display(base, r['base_path'], pfx, sfx)
    roll = seedroll.compute(base, r['seed'], recs.get('prefix'), recs.get('suffix'))

    out = {
        'n': name, 'r': rarity, 'b': badge,
        'sl': AB.CLASS_TO_LABEL.get(cls['class'], cls['class']),
        'lv': int(float((base.get('levelRequirement') or [0])[0])),
        'src': source, 'at': where, 'i': icons.want(SB.item_icon(base)),
    }
    set_path = (base.get('itemSetName') or [None])[0]
    if set_path:
        out['set'] = SB.tag(((SB.rec(set_path) or {}).get('setName') or [None])[0])
    modifier = SB.rec(r['modifier_path']) if r['modifier_path'] else None
    if modifier:
        out['cb'] = I.effects_of(I.read_rel(r['modifier_path']) or '')
    if roll.unmodeled:
        out['why'] = 'not replayed: ' + ', '.join(roll.unmodeled)
        return out
    shown = item_lines.rolled(r['base_path'], paths, roll)
    out['l'] = [[text, _verdict_key(ix, key)] for key, text in shown]
    out['g'] = grading(ix, recs, roll, modifier, shown)
    return out


def _verdict_key(ix, key):
    """The key the scorer's match() reports this line's verdict under, or 0: a
    stat line by its line key ('f' + line key), a grant by its skill slot."""
    if not key:
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
    items, skipped = [], 0
    iagd_db = os.path.join(S.ROOT, 'cache', 'stash_iagd.sqlite') if cfg.iagd else None
    for source, where, r in held(os.path.join(S.ROOT, 'cache', 'stash.sqlite'), iagd_db):
        c = card(ca, ix, icons, source, where, r)
        if c is None:
            skipped += 1
        else:
            items.append(c)
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
    print(f"{len(items)} items ({sum(c['src'] == 'Transfer' for c in items)} transfer, "
          f"{sum(c['src'] == 'IAGD' for c in items)} IAGD), {skipped} not equipment, "
          f"{refused} not replayed, {len(frames)} icons, "
          f"{os.path.getsize(p) / 1e6:.2f} MB -> {p}")


if __name__ == '__main__':
    sys.exit(main())
