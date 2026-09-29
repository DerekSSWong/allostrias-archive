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

from . import item_stats as I

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


def rolled(base_path, sources, roll):
    """[(key, line)] for one item, in the order the game prints them.

    `sources` is {'base'|'prefix'|'suffix': record path} for the records the
    roll was made from; `roll` is seedroll's result for them and must not be a
    refusal. `key` says what the line is, for a caller that grades it: a raw
    field name for a stat line, `conversion`/`conversion2`, `skill:<record>`,
    `mastery:<record>`, `granted` for a granted skill's block, or None for a
    line nobody grades (a pet bonus, a skill modifier). Granted skills come
    last, every source's, as the game prints them.
    """
    if roll.unmodeled:
        raise ValueError('a refused roll has no lines: ' + ', '.join(roll.unmodeled))
    texts = {k: I.read_rel(p) or '' for k, p in sources.items()}
    base_txt = texts['base']

    nums = {k: v for k, v in roll.stats.items() if isinstance(v, (int, float))}
    # seedroll emits a range's Max even where the record carries only a Min;
    # a Max equal to its Min would print "+306-306" for the game's "+306".
    nums = {k: v for k, v in nums.items()
            if not (k.endswith('Max') and nums.get(k[:-3] + 'Min') == v)}
    # A proc split off above carries its own Chance; the echoed Chance must not
    # gate what is left of the field on the merged line.
    for p in roll.proc_lines:
        nums.pop(p['field'] + 'Chance', None)
    head = ''.join(l + '\n' for l in base_txt.splitlines()
                   if l.startswith(('Class=', 'characterBaseAttackSpeedTag=')))
    synthetic = head + ''.join(f'{k}={v:g}\n' for k, v in sorted(nums.items()))

    out = [(None, l) for l in I.base_weapon_damage(synthetic)]
    out += [('defensiveProtection', l) for l in I.base_armor(synthetic)]
    out += [(None, l) for l in I.base_attack_speed(synthetic)]

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

    # Every conversion pair the roll made -- a base and an affix converting
    # different types are two lines -- at the rolled float, printed as the game
    # prints it: 16.57 reads "17%".
    for c in roll.conversions:
        sfx = c['field'][len('conversionPercentage'):]
        conv = (f"conversionInType={c['in']}\nconversionOutType={c['out']}\n"
                f"conversionPercentage={c['value']:.0f}\n")
        out += [('conversion' + sfx, l) for l in I.extract_conversions(conv, '')]

    # Everything the renderer reads off the RECORD rather than off a number:
    # none of it rolls, so each source's own text is the input.
    granted = []
    for which in ('base', 'prefix', 'suffix'):
        txt = texts.get(which)
        if not txt:
            continue
        # "+12% Damage to Humans": racialBonus* is not a seedroll stat, so it is
        # read at the record's value -- which is what the game prints.
        racial = _only(txt, r'^racialBonus')
        if racial.strip():
            out += I.process_stats_fields(racial)
        granted += [('granted', l) for l in I.resolve_item_skill(txt)]
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
        out += [(None, l) for l in I.resolve_pet_bonus(txt)]
        out += [(None, l) for l in I.resolve_pet_conversions(txt)]
    return [(k, l) for k, l in out + granted if l]


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
