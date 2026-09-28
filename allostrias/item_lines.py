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
    `mastery:<record>`, or None for a line nobody grades (granted skill, pet).
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

    # The conversion: the TYPES come from the source whose pair was rolled
    # (seedroll credits only the first valid pair's source), the percentage is
    # the rolled float, printed as the game prints it -- 16.57 reads "17%".
    for sfx in ('', '2'):
        pf = 'conversionPercentage' + sfx
        if pf not in nums:
            continue
        src = next(s for s in ('base', 'prefix', 'suffix') if s in roll.parts.get(pf, {}))
        types = _only(texts[src], rf'^conversion(In|Out)Type{sfx}$')
        conv = types.replace(f'Type{sfx}=', 'Type=') + f'conversionPercentage={nums[pf]:.0f}\n'
        out += [('conversion' + sfx, l) for l in I.extract_conversions(conv, '')]

    # Everything the renderer reads off the RECORD rather than off a number:
    # none of it rolls, so each source's own text is the input.
    for which in ('base', 'prefix', 'suffix'):
        txt = texts.get(which)
        if not txt:
            continue
        # "+12% Damage to Humans": racialBonus* is not a seedroll stat, so it is
        # read at the record's value -- which is what the game prints.
        racial = _only(txt, r'^racialBonus')
        if racial.strip():
            out += I.process_stats_fields(racial)
        out += [(None, l) for l in I.resolve_item_skill(txt)]
        for i in range(1, 9):
            name = re.search(rf'^augmentSkillName{i}=(\S+)', txt, re.M)
            if name:
                part = _only(txt, rf'^augmentSkill(Name|Level){i}$')
                out += [('skill:' + name.group(1), l) for l in I.resolve_augment_skills(part)]
            name = re.search(rf'^augmentMasteryName{i}=(\S+)', txt, re.M)
            if name:
                part = _only(txt, rf'^augmentMastery(Name|Level){i}$')
                out += [('mastery:' + name.group(1), l) for l in I.resolve_augment_mastery(part)]
        out += [(None, l) for l in I.augment_all_skills(txt)]
        out += [(None, l) for l in I.resolve_skill_modifiers(txt)]
        out += [(None, l) for l in I.resolve_pet_bonus(txt)]
        out += [(None, l) for l in I.resolve_pet_conversions(txt)]
    return [(k, l) for k, l in out if l]
