"""An item's tooltip lines AS ROLLED: the ported renderer plus the gaps it leaves.

Line-level fixes live in the renderer, `item_stats.py` (its DIVERGED table);
this module composes one item's lines from the ROLL: merged values, the
conversion as the game rounds it, split-off procs, and the record-only lines.

The evidence is the game's own tooltip text, which Item Assistant stores for
every item it holds; tests/test_seedroll_game.py holds every number these lines
print to it.

Component and augment are NOT inputs. A caller that wants them shows them
separately; the Gear Stash view leaves them off by the user's rule (2026-09-28).
"""
import collections
import re
import struct

from . import item_stats as I
from .archive import seedroll
from .archive.seedroll import Roll

# Stat fields the renderer never prints, with the game's own string for each (a
# tags_ui entry). Moved here from affixes/build.py, which reads it from here.
SUPPLEMENT = {'skillManaCostReduction': 'SkillManaCostReduction'}

def _fmt(v):
    return ('%f' % v).rstrip('0').rstrip('.')


def supplement(field, value):
    fmt = I.UI_TAGS[SUPPLEMENT[field]]
    return re.sub(r'\{\^.\}', '', fmt.replace('{%.0f0}', _fmt(round(value))))


def _only(txt, pattern):
    keep = re.compile(pattern)
    return '\n'.join(l for l in txt.splitlines() if keep.match(l.partition('=')[0])) + '\n'


def rolled(base_path, sources, roll, pets=None):
    """[(key, line)] for one item, in the order the game prints them.

    `sources` is {'base'|'prefix'|'suffix': record path} for the records the
    roll was made from; `roll` is seedroll's result for them and must not be a
    refusal. `key` says what the line is, for a caller that grades it: a raw
    field name for a stat line, `conversion`/`conversion2`, `skill:<record>`,
    `mastery:<record>`, `pet:<field>` for a pet bonus line (the key the
    scorer's pet rows read), `granted` for a granted skill's block, or None
    for a line nobody grades (a skill modifier). Granted skills come
    last, every source's, as the game prints them.

    `pets` is {which: Roll} for the pet bonuses, when the caller has them
    another way than from the seed (the Gear Catalogue: each end of a band).
    """
    if roll.unmodeled:
        raise ValueError('a refused roll has no lines: ' + ', '.join(roll.unmodeled))
    texts = {k: I.read_rel(p) or '' for k, p in sources.items()}
    base_txt = texts['base']
    # A record the game does not roll (stored_roll) has no seed, and its pet
    # bonus prints as stored.
    if pets is None:
        pets = pet_rolls(sources, roll.seed) if roll.seed is not None else {}

    nums = _numbers(roll)
    cls = (re.search(r'^Class=(\S+)', base_txt, re.M) or [None, ''])[1]
    own = weapon_damage(cls, nums)
    head = ''.join(l + '\n' for l in base_txt.splitlines()
                   if l.startswith(('Class=', 'characterBaseAttackSpeedTag=')))
    synthetic = head + ''.join(f'{k}={v:g}\n' for k, v in sorted(nums.items()))

    out = [(None, l) for l in I.base_weapon_damage(synthetic)]
    out += own
    out += [('defensiveProtection', l) for l in I.base_armor(synthetic)]
    out += [(None, l) for l in attacks_per_second(cls, base_txt)]

    printed = I.process_stats_fields(synthetic)
    fields = {f for f, _ in printed}
    out += printed

    for f in SUPPLEMENT:
        if f in nums:
            if f in fields:
                raise ValueError(f'the renderer prints {f} itself now; drop it from SUPPLEMENT')
            out.append((f, supplement(f, nums[f])))

    # A source whose chance-gated value seedroll split off (an affix with its own
    # Chance beside other sources): its own line, "N% Chance of ...".
    for p in roll.proc_lines:
        f = p['field']
        txt = f"{f}Chance={p['chance']:g}\n"
        if f.endswith('Modifier'):
            txt += f"{f}={p['min']:g}\n"
        else:
            txt += f"{f}Min={p['min']:g}\n" + (f"{f}Max={p['max']:g}\n" if p['max'] else '')
            if p.get('duration'):
                txt += f"{f}DurationMin={p['duration']:g}\n"
        out += I.process_stats_fields(txt)

    out += _conversions(roll, '')

    # Everything the renderer reads off the RECORD rather than off a number:
    # none of it rolls, so each source's own text is the input.
    granted = []
    out += racial_lines(texts)
    # An affix's skill level can be an equation in the level of the ITEM it sits on.
    item_level = re.search(r'^itemLevel=(\d+)', base_txt, re.M)
    item_level = int(item_level.group(1)) if item_level else None
    for which in ('base', 'prefix', 'suffix'):
        txt = texts.get(which)
        if not txt:
            continue
        granted += [('granted', l) for l in I.resolve_item_skill(txt, item_level)]
        for i in range(1, 9):
            name = re.search(rf'^augmentSkillName{i}=' + I.PATH, txt, re.M)
            if name:
                part = _only(txt, rf'^augmentSkill(Name|Level){i}$')
                out += [('skill:' + name.group(1), l) for l in I.resolve_augment_skills(part)]
            name = re.search(rf'^augmentMasteryName{i}=' + I.PATH, txt, re.M)
            if name:
                part = _only(txt, rf'^augmentMastery(Name|Level){i}$')
                out += [('mastery:' + name.group(1), l) for l in I.resolve_augment_mastery(part)]
        out += [(None, l) for l in I.augment_all_skills(txt)]
        out += [(None, l) for l in I.resolve_skill_modifiers(txt)]
        if which in pets:
            pet = pets[which]
            out += [('pet:' + f, l) for f, l in I.pet_lines(
                ''.join(f'{k}={v:g}\n' for k, v in sorted(_numbers(pet).items())))]
            out += [(None, l) for _, l in _conversions(pet, I.PET_PREFIX)]
        else:
            out += [('pet:' + f, l) for f, l in I.pet_bonus_lines(txt)]
            out += [(None, l) for l in I.resolve_pet_conversions(txt)]
    return [(k, l) for k, l in out + granted if l]


# A weapon's own Physical damage is its BASE line, as the game prints it first and
# without a "+": "70-91 Physical Damage" (Empowered Cruel Edge). The renderer
# prints those fields as an added bonus, "+70-91 Physical dmg" -- right for armour
# and jewellery, where they are one -- so on a Weapon* class they are taken out
# here. rolls.is_fixed draws the same line: they never roll on a weapon.
def weapon_damage(cls, nums):
    """[(key, line)] for a weapon's own Physical damage, removing its fields
    from `nums`; [] for anything else."""
    if not cls.startswith('Weapon') or 'offensivePhysicalMin' not in nums:
        return []
    lo = nums.pop('offensivePhysicalMin')
    hi = nums.pop('offensivePhysicalMax', lo)
    num = _fmt(lo) if hi == lo else f'{_fmt(lo)}–{_fmt(hi)}'
    out = [('offensivePhysicalMax', f'{num} Physical Damage')]
    # Armor Piercing follows it in the game's base block, and the renderer prints
    # it only beside Physical damage -- which it no longer sees -- so it is
    # rendered here, by the renderer, beside that damage.
    pierce = {f: nums.pop(f) for f in ('offensivePierceRatioMin', 'offensivePierceRatioMax') if f in nums}
    if pierce:
        txt = f'offensivePhysicalMin={lo:g}\n' + ''.join(f'{f}={v:g}\n' for f, v in pierce.items())
        out += [(f, l) for f, l in I.process_stats_fields(txt) if f.startswith('offensivePierceRatio')]
    return out


# "1.82 Attacks per Second", where the game prints the speed as a number:
#   characterAttackSpeed * (1 + characterBaseAttackSpeed) / attack time
# in float32, printed "%.2f". 1.25 is the player record's characterAttackSpeed
# (records/creatures/pc/malepc01.dbr). ⚠️ THE ATTACK TIMES ARE MEASURED, NOT
# READ: no record holds them. 19/30 s for a one-handed melee weapon and 0.7 s for
# everything else are the only simple values inside the intervals every game
# tooltip Item Assistant holds allows -- 69 distinct (kind, speed) pairs, 637
# weapons, 2026-10-02 -- and both sit exactly on a rounding edge there, which a
# fitted constant would not. tests/test_weapon_lines_game.py holds every weapon.
PLAYER_ATTACK_SPEED = 1.25
ONE_HANDED_TIME, OTHER_TIME = 19 / 30, 0.7
ATTACK_TIME = {
    **dict.fromkeys(('WeaponMelee_Axe', 'WeaponMelee_Mace', 'WeaponMelee_Sword',
                     'WeaponMelee_Dagger', 'WeaponMelee_Scepter'), ONE_HANDED_TIME),
    **dict.fromkeys(('WeaponMelee_Axe2h', 'WeaponMelee_Mace2h', 'WeaponMelee_Sword2h',
                     'WeaponMelee_Spear2h', 'WeaponHunting_Ranged1h',
                     'WeaponHunting_Ranged2h'), OTHER_TIME),
}


def _f32(x):
    return struct.unpack('f', struct.pack('f', x))[0]


def attacks_per_second(cls, txt):
    """The game's attack speed line for a weapon that attacks, [] for anything
    else (a shield or off-hand). Keyed on the class, not the speed tag: some
    weapons carry no tag and the game still prints their speed."""
    if cls not in ATTACK_TIME:
        return []
    x = float((re.search(r'^characterBaseAttackSpeed=(-?[\d.]+)', txt, re.M) or [None, 0])[1])
    aps = _f32(_f32(_f32(PLAYER_ATTACK_SPEED) * _f32(1 + _f32(x))) / _f32(ATTACK_TIME[cls]))
    return [f'{aps:.2f} Attacks per Second']


def racial_lines(texts):
    """[(key, line)] for the item's racial bonuses: "+12% Damage to Humans".
    racialBonus* is not a seedroll stat, so it is read at each record's value --
    which is what the game prints -- and SUMMED PER RACE across base, prefix and
    suffix, as the game prints it: 10% to Chthonics and Aetherials plus 15% to
    Aetherials and Aether Corruptions is "+25% Damage to Aetherials" (IAGD #1979)."""
    total = {}                            # (field, race) -> value, first seen first
    for which in ('base', 'prefix', 'suffix'):
        f = dict(l.split('=', 1) for l in (texts.get(which) or '').splitlines()
                 if l.startswith('racialBonus'))
        races = [r.strip() for r in f.pop('racialBonusRace', '').split(';') if r.strip()]
        for field, v in f.items():
            for race in races:
                total[(field, race)] = total.get((field, race), 0.0) + float(v.split(';')[0])
    out = []
    for race in dict.fromkeys(r for _, r in total):
        txt = f'racialBonusRace={race}\n' + ''.join(
            f'{f}={v:g}\n' for (f, r), v in total.items() if r == race)
        out += I.process_stats_fields(txt)
    return out


def pet_rolls(sources, seed):
    """{which: Roll} for each source in `sources` whose record names a pet bonus,
    rolled for an item of `seed` (seedroll.roll_pet). A refused pet roll raises:
    tests/test_seedroll_game.py holds every pet record in the game to rolling."""
    out = {}
    for which, path in sources.items():
        carrier = I.read_rec(path) or {}
        pet_path = (carrier.get('petBonusName') or [None])[0]
        if not pet_path:
            continue
        pet = I.read_rec(pet_path)
        if pet is None:
            raise ValueError(f'{path}: petBonusName {pet_path} is in no archive')
        roll = seedroll.roll_pet(pet, seed, None if which == 'base' else carrier)
        if roll.unmodeled:
            raise ValueError(f'{pet_path}: pet roll refused: ' + ', '.join(roll.unmodeled))
        out[which] = roll
    return out


def _numbers(roll):
    """A roll's numeric stats as the renderer should see them."""
    nums = {k: v for k, v in roll.stats.items() if isinstance(v, (int, float))}
    # seedroll emits a range's Max even where the record carries only a Min;
    # a Max equal to its Min would print "+306-306" for the game's "+306".
    nums = {k: v for k, v in nums.items()
            if not (k.endswith('Max') and nums.get(k[:-3] + 'Min') == v)}
    # A proc seedroll split off carries its own Chance; the echoed Chance must not
    # gate what is left of the field on the merged line. Nor its duration, once
    # nothing is left: it printed "+3 Burn Duration" beside "10% Chance of +504
    # Burn dmg over 3 Seconds" (IAGD #1990), which the game does not.
    for p in roll.proc_lines:
        nums.pop(p['field'] + 'Chance', None)
        if p['field'] + 'Min' not in nums:
            nums.pop(p['field'] + 'DurationMin', None)
    return nums


def _conversions(roll, prefix):
    """Every conversion pair the roll made -- a base and an affix converting
    different types are two lines -- at the rolled float, printed as the game
    prints it: 16.57 reads "17%"."""
    out = []
    for c in roll.conversions:
        sfx = c['field'][len('conversionPercentage'):]
        conv = (f"conversionInType={c['in']}\nconversionOutType={c['out']}\n"
                f"conversionPercentage={c['value']:.0f}\n")
        out += [('conversion' + sfx, l) for l in I.extract_conversions(conv, prefix)]
    return out


def stored_roll(txt):
    """A Roll holding a record's STORED values, for a record the game does not
    roll -- a component, an augment. seedroll.compute would jitter them from a
    seed they do not have. Every number on the record goes in; the renderer
    prints only what it knows. tests/test_augments.py holds rolled() over this
    to the renderer run on the record itself."""
    fields = dict(l.split('=', 1) for l in txt.splitlines() if '=' in l)
    stats = {}
    for f, v in fields.items():
        try:
            n = float(v.split(';')[0])
        except ValueError:
            continue
        if n:
            stats[f] = n
    conversions = [{'field': 'conversionPercentage' + m.group(1), 'in': fields[f],
                    'out': fields['conversionOutType' + m.group(1)],
                    'value': stats.get('conversionPercentage' + m.group(1), 100.0)}
                   for f in fields for m in [re.match(r'^conversionInType(\d*)$', f)]
                   if m and 'conversionOutType' + m.group(1) in fields]
    # A pair with no percentage converts 100%, as the renderer prints it; the
    # stats carry it too, so a grader reads the line the card shows.
    for c in conversions:
        stats.setdefault(c['field'], c['value'])
    return Roll(stats, {f: {'base': v} for f, v in stats.items()}, [], [], conversions)


# ---- set bonuses -------------------------------------------------------------
# ⚠️ THE TIER ENCODING IS RIGHT-ALIGNED AND THE RECORD NOWHERE SAYS SO. A set of M
# members has M-1 tiers, (2) through (M), and a numeric field's `;` array fills the
# LAST len(array) of them: a single value is the FULL-SET bonus, not the 2-piece.
# Left-aligning gives an equally well-formed block with every bonus on the wrong
# tier. A text field (a skill, a conversion type) has no array of its own: it is
# live wherever the number beside it is, and full-set only when nothing is beside
# it. tests/test_setbonus_game.py holds every tier to the game's own tooltips.
_SET_META = {'templateName', 'FileDescription', 'setName', 'setDescription',
             'setMembers', 'itemLevel', 'setSize'}
_COMPANION = [(re.compile(r'^augmentSkillName(\d+)$'), 'augmentSkillLevel{}'),
              (re.compile(r'^augmentMasteryName(\d+)$'), 'augmentMasteryLevel{}'),
              (re.compile(r'^conversion(?:In|Out)Type(\d*)$'), 'conversionPercentage{}'),
              (re.compile(r'^petBonusName()$'), 'petBonusLevel{}'),
              (re.compile(r'^itemSkill(?:Name|AutoController)()$'), 'itemSkillLevel{}')]


def _number(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def set_size(setrec):
    """Pieces for the full set: `setSize` where the record has one (The Arcanum
    lists 6 members and completes at 4, as the game's tiers show), else its members."""
    size = (setrec.get('setSize') or [None])[0]
    return int(float(size)) if size else len([m for m in setrec.get('setMembers') or [] if m])


def set_tier(setrec, pieces):
    """{field: value} a set grants with `pieces` of it worn -- every field, the
    tiers below included. `setrec` is a record as sheet.build.rec() returns it."""
    M = set_size(setrec)
    if pieces < 2 or M < 2:
        return {}
    slot, out = min(pieces, M) - 2, {}
    for f, arr in setrec.items():
        if f in _SET_META or not arr or any(_number(v) is None for v in arr):
            continue
        first = (M - 1) - len(arr)
        if first < 0:
            # Guessing which end to trim is the mistake this decode exists to avoid,
            # unless every value is the same (itemset_d115: 120 x4 over 3 tiers).
            if len(set(arr)) > 1:
                raise ValueError(f'{f} carries {len(arr)} values for a {M}-member set')
            arr, first = arr[-(M - 1):], 0
        if slot >= first and _number(arr[slot - first]):
            out[f] = arr[slot - first]
    for f, arr in setrec.items():
        if f in _SET_META or not arr or f in out or all(_number(v) is not None for v in arr):
            continue
        comp = next((c.format(m.group(1)) for rx, c in _COMPANION for m in [rx.match(f)] if m), None)
        if (comp in out) if comp and comp in setrec else pieces >= M:
            out[f] = arr[0]
    return out


def _text(fields):
    return ''.join(f'{f}={v}\n' for f, v in fields.items())


def set_block(setrec):
    """The set's bonuses as the game lists them: (tiers, after). `tiers` is
    [(pieces, [line])], each with only what it ADDS over the tier below (the
    arrays repeat a carried-over value on every tier); `after` is what the game
    prints below the tiers, untiered: the set's skill modifiers, then the skill
    the full set grants."""
    M = set_size(setrec)
    tiers, below = [], []
    for n in range(2, M + 1):
        txt = _text({f: v for f, v in set_tier(setrec, n).items() if not f.startswith('itemSkill')})
        tier = set_tier(setrec, n)
        lines = [l for name, fn, _ in I.EFFECT_BUILDERS
                 if name not in ('item skill', 'skill modifiers') for l in fn(txt) if l]
        lines += [supplement(f, float(tier[f])) for f in SUPPLEMENT if f in tier]
        left, added = collections.Counter(below), []
        for l in lines:
            if left[l]:
                left[l] -= 1
            else:
                added.append(l)
        if added:
            tiers.append((n, added))
        below = lines
    full = set_tier(setrec, M)
    after = I.resolve_skill_modifiers(_text(full))
    after += I.resolve_item_skill(_text({f: v for f, v in full.items() if f.startswith('itemSkill')}))
    return tiers, [l for l in after if l]
