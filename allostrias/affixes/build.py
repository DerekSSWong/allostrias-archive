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
from .. import item_lines as IL
from ..db import catalogue
from ..sheet import build as SB
from . import filter as F

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

# ---------------------------------------------------------- masteries --
def skill_masteries():
    """(masteries in the game's order, {skill record path: mastery}).

    From each mastery's own records/ui/skills/classNN/classtable.dbr -- the
    roster the game draws that skill tab from -- by the skill RECORD each button
    names, so neither a folder nor a display name decides it: a name is shared
    by unrelated skills (an item skill called Ring of Steel), and a folder is
    only where a file happens to sit. Ten masteries; Berserker is class10.
    """
    names, out = [], {}
    for i in range(1, 11):
        mastery = I.MASTERY_NAMES.get(f'SkillClass{i:02d}')
        table = I.read_rel(f'records/ui/skills/class{i:02d}/classtable.dbr')
        row = re.search(r'^tabSkillButtons=(.*)$', table or '', re.M)
        if not mastery or not row:
            raise SystemExit(f'class{i:02d} has no name or no skill roster')
        names.append(mastery)
        for button in filter(None, (b.strip() for b in row.group(1).split(';'))):
            m = re.search(r'^skillName=' + I.PATH, I.read_rel(button) or '', re.M)
            if m and out.setdefault(m.group(1).lower(), mastery) != mastery:
                raise SystemExit(f'{m.group(1)} is on two masteries\' rosters')
    return names, out


# The page's names for gd-lib's slot groups, where they differ. SLOT_GROUPS
# above stays a verbatim copy -- the corpus test holds it to gd-lib's -- and
# only what ships is renamed. "Weapon Type" is the user's (2026-09-25).
GROUP_LABELS = {'Hand': 'Weapon Type'}


def shipped_slot_groups():
    relabel = lambda g: dict(g, label=GROUP_LABELS.get(g['label'], g['label']))
    return [[relabel(g) for g in e] if isinstance(e, list) else relabel(e) for e in SLOT_GROUPS]


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
    # '1 Second' / '3 Seconds': a unit's plural follows the number, so the high
    # end's wording is the range's.
    singular = lambda parts: [re.sub(r'^(\s+\w+?)s\b', r'\1', p) for p in parts]
    if a != b and singular(a) == singular(b):
        a = b
    if a != b:
        raise ValueError(f'lines differ in shape: {lo_line!r} / {hi_line!r}')
    na, nb = _NUM.findall(lo_line), _NUM.findall(hi_line)
    moving = sum(x != y for x, y in zip(na, nb))
    out = [a[0]]
    for i, (x, y, rest) in enumerate(zip(na, nb, a[1:])):
        if x == y:
            out.append(x)
        else:
            # '+3–5%', not '+3–+5%': a sign both ends share is printed once,
            # as the game's own range strings do ('-{lo}-{hi}% Skill Energy Cost').
            y = y[1:] if x[0] == y[0] and x[0] in '+-' else y
            # A number that is one end of a range is bracketed even alone:
            # '1.5–(2.2–2.6) Seconds', never '1.5–2.2–2.6'.
            in_range = rest in ('–', '-') or a[i] in ('–', '-')
            out.append(f'({x}–{y})' if moving > 1 or in_range else f'{x}–{y}')
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


# Stat fields the ported tooltip renderer does not print (Energy Cost Reduction,
# 13 affix records). The gap is closed in this repo only, by the user's choice on
# 2026-09-25, so item_stats.py stays a verbatim copy. The table lives in
# item_lines.py now, shared with the Gear Stash view.
SUPPLEMENT = IL.SUPPLEMENT
_supplement = IL.supplement


def display(txt, stats, pet_txt, pet_stats, item_levels=None):
    """[(line key, text, hi, is_pet)] in the order the game prints them.

    Each builder of the ported tooltip renderer is run on its own fields, so
    every line comes back already knowing which line key it is -- which is what
    lets the page merge a unit's level tiers line by line. `hi` is the top of
    the line's roll, the number that picks the best tier."""
    lo = {f: s[1] for f, s in stats.items() if s[1] is not None}
    hi = {f: s[2] for f, s in stats.items() if s[2] is not None}
    out = []

    printed = _fields_and_lines(txt, lo, hi)
    for f, line in zip(*printed):
        out.append((line_key(f), line, hi.get(f), False))
    for f in SUPPLEMENT:
        if f not in stats:
            continue
        if f in printed[0]:
            # The renderer prints it now: a second line would be a duplicate.
            raise ValueError(f'the renderer prints {f} itself now; drop it from SUPPLEMENT')
        out.append((line_key(f), merge_band(_supplement(f, lo[f]), _supplement(f, hi[f])),
                    hi[f], False))

    conv = _banded_lines(lambda t: I.extract_conversions(t, ''), txt, lo, hi)
    out += [('conversion', line, hi.get('conversionPercentage'), False) for line in conv]

    for i in range(1, 6):
        if f'augmentSkillName{i}' not in stats:
            continue
        part = _only(txt, rf'^augmentSkill(Name|Level){i}$')
        for line in _banded_lines(I.resolve_augment_skills, part, lo, hi):
            out.append((f'skill{i}', line, hi.get(f'augmentSkillLevel{i}'), False))

    if pet_txt is not None:
        plo = {f: s[1] for f, s in pet_stats.items() if s[1] is not None}
        phi = {f: s[2] for f, s in pet_stats.items() if s[2] is not None}
        pet_txt = I.apply_skill_level(pet_txt, 0)
        for f, line in zip(*_fields_and_lines(pet_txt, plo, phi, I.pet_lines)):
            out.append(('pet:' + line_key(f), line, phi.get(f), True))
    # A granted skill last, below the pet bonus, as the game prints it.
    out += [('itemSkill', line, None, False) for line in granted_lines(txt, item_levels)]
    return out


def granted_lines(txt, item_levels):
    """An affix's granted skill across the item levels it rolls at. Its level
    can be an equation in the level of the item the affix lands on (Frostborn's
    Ice Spike is `(itemLevel*.25)+1`), and an affix card belongs to no item, so
    the skill is shown at both ends, banded, with a note saying it scales."""
    if not re.search(r'^itemSkillName=', txt, re.M):
        return []
    lo, hi = item_levels or (None, None)
    at = lambda lv: I.granted_skill_level(txt, lv)
    if lo is None or at(lo) == at(hi):
        return I.resolve_item_skill(txt, lo)
    a, b = I.resolve_item_skill(txt, lo), I.resolve_item_skill(txt, hi)
    if len(a) != len(b):
        raise ValueError(f'{a[0]}: lines appear or vanish between skill levels {at(lo)} and {at(hi)}')
    return [merge_band(x, y) for x, y in zip(a, b)] + [
        f'{a[0][len("Grants: "):]}: (skill level {at(lo)}–{at(hi)}: scales with item level)']


def _fields_and_lines(txt, lo, hi, render=I.process_stats_fields):
    a = render(_with_values(txt, lo))
    b = render(_with_values(txt, hi))
    if [f for f, _ in a] != [f for f, _ in b]:
        raise ValueError('stat lines differ between the low and the high roll')
    return [f for f, _ in a], [merge_band(x, y) for (_, x), (_, y) in zip(a, b)]


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
                             level=r['level_req'] or 0, stats={}, pet={}, slots=set(),
                             classes=set(), window=None)
    for r in conn.execute('SELECT affix_id, level_min, level_max FROM affix_level'):
        if r['affix_id'] in recs:
            recs[r['affix_id']]['window'] = (r['level_min'], r['level_max'])
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
            recs[r['affix_id']]['classes'].add(r['item_class'])
    return list(recs.values())


def class_top_levels(conn):
    """{item class: the highest itemLevel of any equipment of it}. A pool's
    randomizerLevelMax is often 200-500, past any item that exists (100).

    From `item_stat`, not the records: reading all ~7,600 equipment records for
    this one field cost 3.8 s of a 12.6 s build."""
    return dict(conn.execute(
        'SELECT i.class, MAX(CAST(s.num AS INTEGER)) FROM item i '
        'JOIN item_stat s ON s.item_id = i.id '
        "WHERE i.is_equipment = 1 AND s.field = 'itemLevel' AND s.idx = 0 "
        'GROUP BY i.class').fetchall())


def item_level_windows(affixes, top):
    """{(tag, slot set): (lo, hi)}: the item levels a whole affix card rolls
    at, its tiers together, each capped at the top item level of its classes."""
    out = {}
    for a in affixes:
        if not a['window']:
            continue
        cap = max((top[c] for c in a['classes'] if c in top), default=None)
        if cap is None:
            raise ValueError(f"{a['path']}: no item of its classes has an itemLevel")
        lo, hi = a['window'][0], min(a['window'][1], cap)
        k = (a['tag'], frozenset(a['slots']))
        out[k] = (min(out.get(k, (lo, hi))[0], lo), max(out.get(k, (lo, hi))[1], hi))
    return out


def build(conn):
    fr = field_to_rows(SB.SHEET)
    fields, tags, names, slotsets, skills = [], [], [], [], []
    ix = lambda table, v: table.index(v) if v in table else (table.append(v) or len(table) - 1)
    field_ix = {}
    records, stats = [], collections.Counter()

    affixes = load(conn)
    windows = item_level_windows(affixes, class_top_levels(conn))
    for a in sorted(affixes, key=lambda a: a['path']):
        rows = line_rows(a['stats'], a['pet'])
        txt = I.read_rel(a['path'])
        pet_path = a['stats'].get('petBonusName', (None,) * 4)[3]
        pet_txt = I.read_rel(pet_path) if pet_path else None
        shown = display(txt, a['stats'], pet_txt, a['pet'],
                        windows.get((a['tag'], frozenset(a['slots']))))

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

    # Every skill an affix grants ranks in belongs to a mastery's roster. One
    # that did not would silently drop out of the Mastery filter, so it stops
    # the build instead.
    masteries, of = skill_masteries()
    lost = [k for k in skills if k not in of]
    if lost:
        raise SystemExit(f'{len(lost)} granted skills are on no mastery roster: {lost[:3]}')
    return {
        'r': records, 't': tags, 'n': names, 'k': skills,
        'masteries': masteries, 'km': [masteries.index(of[k]) for k in skills],
        's': [s.split('|') if s else [] for s in slotsets],
        'f': fields, 'lk': [line_key(f) for f in fields],
        'fr': [fr[f] for f in fields],
        'coarse': COARSE_SLOT, 'slotOrder': SLOT_ORDER, 'slotGroups': shipped_slot_groups(),
        'filter': F.build(conn),
    }, stats


def inputs(conn, cfg) -> str:
    """Everything affixes.json is built from: this catalogue build (its
    stamp), the code, and the archives read beside it. The text archives are
    not in the catalogue's stamp, and the stat lines read their tags."""
    meta = sorted(tuple(r) for r in conn.execute('SELECT key, value FROM build_meta'))
    sources = sorted(tuple(r) for r in conn.execute('SELECT * FROM source_archive'))
    archives = [(p, os.path.getsize(p), os.stat(p).st_mtime_ns)
                for p in cfg.arz_paths + cfg.text_arc_paths]
    return json.dumps([meta, sources, archives, catalogue.code_digest()])


def main(out_dir=None, reuse=False):
    """Build affixes.json. `reuse` keeps the existing one when it was built
    from the same inputs: the Refresh server's startup, which spent 5 s
    rebuilding a bundle no save can change. Gates never pass it."""
    out_dir = out_dir or OUT
    os.makedirs(out_dir, exist_ok=True)
    cfg = S.load()
    conn = catalogue.connect(cfg.catalogue_db, create=False)
    p = os.path.join(out_dir, 'affixes.json')
    stamp_path = p + '.inputs'
    now = inputs(conn, cfg)
    if reuse and os.path.isfile(p) and os.path.isfile(stamp_path):
        with open(stamp_path) as fh:
            if fh.read() == now:
                print(f'affixes.json built from the same inputs, reused -> {p}')
                return
    # Removed BEFORE the bundle is rewritten, so a write that dies halfway
    # leaves no stamp vouching for it.
    if os.path.exists(stamp_path):
        os.remove(stamp_path)
    corpus, stats = build(conn)
    with open(p, 'w') as fh:
        json.dump(corpus, fh, separators=(',', ':'))
    with open(stamp_path, 'w') as fh:
        fh.write(now)
    print('  '.join(f'{k} {v}' for k, v in stats.items()))
    print(f'{len(corpus["t"])} tags  {len(corpus["f"])} scored fields  '
          f'{os.path.getsize(p) / 1e6:.2f} MB -> {p}')


if __name__ == '__main__':
    main()
