#!/usr/bin/env python3
"""catalogue.sqlite -> the affix corpus the sheet's Affixes view grades.

    python3 -m allostrias.affixes.build

PORTED FROM GD Lens's affixes.py (and the line table gd-lib writes for it), not
imported: GD Lens and gd-lib are test oracles here, never build inputs. What is
ported is the MODEL -- what a line is, how many an affix carries, which sheet
row reads which field. The DATA is this repo's own: every record, band and slot
comes out of catalogue.sqlite.

WHAT SHIPS, per affix record that can drop (it has affix_eligibility rows) and
has a display name:
  - the fields some sheet row reads, with their roll band -- what gets SCORED;
  - the "+N to <skill>" grants, keyed by the skill's record path;
  - how many LINES the record carries in all, readable or not -- the
    denominator, so padding the sheet cannot use still costs;
  - its slot family, and every line it shows in the game's own wording with the
    band it rolls between -- what gets DISPLAYED and searched.

Grading is the page's: it depends on the character's verdicts, which move on
every click. Nothing here knows a character.

⚠️ THE ROWS ARE THIS SHEET'S, NOT GD Lens's. Fields are joined to the archive's
own SHEET table, which differs from GD Lens's (Life Steal, Damage Absorption,
no Damage Blocked modifier). So a grade here can legitimately differ from GD
Lens's for the same character; the corpus -- records, lines, bands, slots -- is
what the oracle gate holds equal.
"""
import collections
import json
import os
import re
import sys

from .. import settings as S
from .. import item_stats as I
from ..db import catalogue
from ..sheet import build as SB

OUT = os.path.join(S.ROOT, 'cache', 'affixes')

# ------------------------------------------------------------------ slots --
# The 23 equipment classes an affix can roll onto, by the label gd-lib's affix
# catalogue gives each. tests/test_eligibility.py holds this total against the
# item table in both directions.
CLASS_TO_LABEL = {
    'ArmorJewelry_Amulet': 'Amulet',
    'ArmorJewelry_Medal': 'Medal',
    'ArmorJewelry_Ring': 'Ring',
    'ArmorProtective_Chest': 'Chest',
    'ArmorProtective_Feet': 'Boots',
    'ArmorProtective_Hands': 'Gloves',
    'ArmorProtective_Head': 'Helm',
    'ArmorProtective_Legs': 'Legs',
    'ArmorProtective_Shoulders': 'Shoulders',
    'ArmorProtective_Waist': 'Belt',
    'WeaponArmor_Offhand': 'Off-Hand (Focus)',
    'WeaponArmor_Shield': 'Shield',
    'WeaponHunting_Ranged1h': 'Ranged',
    'WeaponHunting_Ranged2h': 'Ranged (2H)',
    'WeaponMelee_Axe': 'Axe',
    'WeaponMelee_Axe2h': 'Axe (2H)',
    'WeaponMelee_Dagger': 'Dagger',
    'WeaponMelee_Mace': 'Mace',
    'WeaponMelee_Mace2h': 'Mace (2H)',
    'WeaponMelee_Scepter': 'Scepter',
    'WeaponMelee_Spear2h': 'Spear (2H)',
    'WeaponMelee_Sword': 'Sword',
    'WeaponMelee_Sword2h': 'Sword (2H)',
}

# Copied from gd-lib's affix_corpus.py; tests/test_affix_corpus.py diffs them.
# The coarse buckets are for MATCHING only -- a card prints the slots the
# records name, never "1H Weapon".
#
# ⚠️ Spear (2H) is absent from COARSE_SLOT, as it is in gd-lib: every spear
# affix also rolls on another 2H type today. The corpus gate fails if a
# spear-only affix appears, which is when that would start to matter.
COARSE_SLOT = {
    'Ranged (2H)': '2H Weapon', 'Axe (2H)': '2H Weapon', 'Mace (2H)': '2H Weapon',
    'Sword (2H)': '2H Weapon', 'Axe': '1H Weapon', 'Dagger': '1H Weapon',
    'Mace': '1H Weapon', 'Scepter': '1H Weapon', 'Sword': '1H Weapon',
}
SLOT_ORDER = ['Axe', 'Sword', 'Dagger', 'Mace', 'Scepter', 'Ranged',
              'Axe (2H)', 'Mace (2H)', 'Sword (2H)', 'Spear (2H)', 'Ranged (2H)',
              '1H Weapon', '2H Weapon', 'Shield', 'Off-Hand (Focus)',
              'Helm', 'Shoulders', 'Chest', 'Gloves', 'Belt', 'Legs', 'Boots',
              'Ring', 'Amulet', 'Medal']
SLOT_GROUPS = [
    dict(label='Hand', values=[
        'Axe', 'Sword', 'Dagger', 'Mace', 'Scepter', 'Ranged',
        'Axe (2H)', 'Mace (2H)', 'Sword (2H)', 'Spear (2H)', 'Ranged (2H)',
        '1H Weapon', '2H Weapon', 'Shield', 'Off-Hand (Focus)']),
    [
        dict(label='Armor', values=[
            'Helm', 'Shoulders', 'Chest', 'Gloves', 'Belt', 'Legs', 'Boots']),
        dict(label='Jewelry', values=['Ring', 'Amulet', 'Medal']),
    ],
]

# ------------------------------------------------------ what a stat is ----
# PORTED FROM GD Lens's stat_engine.SKIP_EXACT / SKIP_PREFIX: numeric fields
# that are not a stat -- identifiers, art, costs, loot machinery. A line the
# denominator counts must be a line; counting these would charge an affix for
# its own bookkeeping.
SKIP_EXACT = {
    'itemLevel', 'levelRequirement', 'itemCost', 'itemCostScalePercent',
    'lootRandomizerCost', 'lootRandomizerJitter', 'marketAdjustmentPercent',
    'bardTier', 'itemSkillLevelEq', 'skillTier', 'skillMaxLevel',
    'skillConnectionOff', 'skillExperienceLevels', 'devotionButtonLocation',
    'skillUltimateLevel', 'skillCooldownTime', 'skillActiveDuration',
    'skillManaCost', 'skillProjectileNumber', 'skillTargetNumber',
    'skillTargetRadius', 'skillTargetAngle', 'skillWeaponDamagePct',
    'racialBonusPercentDamage', 'racialBonusAbsoluteDefense',
    'attributeScalePercent',
    'maxTransparency', 'outlineThickness', 'physicsFriction', 'physicsMass',
    'physicsRestitution', 'scale', 'castsShadows', 'cameraShakeAmplitude',
    'completedRelicLevel', 'craftingMaterial', 'exclusiveSkill', 'medalVisible',
    'isPetBonusScaling', 'debufSkill',
    'head', 'shoulders', 'chest', 'hands', 'waist', 'legs', 'feet',
    'ring', 'amulet', 'medal', 'offhand', 'shield',
    'axe', 'dagger', 'mace', 'scepter', 'sword', 'ranged1h',
    'axe2h', 'mace2h', 'sword2h', 'spear2h', 'ranged2h',
}
SKIP_PREFIX = ('bitmap', 'Class', 'template', 'File', 'Actor', 'skillDisplay',
               'skillBase', 'skillUp', 'skillDown', 'buffSkill', 'petSkill',
               'artifact', 'reagent', 'loot', 'market', 'mesh', 'fx', 'sound',
               'skillConnection', 'devotion')
_SKIP_PREFIX_LOW = tuple(p.lower() for p in SKIP_PREFIX)


def is_stat(field):
    if field in SKIP_EXACT:
        return False
    low = field[0].lower() + field[1:]
    return not low.startswith(_SKIP_PREFIX_LOW)


_MINMAX = re.compile(r'(Duration)?(Min|Max)$')


def line_key(field):
    """The LINE a field belongs to. Ported from GD Lens's line_key(), over the
    line table's field names (`skill1`, `itemSkill`, `conversion`, ...).

    A line is not a field: a Min with its Max, a DoT with its Duration and a
    proc with its Chance are one line each. A `Modifier` is NOT folded in --
    "+20% Bleeding Damage" is its own line beside the flat bleed. Pet fields
    collapse by the same rules, but only against each other."""
    if field.startswith('pet:'):
        return 'pet:' + line_key(field[4:])
    return re.sub(r'Chance$', '', _MINMAX.sub('', field)) or field


# -------------------------------------------------------- one record's lines
# The line-table shape gd-lib's affix_lines.csv uses, rebuilt from SQL. Several
# fields spell one line, and those lines are named for the line rather than for
# whichever field happened to be numeric:
#
#   conversionInType/OutType/Percentage -> conversion
#   augmentSkillName{i}/Level{i}        -> skill{i}   (source = the skill record)
#   itemSkillName/AutoController        -> itemSkill  (no magnitude)
#   racialBonusRace/PercentDamage       -> racialBonusRace
#
# Everything else numeric is its own row, pet stats in their own bucket.
NON_STAT_FIELDS = {'itemSkillLevelEq', 'bitmapName'}
OWNED = re.compile(r'^(conversionPercentage\d*|augmentSkillLevel\d'
                   r'|racialBonus(?:Percent|Absolute)(?:Damage|Defense))$')
TEXT_OWNED = re.compile(r'^(conversion(?:In|Out)Type\d*|augmentSkillName\d'
                        r'|itemSkill(?:Name|AutoController)|racialBonusRace'
                        r'|petBonusName)$')


def line_rows(stats, pet_stats):
    """[{bucket, field, value, lo, hi, source}] for one record.

    `stats` / `pet_stats` are {field: (value, lo, hi, txt)} at idx 0. Raises on
    a text field it does not know how to read, rather than dropping it: a line
    nobody claims is a line the denominator silently forgets."""
    rows = []
    for f, (v, lo, hi, txt) in sorted(stats.items()):
        if f in NON_STAT_FIELDS:
            continue
        if txt is not None:
            if not TEXT_OWNED.match(f):
                raise ValueError(f'unclaimed text field {f}={txt}')
            continue
        if OWNED.match(f):
            continue
        rows.append(dict(bucket='player', field=f, value=v, lo=lo, hi=hi, source=''))

    for f in stats:
        m = re.match(r'^conversionInType(\d*)$', f)
        if not m:
            continue
        sfx = m.group(1)
        if f'conversionOutType{sfx}' not in stats:
            continue
        v, lo, hi, _ = stats.get(f'conversionPercentage{sfx}', (100.0, None, None, None))
        if lo is None:
            raise ValueError(f'conversion{sfx} has no stored percentage')
        rows.append(dict(bucket='player', field=f'conversion{sfx}', value=v,
                         lo=lo, hi=hi, source=''))

    for i in range(1, 6):
        name = stats.get(f'augmentSkillName{i}')
        lvl = stats.get(f'augmentSkillLevel{i}')
        if not name and not lvl:
            continue
        rows.append(dict(bucket='player', field=f'skill{i}',
                         value=lvl[0] if lvl else None,
                         lo=lvl[1] if lvl else None, hi=lvl[2] if lvl else None,
                         source=name[3] if name else ''))

    if 'itemSkillName' in stats:
        rows.append(dict(bucket='player', field='itemSkill', value=None, lo=None,
                         hi=None, source=stats['itemSkillName'][3]))

    if 'racialBonusRace' in stats:
        v = stats.get('racialBonusPercentDamage')
        rows.append(dict(bucket='player', field='racialBonusRace',
                         value=v[0] if v else None, lo=v[1] if v else None,
                         hi=v[2] if v else None, source=''))

    src = stats.get('petBonusName', (None, None, None, ''))[3]
    for f, (v, lo, hi, txt) in sorted(pet_stats.items()):
        if txt is not None or f in NON_STAT_FIELDS:
            continue
        rows.append(dict(bucket='pet', field=f, value=v, lo=lo, hi=hi, source=src))
    return rows


def row_key(r):
    """A row's field as the scorer sees it: pet fields namespaced."""
    return ('pet:' if r['bucket'] == 'pet' else '') + r['field']


def line_count(rows):
    """Every LINE the record carries, readable by the sheet or not."""
    return len({line_key(row_key(r)) for r in rows if is_stat(r['field'])})


# --------------------------------------------------------- the sheet join --
def field_to_rows(sheet):
    """field -> ["Section / Label"] for every sheet row that reads it.

    Derived from the SHEET table rather than written down, so a row added there
    reaches the scorer with no second edit. A row reads its fields and its
    modifier; pet rows read `pet:<field>`."""
    out = collections.defaultdict(list)
    for entry in sheet:
        sec, rows = entry[0], entry[1]
        pre = 'pet:' if len(entry) > 2 and entry[2] == 'pet' else ''
        for r in rows:
            for f in r.get('f', []) + ([r['m']] if r.get('m') else []):
                key = f'{sec} / {r["label"]}'
                if key not in out[pre + f]:
                    out[pre + f].append(key)
    return dict(out)


# ---------------------------------------------------------- the display --
# The sign belongs to the number: a band can cross zero, and '-0.5' / '+1.5'
# is one line whose number moves, not two lines of different shape.
_NUM = re.compile(r'[-+]?\d+(?:\.\d+)?')


def _fmt(v):
    return ('%f' % v).rstrip('0').rstrip('.')


def _with_values(txt, values):
    """The record's text with each named field set to a value."""
    def sub(m):
        f = m.group(1)
        return f'{f}={_fmt(values[f])}' if f in values else m.group(0)
    return re.sub(r'^([A-Za-z0-9]+)=.*$', sub, txt, flags=re.M)


def merge_band(lo_line, hi_line):
    """One line from its lowest and highest roll: '+3% Cunning' and
    '+7% Cunning' -> '+3–7% Cunning'. Where more than one number moves, each
    range is bracketed so '(8–12)–(10–15) Fire dmg' cannot be misread."""
    if lo_line == hi_line:
        return lo_line
    a, b = _NUM.split(lo_line), _NUM.split(hi_line)
    if a != b:
        raise ValueError(f'lines differ in shape: {lo_line!r} / {hi_line!r}')
    na, nb = _NUM.findall(lo_line), _NUM.findall(hi_line)
    moving = sum(x != y for x, y in zip(na, nb))
    out = [a[0]]
    for x, y, rest in zip(na, nb, a[1:]):
        if x == y:
            out.append(x)
        else:
            out.append(f'({x}–{y})' if moving > 1 else f'{x}–{y}')
        out.append(rest)
    return ''.join(out)


def _banded_lines(render, txt, lo, hi):
    """render(txt) at the low and the high end of every band, zipped."""
    a, b = render(_with_values(txt, lo)), render(_with_values(txt, hi))
    if len(a) != len(b):
        raise ValueError(f'{len(a)} lines at the low roll, {len(b)} at the high')
    return [merge_band(x, y) for x, y in zip(a, b)]


def _only(txt, pattern):
    """The record's text reduced to the fields matching `pattern` (plus Class,
    which some builders key off)."""
    keep = re.compile(pattern)
    return '\n'.join(l for l in txt.splitlines()
                     if keep.match(l.partition('=')[0]) or l.startswith('Class=')) + '\n'


def display(txt, stats, pet_txt, pet_stats):
    """[(line key, text, hi, is_pet)] in the order the game prints them.

    Each builder of the ported tooltip renderer is run on its own fields, so
    every line comes back already knowing which line key it is -- which is what
    lets the page merge a unit's level tiers line by line. `hi` is the top of
    the line's roll, the number that picks the best tier."""
    lo = {f: s[1] for f, s in stats.items() if s[1] is not None}
    hi = {f: s[2] for f, s in stats.items() if s[2] is not None}
    out = []

    for f, line in zip(*_fields_and_lines(txt, lo, hi)):
        out.append((line_key(f), line, hi.get(f), False))

    conv = _banded_lines(lambda t: I.extract_conversions(t, ''), txt, lo, hi)
    out += [('conversion', line, hi.get('conversionPercentage'), False) for line in conv]

    for i in range(1, 6):
        if f'augmentSkillName{i}' not in stats:
            continue
        part = _only(txt, rf'^augmentSkill(Name|Level){i}$')
        for line in _banded_lines(I.resolve_augment_skills, part, lo, hi):
            out.append((f'skill{i}', line, hi.get(f'augmentSkillLevel{i}'), False))

    for line in I.resolve_item_skill(txt):
        out.append(('itemSkill', line, None, False))

    if pet_txt is not None:
        plo = {f: s[1] for f, s in pet_stats.items() if s[1] is not None}
        phi = {f: s[2] for f, s in pet_stats.items() if s[2] is not None}
        pet_txt = I.apply_skill_level(pet_txt, 0)
        for f, val in re.findall(r'^([A-Za-z0-9]+)=(-?[\d.]+)', pet_txt, re.M):
            for line in _banded_lines(_pet_line, f'{f}={val}\n', plo, phi):
                out.append(('pet:' + line_key(f), line, phi.get(f), True))
    return out


def _fields_and_lines(txt, lo, hi):
    a = I.process_stats_fields(_with_values(txt, lo))
    b = I.process_stats_fields(_with_values(txt, hi))
    if [f for f, _ in a] != [f for f, _ in b]:
        raise ValueError('stat lines differ between the low and the high roll')
    return [f for f, _ in a], [merge_band(x, y) for (_, x), (_, y) in zip(a, b)]


def _pet_line(txt):
    """resolve_pet_bonus()'s per-field rule, on one field of the pet record."""
    field, _, val = txt.strip().partition('=')
    shared = I.process_stats(txt)
    if shared:
        return [I.PET_PREFIX + l for l in shared]
    if field in I.PET_FIELD_MAP:
        label, is_pct = I.PET_FIELD_MAP[field]
        sign = '' if val.startswith('-') else '+'
        return [f"{I.PET_PREFIX}{sign}{I._fmt_num(val)}{'%' if is_pct else ''} {label}"]
    return []


# ------------------------------------------------------------- assemble --
def load(conn):
    """{path: record dict} for every affix that can drop and has a name."""
    recs = {}
    for r in conn.execute("""
            SELECT a.id, a.path, a.kind, a.name_tag, a.name, a.rarity, a.level_req
            FROM affix a
            WHERE a.kind IN ('Prefix', 'Suffix') AND a.name IS NOT NULL
              AND EXISTS (SELECT 1 FROM affix_eligibility e WHERE e.affix_id=a.id)"""):
        recs[r['id']] = dict(path=r['path'], kind=r['kind'], tag=r['name_tag'],
                             name=r['name'], rarity=r['rarity'],
                             level=r['level_req'] or 0, stats={}, pet={}, slots=set())
    for table, key in (('affix_stat', 'stats'), ('affix_pet_stat', 'pet')):
        for r in conn.execute(f'SELECT affix_id, field, idx, value, lo, hi, txt FROM {table}'):
            rec = recs.get(r['affix_id'])
            # Only idx 0: racialBonusRace is the one array on an affix (a second
            # race), and the line is one line whichever races it names.
            if rec is not None and r['idx'] == 0:
                rec[key][r['field']] = (r['value'], r['lo'], r['hi'], r['txt'])
    for r in conn.execute('SELECT affix_id, item_class FROM affix_eligibility'):
        if r['affix_id'] in recs:
            recs[r['affix_id']]['slots'].add(CLASS_TO_LABEL[r['item_class']])
    return list(recs.values())


def build(conn):
    fr = field_to_rows(SB.SHEET)
    fields, tags, names, slotsets, skills = [], [], [], [], []
    ix = lambda table, v: table.index(v) if v in table else (table.append(v) or len(table) - 1)
    field_ix = {}
    records, stats = [], collections.Counter()

    for a in sorted(load(conn), key=lambda a: a['path']):
        rows = line_rows(a['stats'], a['pet'])
        txt = I.read_rel(a['path'])
        pet_path = a['stats'].get('petBonusName', (None,) * 4)[3]
        pet_txt = I.read_rel(pet_path) if pet_path else None
        shown = display(txt, a['stats'], pet_txt, a['pet'])

        scored = []
        for r in rows:
            k = row_key(r)
            if k in fr and r['lo'] is not None and is_stat(r['field']):
                if k not in field_ix:
                    field_ix[k] = len(fields)
                    fields.append(k)
                scored.append([field_ix[k], r['lo'], r['hi']])
        grants = [[ix(skills, r['source']), r['field'], int(r['lo']), int(r['hi'])]
                  for r in rows if r['field'].startswith('skill') and r['source']
                  and r['lo'] is not None]
        slots = sorted(a['slots'], key=SLOT_ORDER.index)
        records.append([
            ix(tags, a['tag']), ix(names, a['name']),
            1 if a['kind'] == 'Suffix' else 0,
            1 if a['rarity'] == 'Rare' else 0,
            a['level'], line_count(rows), scored, grants,
            ix(slotsets, '|'.join(slots)),
            [[k, t, h, 1 if p else 0] for k, t, h, p in shown],
        ])
        stats['records'] += 1
        stats['with a scored field' if scored else 'nothing the sheet reads'] += 1

    return {
        'r': records, 't': tags, 'n': names, 'k': skills,
        's': [s.split('|') if s else [] for s in slotsets],
        'f': fields, 'lk': [line_key(f) for f in fields],
        'fr': [fr[f] for f in fields],
        'coarse': COARSE_SLOT, 'slotOrder': SLOT_ORDER, 'slotGroups': SLOT_GROUPS,
    }, stats


def main(out_dir=None):
    out_dir = out_dir or OUT
    os.makedirs(out_dir, exist_ok=True)
    conn = catalogue.connect(S.load().catalogue_db, create=False)
    corpus, stats = build(conn)
    p = os.path.join(out_dir, 'affixes.json')
    with open(p, 'w') as fh:
        json.dump(corpus, fh, separators=(',', ':'))
    print('  '.join(f'{k} {v}' for k, v in stats.items()))
    print(f'{len(corpus["t"])} tags  {len(corpus["f"])} scored fields  '
          f'{os.path.getsize(p) / 1e6:.2f} MB -> {p}')


if __name__ == '__main__':
    main()
