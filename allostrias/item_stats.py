"""How a record's stats read, in the game's own words.

Every project that prints a stat prints it through here. The GD Catalogue builds
its cards from `effects_of()`; the affix line table stores what this renders in
its `label` column, and GD Lens reads that column, so GD Lens is already showing
this module's output whether or not it calls it.

WHAT IS HERE: the field maps, the damage-type and resistance labels, the number
formatting, and the resolvers that turn a granted skill, an augment, a pet bonus
or a conversion into lines. `effects_of()` is the ONE order in which every caller
emits a record's lines -- four hand-composed lists that differed in membership
AND order preceded it, and that divergence is what hid an affix-conversion bug.

WHAT IS NOT HERE, on purpose: anything that composes a CARD. Slot families, item
naming, faction palettes, badges and the rest stayed in the catalogue, because
they answer "how does this look in that list", not "what does this record say".
The line is "renders a stat" against "lays out a card", and it is thinner than
the other boundaries in this repo -- when in doubt, a thing that would read
differently on a different page belongs to that page.
"""
import re

from . import settings as S
from . import skill_triggers as st
from .archive import arc
from .archive.records import Records

# ---------------------------------------------------------------------------
# PORTED FROM gd-lib's item_stats.py, not imported. The file is a verbatim copy
# except for this block and read_rel() below; everything else is left alone
# precisely so `diff` stays the review, and tests/test_item_stats.py runs both
# against every item in the catalogue and requires them to agree exactly.
#
# The boundary that moved is WHERE RECORDS AND TAGS COME FROM. gd-lib reads
# gd-lib's `.extracted/` text tree; this reads the .arz and the .arc through
# archive/records.py and archive/arc.py, so allostrias builds on an install
# where gd-lib has never run. Records.text() reproduces the .extracted files
# byte for byte, which is what makes the two comparable at all.
#
# The four tag FAMILIES are kept separate rather than merged. See
# archive/arc.load_tag_families: they are disjoint today, so merging would
# behave identically -- but it would also let this resolve tags the original
# could not, and a port that is more forgiving than its oracle cannot be held
# to it.
# ---------------------------------------------------------------------------
_cfg = S.load()
_records = Records(_cfg.arz_paths)
_tags = arc.load_tag_families(_cfg.text_arc_paths)

ITEM_TAGS = _tags['items']
UI_TAGS = _tags['ui']
SKILL_TAGS = _tags['skills']


def clean_name(name):
    """Strip Grim Dawn's inline colour-code tokens, e.g. '^kMark of Dreeg'."""
    return re.sub(r'\^.', '', name).strip() if name else name


MASTERY_NAMES = {f'SkillClass{i:02d}': n for i, n in enumerate(
    (clean_name(SKILL_TAGS.get(f'tagSkillClassName{i:02d}', ''))
     for i in range(1, 11)), start=1) if n}


# A rune's granted-skill name (skillDisplayName=) resolves through the
# SKILLS tag family, not items or ui -- easy to miss, cost 54/486 items
# (all their effects) the first time this script was written.
# Monster-race names (tagRaceNNN / tagRaceNNNP) for racialBonusRace= live in
# their OWN tag family -- not items, ui, or skills. Missing this rendered
# "+10% Damage to Race004" instead of "...to Chthonics".
CREATURE_TAGS = _tags['creatures']
_UNUSED_CREATURE_TAGS = ('tags_creatures.txt', 'tagsgdx1_creatures.txt',
                              'tagsgdx2_creatures.txt', 'tagsgdx3_creatures.txt')


# ------------------------------------------------------------- stat names ---
# offensiveSlow{Type}* is the damage-over-time variant of a direct type and
# has its own in-game name for most types (Fire->Burn, Cold->Frostburn,
# Lightning->Electrocute, Physical->Trauma [NOT "Internal Trauma" -- that's
# the debuff-icon name, every stat-line tag says "Trauma"], Life->Vitality
# Decay). Poison/Bleeding/Chaos/Aether do NOT follow the offensive/offensiveSlow
# split evenly:
#   - offensivePoison*      (no "Slow") = DIRECT hit, displays as "Acid"
#   - offensiveSlowPoison*                = the true DoT, displays as "Poison"
#   - Chaos and Aether have NO slow/DoT variant at all (verified: zero
#     offensiveSlowChaos*/offensiveSlowAether* fields anywhere in the item db)
#   - Bleeding has NO direct variant at all (verified: zero offensiveBleeding*
#     without "Slow" -- it is DoT-only)
DOT_NAME = {
    'Fire': 'Burn', 'Cold': 'Frostburn', 'Lightning': 'Electrocute',
    'Physical': 'Trauma', 'Life': 'Vitality Decay',
}


DIRECT_NAME = {
    'Poison': 'Acid',  # offensivePoison* (non-slow) is the direct hit
}


SAME_NAME_NO_DOT = {'Chaos', 'Aether'}  # direct-only, no slow variant exists


# defensiveX (flat, no suffix) = X Resist. A few types have unusual raw
# field spellings that don't match the {Type} pattern used elsewhere.
RESIST_LABEL_OVERRIDE = {
    'Poison': 'Poison/Acid Resist',       # one shared resist pool, confirmed
                                            # via tagCharStatsPetPoisonResist
    'Life': 'Vitality Resist',             # defensiveLife means Vitality, not Health
    'ElementalResistance': 'Elemental Resist',
    'TotalSpeedResistance': 'Slow Resist',
}


# Misc named stats that don't fit the offensive/defensive/{Type} pattern.
# mine -> in-game, confirmed against tagCharStats*/Damage* tags in tags_ui.txt.
# Min/Max PAIRS that Pass 2's type loop cannot reach, because it only handles
# kinds in DAMAGE_TYPES and these parse as kind="BonusPhysical" /
# "PercentCurrentLife". Each renders as ONE range line, and neither takes the
# leading "+" MISC_FIELD_MAP adds -- per the game's own format strings in
# text_en/, which are the authority here rather than a guess:
#   DamageBonusPhysical      = {%t0} {^E}Physical Damage
#   DamagePercentCurrentLife = {%t0}% {^E}Reduction to Enemy's Health
# (label, is_pct)
RANGE_FIELD_MAP = {
    'offensiveBonusPhysical': ('Physical Damage', False),
    'offensivePercentCurrentLife': ("Reduction to Enemy's Health", True),
}


MISC_FIELD_MAP = {
    'characterOffensiveAbility': ('Offensive Ability', False),
    'characterDefensiveAbility': ('Defensive Ability', False),
    'characterOffensiveAbilityModifier': ('Offensive Ability', True),
    'characterDefensiveAbilityModifier': ('Defensive Ability', True),
    'characterAttackSpeedModifier': ('Attack Speed', True),
    'characterSpellCastSpeedModifier': ('Cast Speed', True),
    'characterRunSpeedModifier': ('Movement Speed', True),  # tagCharRunSpeedModifier, not "Run Speed"
    'characterTotalSpeedModifier': ('Total Speed', True),
    'characterLifeModifier': ('Health', True),
    'characterLife': ('Health', False),
    'characterLifeRegenModifier': ('Health Regeneration', True),
    'characterLifeRegen': ('Health Regeneration', False),
    'characterManaModifier': ('Energy', True),
    'characterMana': ('Energy', False),
    'characterManaRegenModifier': ('Energy Regeneration', True),
    'characterManaRegen': ('Energy Regeneration', False),
    'characterEnergyAbsorptionPercent': ('Energy Absorption', True),
    'characterHealIncreasePercent': ('Healing Increased', True),
    'characterConstitutionModifier': ('Constitution Bonus', True),
    # Flat/percent primary-attribute bonuses -- confirmed missing entirely
    # (rendered as NO effect line at all) 2026-08-20 while investigating why
    # affix "Enlightening" and item base "Basinet" showed zero stats in the
    # affix/base review catalogue; ~84 affix files each carry the flat form.
    # Labels are the game's own player-facing attribute names, NOT the raw
    # field names -- confirmed via tags_ui.txt: `Strength=Physique`,
    # `Dexterity=Cunning`, `Intelligence=Spirit`, and their tagCharAttribute0
    # {1,2,3}/tagCharAttribute0{1,2,3}Modifier tooltip format strings.
    'characterStrength': ('Physique', False),
    'characterDexterity': ('Cunning', False),
    'characterIntelligence': ('Spirit', False),
    'characterStrengthModifier': ('Physique', True),
    'characterDexterityModifier': ('Cunning', True),
    'characterIntelligenceModifier': ('Spirit', True),
    # tagCharIncreasedExperience={%+.0f0}% {^E}Experience Gained -- also
    # found missing via the "Enlightening" investigation above.
    'characterIncreasedExperience': ('Experience Gained', True),
    # confirmed via tags_ui.txt: DefenseBleedingDuration/DefensePoisonDuration
    # -> "{%.0f0}% Reduction in Bleeding/Poison Duration" (note: NO "+" in
    # the game's own format string, unlike almost every other percent stat
    # here -- this map's shared sign logic will still prepend one; a known,
    # minor cosmetic mismatch, same class as the pure-Physical-weapon "+"
    # noted in build_mi_catalogue.base_weapon_damage(), not a data-loss bug).
    'defensiveBleedingDuration': ('Reduction in Bleeding Duration', True),
    'defensivePoisonDuration': ('Reduction in Poison Duration', True),
    # "All Damage" (not just "Damage") -- confirmed via tags_ui.txt:
    # `tagDamageModifierTotalDamage={%+.0f0}% {^E}to All Damage` (the
    # game's own text also prepends "to", but every other MISC_FIELD_MAP/
    # PET_FIELD_MAP label uses the bare-label + generic sign/percent
    # convention with no "to", so this only changes the label itself, not
    # the surrounding sentence structure, to stay consistent with every
    # other stat line here).
    'offensiveTotalDamageModifier': ('All Damage', True),
    'offensiveCritDamageModifier': ('Critical Damage', True),
    'defensiveProtectionModifier': ('Armor', True),
    # Mislabeled "Damage Blocked" until now -- confirmed via tags_ui.txt's
    # own UI format string, `DefenseBlockModifier={%+.0f0}% {^E}Shield
    # Block Chance` (user-flagged via "Aetherthorn Shield"'s "Arcane Will"
    # modifier showing "+50% Shield Block Chance" for this exact field).
    'defensiveBlockModifier': ('Shield Block Chance', True),
    'defensiveBlockRecovery': ('Block Recovery', True),
    'defensiveDisruptionProjectile': ('Deflect Chance', True),
    'skillCooldownReduction': ('Cooldown Reduction', True),
    'characterLightRadius': ('Light Radius', False),
    # These 4 resistance names were already correctly mapped for the PET_FIELD_MAP
    # context below but never for a plain item's own top-level stats (user-flagged
    # via "Bloodbound Helm"/"Frostplume Mantle": defensiveElementalResistance/
    # defensiveStun on their own base records rendered nothing at all). Not
    # caught by TYPE_FIELD_RE below because the raw field name itself
    # ("ElementalResistance"/"TotalSpeedResistance"/"Stun"/"Freeze") isn't a
    # DAMAGE_TYPES member -- "Elemental" is, but "ElementalResistance" as a
    # whole word isn't, so TYPE_FIELD_RE's `kind not in DAMAGE_TYPES` check
    # silently drops the field entirely rather than matching a truncated kind.
    # All 4 are percentages in-game -- confirmed via tags_ui.txt (same
    # DefenseFreeze/DefenseStunNegative/DefenseElementalResistance/
    # tagTotalSpeedResistance format strings cited in process_stats()'s
    # generic resist branch above; user-flagged the sibling bug via
    # "Ascendant Source"'s Chaos Resistance).
    'defensiveElementalResistance': ('Elemental Resist', True),
    'defensiveTotalSpeedResistance': ('Slow Resist', True),
    'defensiveStun': ('Stun Resist', True),
    'defensiveFreeze': ('Freeze Resist', True),
    # "X% of Attack Damage converted to Health" (life leech) -- shown without
    # a leading "+" in the real tooltip (verified against "Bloodbound Helm"'s
    # "4/6% of Attack Damage converted to Health"), unlike every other %
    # stat in MISC_FIELD_MAP, so it can't just reuse the generic sign+label
    # formatting process_stats() applies to this whole map -- handled as a
    # special case directly in process_stats() below instead of here.
    # Resistance Reduction ("RR") is a `Damage*=` proc-tooltip tag family,
    # not a tagCharStats one: DamageTotalResistanceReductionAbsolute=
    # "{^E}Reduced target's Resistances" / ...Percent="% {^E}Reduced
    # target's Resistances". Flat-vs-percent already conveyed by the %
    # sign, same convention as Health/Armor/etc, so both map to one label.
    # NOTE the raw fields carry a Min/DurationMin suffix (unlike most other
    # MISC_FIELD_MAP entries) -- confirmed against Mark of Dreeg's/Hexxer's
    # Kiss's actual records; a sibling `...PercentChance` field also exists
    # (proc trigger chance) and is deliberately NOT mapped/shown.
    'offensiveTotalResistanceReductionAbsoluteMin': ("Reduced Target's Resistances", False),
    'offensiveTotalResistanceReductionPercentMin': ("Reduced Target's Resistances", True),
    'offensiveTotalResistanceReductionAbsoluteDurationMin': ("Reduced Target's Resistances Duration", False),
    'offensiveTotalResistanceReductionPercentDurationMin': ("Reduced Target's Resistances Duration", True),
    # "Entrapment Resistance" -- confirmed via tags_ui.txt's own tooltip
    # format string, `DefenseTrapNegative={%.0f0}% {^E}Entrapment
    # Resistance` (the shorter character-sheet tag, `tagCharStatsTrapResist`,
    # says "Trap Resist" instead -- picked the tooltip wording here since
    # it's what the user's pasted real item tooltip actually showed, and
    # this map is for item-tooltip lines specifically). "Trap" isn't a
    # DAMAGE_TYPES member so the generic resist loop above never sees it --
    # user-flagged via "Bysmiel-Sect Legguards": defensiveTrap=40 rendered
    # nothing at all (its whole "32/48% Entrapment Resistance" line missing).
    'defensiveTrap': ('Entrapment Resist', True),
    # Eight fields that were entirely unhandled, so 86 items rendered with fewer
    # effect lines than they should. Labels confirmed against tags_ui.txt:
    #   DefensePetrifyNegative        -> Petrify Resistance
    #   DefenseLifeLeach              -> Life Leech Resistance
    #   DefenseAbsorptionModifier     -> Increases Armor Absorption by N%
    #   DefenseBlockAmountModifier    -> Shield Damage Blocked
    #   tagRetaliationModifierTotalDamage -> Retaliation Damage
    #   tagCharStatsReflectResist     -> Reflect Resist
    #   DefenseDisruption             -> Disruption Resist
    #   defensiveBonusProtection      -> flat "+N Armor" (no tag found; the field
    #                                    name and behaviour are unambiguous next
    #                                    to its sibling defensiveProtection)
    # TWO TRAPS HERE.
    # defensiveBlockAmountModifier ("Shield Damage Blocked") is a DIFFERENT field
    # from defensiveBlockModifier ("Shield Block Chance") -- some items carry both
    # (e.g. "Survivor's Resilience"), so they are two separate real stat lines.
    # The Retaliation label deliberately keeps the short wording the published
    # catalogue already used, not the tag's verbose "to All Retaliation Damage".
    'defensivePetrify': ('Petrify Resist', True),
    'defensiveSlowLifeLeach': ('Life Leech Resist', True),
    # Same "Slow{X}Leach" naming pattern as defensiveSlowLifeLeach above,
    # different resource -- confirmed via tags_ui.txt:
    # `DefenseManaLeach={%.0f0}% {^E}Energy Leech Resistance` (user-flagged
    # via "Soul Shard": defensiveSlowManaLeach=25 lost its whole "+25%
    # Energy Leech Resist" line).
    'defensiveSlowManaLeach': ('Energy Leech Resist', True),
    'defensiveAbsorptionModifier': ('Armor Absorption', True),
    'defensiveBlockAmountModifier': ('Shield Damage Blocked', True),
    'retaliationTotalDamageModifier': ('Retaliation Damage', True),
    'defensivePercentReflectionResistance': ('Reflect Resist', True),
    'defensiveDisruption': ('Disruption Resist', True),

    # Four fields whose OLD published label was GARBLED, not merely missing:
    # "+75 Protection Resist" for defensiveProtection (a flat Armor field with no
    # Resist concept at all), "+15% Fire Duration Resist" for defensiveFireDuration
    # (real label: "Reduction in Burn Duration" -- the game's Fire->Burn DoT rename
    # applies here too).
    # CAUSE, AND IT IS A CLASS OF BUG NOT TWO INSTANCES: whatever generated the old
    # data had a silent fallback that stringified an unmapped field's raw kind name
    # instead of skipping it. This version skips. Expect more garbled-looking old
    # labels from the same source.
    # NOTE defensiveProtection is deliberately NOT in this map -- it means two
    # different things depending on the record and needs the Class= check in
    # process_stats(). See that branch.
    'defensiveFireDuration': ('Reduction in Burn Duration', True),
    # `characterDeflectProjectile` -- a DIFFERENT field from
    # `defensiveDisruptionProjectile` (both -> "Deflect Chance" per
    # tags_ui.txt's `tagCharStatsProjDeflectChance`), only the latter was
    # mapped before -- user-flagged via "Ballistic Plating"'s
    # `characterDeflectProjectile=10` losing its whole "+10% Deflect Chance"
    # line.
    # "Chance to Avoid Projectiles" per tagCharDeflectProjectiles -- the ITEM
    # line, and the exact counterpart of characterDodgePercent's melee wording
    # below. It shipped as "Deflect Chance" (tagCharStatsProjDeflectChance, the
    # character sheet's name) until a user-supplied item block showed otherwise.
    'characterDeflectProjectile': ('Chance to Avoid Projectiles', True),
    # `characterDodgePercent` -- melee avoidance, and the THIRD instance of the
    # class of bug the block above predicts: an unmapped field is dropped whole,
    # silently, on every catalogue at once. User-flagged 2026-08-22 via Explorer's
    # Trousers, whose `characterDodgePercent=4` was missing from its card. 72 item
    # records carry it. Label from tags_ui.txt `tagCharDodgePercent`; do NOT
    # shorten it to "Dodge Chance", which is the CHARACTER-SHEET label
    # (`tagCharStatsDodgeChance`) for the same stat, not the item-line one.
    'characterDodgePercent': ('Chance to Avoid Melee Attacks', True),
}


DAMAGE_TYPES = ['Fire', 'Cold', 'Lightning', 'Physical', 'Poison', 'Bleeding',
                'Chaos', 'Aether', 'Vitality', 'Life', 'Pierce', 'Elemental']


def _type_dmg_label(kind):
    """kind is a raw {Type} token from an offensive*/offensiveSlow* field."""
    if kind in DIRECT_NAME:
        return DIRECT_NAME[kind] + ' dmg'
    if kind == 'Life':
        return 'Vitality dmg'
    return kind + ' dmg'


def _type_dot_label(kind):
    if kind in DOT_NAME:
        return DOT_NAME[kind] + ' dmg'
    if kind in SAME_NAME_NO_DOT:
        # Should never actually be reached (no offensiveSlow{Chaos,Aether}
        # fields exist), but fail loudly rather than silently mislabel if
        # a future patch adds one.
        raise ValueError(f'Unexpected offensiveSlow{kind}* field — {kind} was '
                          f'confirmed to have no DoT variant when this was written')
    return kind + ' dmg'  # Poison, Bleeding: DoT name == direct name


def _resist_label(kind):
    if kind in RESIST_LABEL_OVERRIDE:
        return RESIST_LABEL_OVERRIDE[kind]
    return kind + ' Resist'


def _dot_duration_label(kind):
    if kind in DOT_NAME:
        return DOT_NAME[kind] + ' Duration'
    if kind == 'Bleeding':
        return 'Bleed Duration'  # tagCharStatsBleedDuration=Bleed Duration
    return kind + ' Duration'   # Poison


TYPE_FIELD_RE = re.compile(
    r'^(offensive|defensive|retaliation)(Slow)?([A-Za-z]+?)'
    r'(Min|Max|Modifier|DurationMin|DurationModifier)?=(-?[\d.]+)', re.M)


def _fmt_num(raw):
    if '.' in raw:
        raw = raw.rstrip('0').rstrip('.')
    return raw


def process_stats(txt):
    """Every recognized offensive/defensive/retaliation/character/skill stat
    line in `txt` as a display string, in the same alphabetical-by-field-name
    order the source .dbr stores them in (matches what the game's own tooltip
    renders in practice).

    A thin wrapper over process_stats_fields(), which carries the FIELD NAME
    each line came from. That pairing was always built internally and thrown
    away here; keeping this function returning bare strings means the four
    catalogues and GD Lens are untouched by exposing it."""
    return [line for _, line in process_stats_fields(txt)]


def process_stats_fields(txt):
    """(field, display string) for every stat line, in emission order.

    The field name is what makes a stat line QUERYABLE -- "how many affixes
    carry Cold Resist" cannot be answered from the prose alone, which is why
    .gdtools grew a second parser (build_affix_catalogue.numeric_fields) to
    recover it. This is the supported way to get it.

    NOT one field per line, and it never was: a damage range emits one line
    from a Min/Max pair (attributed to `<stem>Min`), and a few lines are
    attributed to a synthesized key (`blockRecoveryTime`, `blockAbsorption`)
    that is not a record field at all. Callers joining on record fields must
    tolerate both."""
    seen_lines = []
    # Pass 1: misc named fields (character*, skill*, offensiveTotalDamage*,
    # defensiveProtection*, Resistance Reduction, etc.)
    # Fields whose combined-sentence pass below owns the output; emitting them
    # here too would print the same debuff twice, once split and once joined.
    rr_combined = {
        stub for stub in ('TotalResistanceReductionAbsolute', 'TotalResistanceReductionPercent')
        if re.search(rf'^offensive{stub}Min=', txt, re.M)
        and re.search(rf'^offensive{stub}DurationMin=', txt, re.M)
    }
    emitted_ranges = set()
    for field, val in re.findall(r'^([A-Za-z0-9]+)=(-?[\d.]+)', txt, re.M):
        if any(field.startswith(f'offensive{stub}') for stub in rr_combined):
            continue
        if field.endswith(('Min', 'Max')) and field[:-3] in RANGE_FIELD_MAP:
            # Min and Max both land here; emit the pair once, from whichever
            # arrives first, exactly as Pass 2 does for the DAMAGE_TYPES pairs.
            stem = field[:-3]
            if stem in emitted_ranges:
                continue
            emitted_ranges.add(stem)
            label, is_pct = RANGE_FIELD_MAP[stem]
            minv = re.search(rf'^{stem}Min=(-?[\d.]+)', txt, re.M)
            maxv = re.search(rf'^{stem}Max=(-?[\d.]+)', txt, re.M)
            if not minv:
                continue
            num = _fmt_num(minv.group(1))
            if maxv and maxv.group(1) != minv.group(1):
                num = f"{num}\u2013{_fmt_num(maxv.group(1))}"
            seen_lines.append((f'{stem}Min', f"{num}{'%' if is_pct else ''} {label}"))
        elif field in MISC_FIELD_MAP:
            label, is_pct = MISC_FIELD_MAP[field]
            sign = '' if val.startswith('-') else '+'
            seen_lines.append((field, f"{sign}{_fmt_num(val)}{'%' if is_pct else ''} {label}"))
        elif field == 'offensiveLifeLeechMin':
            # "X% of Attack Damage converted to Health" -- no leading "+"
            # in the real tooltip (verified against Bloodbound Helm's own
            # "4/6% of Attack Damage converted to Health"), unlike every
            # other MISC_FIELD_MAP percent stat.
            seen_lines.append((field, f"{_fmt_num(val)}% of Attack Damage converted to Health"))
        elif field == 'characterManaLimitReserve':
            # "150 Energy Reserved" -- a COST, printed without a leading "+"
            # (tagCharManaLimitReserve={%.0f0} Energy Reserved), like
            # offensiveLifeLeechMin above. 82 records carry it, including every
            # set that grants a reserved-energy aura.
            seen_lines.append((field, f'{_fmt_num(val)} Energy Reserved'))
        elif field == 'characterWeaponStrengthReqReduction':
            # "-N% Physique Requirement for all Weapons" -- ALWAYS a
            # negative display regardless of the raw field's (always-
            # positive) sign, per tags_ui.txt's own UI format string:
            # `tagCharWeaponStrengthReqReduction=-{%.0f0}% ... Physique
            # Requirement for all Weapons` (user-flagged via "Kymon's
            # Badge"). "Strength" is this stat's old internal name; the
            # game calls it "Physique" everywhere player-facing (see
            # gd_ingame_terminology).
            seen_lines.append((field, f"-{_fmt_num(val)}% Physique Requirement for all Weapons"))
        elif field == 'characterDefensiveBlockRecoveryReduction':
            # "-N% Shield Recovery Time" -- ALWAYS negative regardless of
            # the raw field's sign, same field + same always-negative
            # convention already fixed for the skill-modifier level in
            # build_mi_catalogue.py ("Aetherthorn Shield"'s "Arcane Will"
            # modifier) -- process_stats() never had this special case for
            # a plain top-level item, so "Rimethorn Ash"
            # (characterDefensiveBlockRecoveryReduction=5) lost its whole
            # line here even though the identical field on a skill modifier
            # already worked. Confirmed via tags_ui.txt:
            # `tagCharDefensiveBlockRecoveryReduction={-%.0f0}%...Shield
            # Recovery Time`.
            seen_lines.append((field, f"-{_fmt_num(val)}% Shield Recovery Time"))
        elif field in ('racialBonusPercentDamage', 'racialBonusPercentDefense',
                       'racialBonusAbsoluteDamage', 'racialBonusAbsoluteDefense'):
            pass  # needs its paired racialBonusRace, handled once below
        elif field in ('defensiveProtection', 'defensiveBonusProtection'):
            # Same raw field, two different in-game meanings -- and the game
            # itself ships two different format tags for exactly this split:
            #   DefenseAbsorptionProtection={%.0f0} Armor        (no plus)
            #   DefenseAbsorptionProtectionPlus=+{%.0f0} {^E}Armor
            # On an equippable piece (Class=ArmorProtective_*/WeaponArmor_*)
            # it's that piece's OWN base Armor rating and renders WITHOUT a
            # "+" -- and for those, build_mi_catalogue.base_armor() already
            # emits it, so emitting it here too double-printed the line on
            # 177 MI / 250 Craftable items (caught by diffing a rebuild after
            # this field was first added here for the Augments catalogue).
            # On a component/augment/relic (Class=ItemRelic/ItemEnchantment)
            # it's a GRANTED bonus and renders "+75 Armor" -- that's the case
            # this map entry was originally added for ("Bloodied Crystal").
            cls_m = re.search(r'^Class=(\S+)', txt, re.M)
            cls = cls_m.group(1) if cls_m else ''
            if not cls.startswith(('ArmorProtective_', 'WeaponArmor_')):
                seen_lines.append((field, f"+{_fmt_num(val)} Armor"))
        elif field in ('defensiveBlock', 'defensiveBlockChance', 'blockRecoveryTime', 'blockAbsorption'):
            pass  # handled together as one combined line below, once per record

    # Shield base stats -- a genuinely different item Class (WeaponArmor_
    # Shield) had never been exercised through process_stats() before
    # (user-flagged via "Aetherthorn Shield": completely missing "32%
    # Chance to block 780 damage" and "0.5 second Block Recovery"). Two
    # separate lines, matching the real tooltip: chance+amount combine into
    # one sentence (`defensiveBlockChance`+`defensiveBlock`), recovery time
    # is its own line (`blockRecoveryTime`, confirmed via tags_ui.txt's
    # `ShieldBlockRecoveryTime={%.2f0} second Block Recovery`).
    # `blockAbsorption` is only shown when it's a REDUCED (<100%) absorb --
    # every shield checked has 100 (full block absorption), which the real
    # tooltip doesn't bother stating, so treat 100 as the unstated default.
    chance_m = re.search(r'^defensiveBlockChance=([\d.]+)', txt, re.M)
    if chance_m:
        block_m = re.search(r'^defensiveBlock=([\d.]+)', txt, re.M)
        line = f"{_fmt_num(chance_m.group(1))}% Chance to block"
        if block_m:
            line += f" {_fmt_num(block_m.group(1))} damage"
        seen_lines.append(('defensiveBlockChance', line))
    recovery_m = re.search(r'^blockRecoveryTime=([\d.]+)', txt, re.M)
    if recovery_m:
        seen_lines.append(('blockRecoveryTime', f"{_fmt_num(recovery_m.group(1))} second Block Recovery"))
    absorb_m = re.search(r'^blockAbsorption=([\d.]+)', txt, re.M)
    if absorb_m and absorb_m.group(1) != '100':
        seen_lines.append(('blockAbsorption', f"{_fmt_num(absorb_m.group(1))}% Absorption"))

    # racialBonus{Percent,Absolute}{Damage,Defense} + racialBonusRace --
    # "+10% Damage to Chthonics" / "6% Less Damage from Beastkin". The value
    # and the race it applies to live in two separate fields, so this can't
    # be a plain MISC_FIELD_MAP entry (user-flagged via "Potent Manticore
    # Venom", whose whole "+10% Damage to Chthonics" line was missing).
    # Labels confirmed via tags_ui.txt:
    #   RacialBonusPercentDamage={%+.0f0}% {^E}Damage to {%s1}
    #   RacialBonusPercentDefense={%.0f0}% {^E}Less Damage from {%s1}
    #   RacialBonusAbsoluteDamage={%+.0f0} {^E}Damage to {%s1}
    #   RacialBonusAbsoluteDefense={%.0f0} {^E}Less Damage from {%s1}
    # The race name uses the PLURAL tag (tagRace004P="Chthonics", not
    # tagRace004="Chthonic") -- confirmed against the pasted real tooltip.
    # racialBonusRace can be a `;`-separated list, and a few records use a
    # literal race name ("Aetherial") instead of a RaceNNN token, so fall
    # back to the raw value when the tag lookup misses.
    race_m = re.search(r'^racialBonusRace=(\S+)', txt, re.M)
    if race_m:
        races = [r for r in race_m.group(1).split(';') if r.strip()]
        race_label = ', '.join(
            CREATURE_TAGS.get(f'tag{r.strip()}P') or CREATURE_TAGS.get(f'tag{r.strip()}') or r.strip()
            for r in races)
        for rfield, tmpl, pct in [
            ('racialBonusPercentDamage', '+{v}{p} Damage to {r}', True),
            ('racialBonusAbsoluteDamage', '+{v}{p} Damage to {r}', False),
            ('racialBonusPercentDefense', '{v}{p} Less Damage from {r}', True),
            ('racialBonusAbsoluteDefense', '{v}{p} Less Damage from {r}', False),
        ]:
            rv_m = re.search(rf'^{rfield}=([\d.]+)', txt, re.M)
            if rv_m:
                seen_lines.append((rfield, tmpl.format(
                    v=_fmt_num(rv_m.group(1)), p='%' if pct else '', r=race_label)))

    # offensiveSlow{X}Min + DurationMin combine into ONE debuff sentence.
    # These appear on plain Augment/Component records too, not just inside
    # skill-modifier payloads, and process_stats() had no combined-sentence
    # handling at all -- so each affected item lost its whole debuff line
    # ("Nature's Harvest", "Deathchill Bolts", "Arcane Spark", "Kymon's Will",
    # the last with no "Slow" in its field name).
    # Labels confirmed via tags_ui.txt: DamageTotalDamageReductionPercent =
    # "Reduced target's Damage", DamageDurationRunSpeed = "Slower target
    # Movement", DamageDurationManaLeach = "Energy Leech".
    for field_stub, label_tpl, is_pct in [
        ('DefensiveAbility', "Reduced target's Defensive Ability", False),
        ('RunSpeed', 'Slower target Movement', True),
        ('ManaLeach', 'Energy Leech', False),
        ('TotalDamageReductionPercent', "Reduced target's Damage", True),
        # Resistance Reduction reads "28 Reduced target's Resistances for 8
        # Seconds" in the real tooltip, not a value line plus a Duration line.
        # Its MISC_FIELD_MAP entries above are suppressed when both halves are
        # present (see the skip below) -- they still carry the value-only case,
        # e.g. a permanent RR debuff with no duration field at all.
        ('TotalResistanceReductionAbsolute', "Reduced target's Resistances", False),
        ('TotalResistanceReductionPercent', "Reduced target's Resistances", True),
    ]:
        for prefix in ('offensiveSlow', 'offensive'):
            val_m = re.search(rf'^{prefix}{field_stub}Min=([\d.]+)', txt, re.M)
            if val_m:
                break
        else:
            continue
        dur_m = re.search(rf'^{prefix}{field_stub}DurationMin=([\d.]+)', txt, re.M)
        line = f"{_fmt_num(val_m.group(1))}{'%' if is_pct else ''} {label_tpl}"
        if dur_m:
            line += f' for {_fmt_num(dur_m.group(1))} Seconds'
        seen_lines.append((f'{prefix}{field_stub}Min', line))

    # DoT "value" + "duration" fields combine into ONE "{total} {label} over
    # {duration} Seconds" line in the real tooltip (total = value * duration),
    # not two separate "+N dmg" / "+N Duration" lines -- confirmed via
    # Hypporaven Plumage's "Winds of Asterkarn" skill-modifier payload
    # (offensiveSlowLifeMin=160, offensiveSlowLifeDurationMin=2 -> pasted
    # "320 Vitality Decay Damage over 2 Seconds", 160*2=320 exactly) and its
    # "Vire's Might" modifier (220*2=440, also exact) -- two-for-two with no
    # rounding needed. Scanned up front so the main loop below can emit one
    # combined line per pair instead of the previous two separate ones. Only
    # {prefix}Slow{kind}Min/Max + DurationMin trigger this -- DurationModifier
    # is a different field (a % duration INCREASE bonus, not the modifier's
    # own base duration) and stays its own separate line as before.
    dot_combo_line = {}
    for cm in re.finditer(r'^(offensive|defensive|retaliation)Slow([A-Za-z]+?)Min=(-?[\d.]+)', txt, re.M):
        c_prefix, c_kind, c_val = cm.groups()
        if c_kind not in DAMAGE_TYPES:
            continue
        dur_m = re.search(rf'^{c_prefix}Slow{c_kind}DurationMin=([\d.]+)', txt, re.M)
        if not dur_m:
            continue
        dur = float(dur_m.group(1))
        total = _fmt_num(str(float(c_val) * dur))
        max_m = re.search(rf'^{c_prefix}Slow{c_kind}Max=(-?[\d.]+)', txt, re.M)
        if max_m:
            total = f"{total}–{_fmt_num(str(float(max_m.group(1)) * dur))}"
        sign = '' if c_val.startswith('-') else '+'
        dur_str = _fmt_num(dur_m.group(1))
        dot_combo_line[(c_prefix, c_kind)] = (
            f"{sign}{total} {_type_dot_label(c_kind)} over {dur_str} "
            f"Second{'' if dur_str == '1' else 's'}")

    # Pass 2: {offensive,defensive,retaliation}[Slow]{Type}[Min|Max|Modifier|
    # DurationMin|DurationModifier] fields for the standard damage/resist types.
    handled_minmax = set()
    combo_emitted = set()
    for m in TYPE_FIELD_RE.finditer(txt):
        prefix, slow, kind, suffix, val = m.groups()
        if kind not in DAMAGE_TYPES:
            continue
        field = m.group(0).split('=')[0]
        combo_key = (prefix, kind)
        if slow and suffix in ('Min', 'Max', 'DurationMin') and combo_key in dot_combo_line:
            if combo_key in combo_emitted:
                continue
            combo_emitted.add(combo_key)
            seen_lines.append((field, dot_combo_line[combo_key]))
            continue
        if suffix in ('Min', 'Max'):
            group_key = (prefix, slow, kind, suffix and 'MinMax')
            if group_key in handled_minmax:
                continue
            handled_minmax.add(group_key)
            minv = re.search(rf'^{re.escape(prefix)}{"Slow" if slow else ""}{kind}Min=(-?[\d.]+)', txt, re.M)
            maxv = re.search(rf'^{re.escape(prefix)}{"Slow" if slow else ""}{kind}Max=(-?[\d.]+)', txt, re.M)
            if not minv:
                continue
            num = _fmt_num(minv.group(1))
            if maxv:
                num = f"{num}–{_fmt_num(maxv.group(1))}"
            sign = '' if num.startswith('-') else '+'
        else:
            sign = '' if val.startswith('-') else '+'
            num = _fmt_num(val)

        if prefix == 'defensive' and suffix is None:
            # Flat resist fields ARE percentages in-game -- confirmed via
            # tags_ui.txt's own format strings for every resist type checked
            # (e.g. `DefenseChaos={%.0f0}% {^E}Chaos Resistance`,
            # `DefenseFire={%.0f0}% {^E}Fire Resistance`, same `%` for Cold/
            # Aether/Bleeding/Life/Pierce/Poison/Freeze/Stun) -- user-flagged
            # via "Ascendant Source": pasted "24/36% Chaos Resistance" vs our
            # "+30 Chaos Resist" with no `%` at all. This was wrong for every
            # flat resist line in the whole catalogue, not just this field.
            label = _resist_label(kind)
            pct = True
        elif suffix in ('DurationMin', 'DurationModifier'):
            label = _dot_duration_label(kind) if slow else f'{kind} Duration'
            pct = suffix == 'DurationModifier'
        elif slow:
            label = _type_dot_label(kind)
            pct = suffix == 'Modifier'
        else:
            label = _type_dmg_label(kind)
            pct = suffix == 'Modifier'
            if prefix == 'retaliation':
                label = label.replace(' dmg', ' Retaliation')

        seen_lines.append((field, f"{sign}{num}{'%' if pct else ''} {label}"))

    return seen_lines


# ------------------------------------------------------------------- pets ---
# tagCharStatsPet* confirms the field-name-to-label mapping for the linked
# petbonus.tpl file's fields (same raw field names as normal stats, but the
# WHOLE file means "applies to your pet", not the player).
PET_FIELD_MAP = {
    'characterOffensiveAbilityModifier': ('Offensive Ability', True),
    'characterDefensiveAbilityModifier': ('Defensive Ability', True),
    'characterAttackSpeedModifier': ('Attack Speed', True),
    # "Health," not "Life" -- tagCharStatsPetHealth's own display text is
    # "Life", but the user's pasted real item tooltip for "Bysmiel-Sect
    # Legguards"' pet bonus showed "+5/+7% Health" instead, and this exact
    # field is ALSO already labeled "Health" for the base-item (non-pet)
    # context in MISC_FIELD_MAP above -- keeping the two consistent, and
    # trusting the pasted floating-tooltip text over the shorter
    # character-sheet tag where they disagree (same kind of split as the
    # Entrapment/Trap naming above).
    'characterLifeModifier': ('Health', True),
    'characterTotalSpeedModifier': ('Total Speed', True),
    # "All Damage" (not just "Damage") -- confirmed via tags_ui.txt:
    # `tagDamageModifierTotalDamage={%+.0f0}% {^E}to All Damage` (the
    # game's own text also prepends "to", but every other MISC_FIELD_MAP/
    # PET_FIELD_MAP label uses the bare-label + generic sign/percent
    # convention with no "to", so this only changes the label itself, not
    # the surrounding sentence structure, to stay consistent with every
    # other stat line here).
    'offensiveTotalDamageModifier': ('All Damage', True),
    'defensiveProtectionModifier': ('Armor', True),
    'offensiveCritDamageModifier': ('Critical Damage', True),
    # Same fix as MISC_FIELD_MAP's resist entries above -- these are
    # percentages in-game too (same raw field names, same mechanic, just
    # applied to the pet instead of the player).
    'defensiveAether': ('Aether Resist', True),
    'defensiveChaos': ('Chaos Resist', True),
    'defensivePoison': ('Poison/Acid Resist', True),
    'defensiveBleeding': ('Bleeding Resist', True),
    'defensivePierce': ('Pierce Resist', True),
    'defensiveLife': ('Vitality Resist', True),
    'defensiveFreeze': ('Freeze Resist', True),
    'defensiveStun': ('Stun Resist', True),
    'defensiveElementalResistance': ('Elemental Resist', True),
    'defensiveTotalSpeedResistance': ('Slow Resist', True),
    # Same field/fix as MISC_FIELD_MAP's 'defensiveTrap' above -- user-
    # flagged via "Bysmiel-Sect Legguards"' own petBonusName file, which
    # carries defensiveTrap=40 in addition to (separately from) the base
    # item's own defensiveTrap=40 -- both were silently dropped before.
    'defensiveTrap': ('Entrapment Resist', True),
    'offensiveSlowBleedingMin': ('Bleeding dmg', False),
    'offensiveSlowBleedingDurationMin': ('Bleed Duration', False),
    'offensiveElementalMin': ('Elemental dmg', False),
    'offensiveChaosMin': ('Chaos dmg', False),
    'offensiveChaosModifier': ('Chaos dmg', True),
    'offensiveAetherModifier': ('Aether dmg', True),
    'offensiveSlowPoisonModifier': ('Poison dmg', True),
    # PET_FIELD_MAP only covers whichever field/type combos some earlier
    # item happened to need -- unlike process_stats()'s generic DAMAGE_TYPES
    # loop, this map has no fallback, so any untried combo silently vanishes.
    # These two -- user-flagged via "Mortality" (relic)'s granted skill's
    # own nested pet bonus, which carries offensiveLifeMin=33/
    # offensiveLifeModifier=125 alongside the already-covered CritDamage/
    # TotalDamage fields -- were missing outright.
    'offensiveLifeMin': ('Vitality dmg', False),
    'offensiveLifeModifier': ('Vitality dmg', True),
}


PET_PREFIX = 'Pet: '


def apply_skill_level(txt, level_idx):
    """Collapse a skill record's per-level arrays (`characterLifeModifier=8; 20`)
    to the single value at `level_idx`, so every downstream formatter can keep
    reading one value per field and needs no level parameter of its own.

    The level comes from the GRANTING record's `itemSkillLevelEq`, not from the
    skill: Mogdrogen's Tranquility and Mogdrogen's Peace grant the SAME buff
    record and differ only by Eq=1 vs Eq=2, which is what makes the mythical set
    read +20% Health where the base set reads +8%. Items grant at Eq=1, so index
    0 stays the default and their output is unchanged -- which matters, because
    "take the first entry" was verified against a real tooltip (Harbinger's
    Dominator Blade) and must not silently become "take the last".
    """
    out = []
    for line in txt.splitlines():
        m = re.match(r'^([A-Za-z0-9]+)=(-?[\d.]+(?:\s*;\s*-?[\d.]+)+)\s*$', line)
        if m:
            vals = [v.strip() for v in m.group(2).split(';') if v.strip()]
            out.append(f'{m.group(1)}={vals[min(level_idx, len(vals) - 1)]}')
        else:
            out.append(line)
    return '\n'.join(out) + '\n'


def skill_level_index(txt):
    """`itemSkillLevelEq` on the granting record, as a 0-based index."""
    m = re.search(r'^itemSkillLevelEq=(\d+)', txt, re.M)
    return max(int(m.group(1)) - 1, 0) if m else 0


def supplement_shared_stats(txt, prefix, existing):
    """Lines for the fields `format_skill_modifier_stats()` has no opinion on,
    formatted by the shared engine and appended to `existing` in place.

    Probe FIELD BY FIELD (the two formatters phrase the same stat differently,
    so a string-level union prints it twice in two voices) but then run
    process_stats() ONCE over all the leftover fields TOGETHER -- its
    combined-sentence passes need both halves of a pair in the same text, or
    "28 Reduced target's Resistances for 8 Seconds" comes out as a value line
    plus a duration line, which is what the game does not say.
    """
    fields = [(f, v) for f, v in re.findall(r'^([A-Za-z0-9]+)=(-?[\d.]+)', txt, re.M)
              if not format_skill_modifier_stats(f'{f}={v}\n', '')]
    if not fields:
        return existing
    residual = '\n'.join(f'{f}={v}' for f, v in fields) + '\n'
    for extra in process_stats(residual):
        line = f'{prefix}{extra}'
        if line not in existing:
            existing.append(line)
    return existing


def resolve_pet_bonus(txt, level_idx=0):
    m = re.search(r'^petBonusName=(\S+)', txt, re.M)
    if not m:
        return []
    link_txt = read_rel(m.group(1))
    if link_txt is None:
        return []
    link_txt = apply_skill_level(link_txt, level_idx)
    # PET_FIELD_MAP is a small hand-built map; process_stats() knows the whole
    # stat vocabulary. Ask the shared engine FIELD BY FIELD and fall back to the
    # pet map only where it has nothing -- a wholesale swap would add 287 lines
    # across 199 pet records but silently reword 29 existing ones (flat DoT
    # damage renders as "+6 Bleeding dmg over 3 Seconds" there, "+6 Bleeding dmg"
    # here), and a phrasing change is not a fix.
    lines = []
    for field, val in re.findall(r'^([A-Za-z0-9]+)=(-?[\d.]+)', link_txt, re.M):
        shared = process_stats(f'{field}={val}\n')
        if shared:
            lines += [f'{PET_PREFIX}{l}' for l in shared]
        elif field in PET_FIELD_MAP:
            label, is_pct = PET_FIELD_MAP[field]
            sign = '' if val.startswith('-') else '+'
            lines.append(f"{PET_PREFIX}{sign}{_fmt_num(val)}{'%' if is_pct else ''} {label}")
    return lines


def resolve_item_skill(txt):
    """itemSkillName = a skill GRANTED to the player (usually an on-attack
    proc, e.g. 'Crafted' guns granting Fireball). Returns a list of display
    lines (empty if none): "Grants: X" plus that skill's OWN stat payload
    (duration/cooldown/damage/etc, via format_skill_modifier_stats() -- that
    function is purely field-driven, not gated on Class=Skill_Modifier, so
    it works fine here even though a granted skill is usually a different
    Class like Skill_BuffSelfDuration) and its own nested petBonusName, if
    it has one. User-flagged via "Mortality" (relic): its granted "Mortality"
    proc (itemskillsgdx1/relics/mortality.dbr) carries a full stat block --
    skillActiveDuration=8, skillCooldownTime=12, offensiveLifeMin=33,
    offensiveLifeModifier=125, offensiveAetherModifier=125,
    offensiveSlowLifeModifier=125, offensiveCritDamageModifier=8, PLUS its
    own petBonusName (mortality_buff_petbonus.dbr) -- previously only
    "Grants: Mortality" showed at all, the entire stat block silently
    dropped. This was a real gap for every item with a granted proc skill in
    both catalogues, not just this one. modifiedSkillName (modifies an
    existing class skill) is still NOT resolved here -- those target files
    don't carry a skillDisplayName tag (they're raw class-skill records), so
    there's no clean name to show."""
    m = re.search(r'^itemSkillName=(\S+)', txt, re.M)
    if not m:
        return []
    skill_txt = read_rel(m.group(1))
    if skill_txt is None:
        return []
    level_idx = skill_level_index(txt)
    skill_txt = apply_skill_level(skill_txt, level_idx)
    disp_m = re.search(r'^skillDisplayName=(\S+)', skill_txt, re.M)
    if not disp_m:
        # A Skill_BuffRadiusToggled / buff-wrapper record carries no name of its
        # own: the display name, description, stats and pet bonus all live one
        # `buffSkillName` hop away. Without this hop the entire granted-skill
        # block vanishes -- 19 of the 121 sets that grant a skill, including both
        # Mogdrogen sets, showed nothing at all. ONE hop only, deliberately: the
        # chain can continue, and each further hop is a different record family
        # with its own display rules.
        buff_m = re.search(r'^buffSkillName=(\S+)', skill_txt, re.M)
        buff_txt = read_rel(buff_m.group(1)) if buff_m else None
        if buff_txt is None:
            return []
        skill_txt = apply_skill_level(buff_txt, level_idx)
        disp_m = re.search(r'^skillDisplayName=(\S+)', skill_txt, re.M)
        if not disp_m:
            return []
    name = clean_name(SKILL_TAGS.get(disp_m.group(1), ''))
    if not name:
        return []
    lines = [f'Grants: {name}']
    # The skill's own prose description (skillBaseDescription -> a tag in the
    # SKILLS tag family), e.g. Leap's "Leap through the air to land towards
    # the target point, sending a shockwave through the ground upon landing."
    # The real in-game tooltip prints this under the skill's name, above its
    # stat lines, so it goes first here (user-flagged: "add skill
    # descriptions if skill is granted"). Rendered as an ordinary
    # "{name}: ..." line so it groups into that skill's box like every other
    # line for the same skill; the card CSS italicises it via .skill-desc.
    desc_m = re.search(r'^skillBaseDescription=(\S+)', skill_txt, re.M)
    if desc_m:
        desc = clean_name(SKILL_TAGS.get(desc_m.group(1), ''))
        if desc:
            lines.append(f'{name}: {desc}')
    chance_line = resolve_skill_trigger_chance(txt, f'{name}: ')
    if chance_line:
        lines.append(chance_line)
    # format_skill_modifier_stats() knows the SKILL-shaped fields (duration,
    # radius, cooldown, refresh, conversions) that process_stats() has no concept
    # of; process_stats() knows the whole ordinary stat vocabulary that the
    # skill formatter only partially reimplements. Neither is a superset, so take
    # both and drop exact repeats -- "150 Energy Reserved" and "+3% Max Aether
    # Resist" on Mogdrogen's Tranquility exist only in the second.
    skill_lines = supplement_shared_stats(
        skill_txt, f'{name}: ', format_skill_modifier_stats(skill_txt, f'{name}: '))
    lines += skill_lines
    lines += [f'{name}: {l}' for l in resolve_pet_bonus(skill_txt, level_idx)]
    return lines


def read_rel(relpath):
    """A record's text by relative path, or None. THE one record source here.

    gd-lib opens `.extracted/<relpath>`; this renders the same bytes from the
    .arz. See archive/records.py for why the two are the same string and not
    merely the same data.
    """
    return _records.text(relpath)


def skill_display_name(txt):
    """Resolve a skill record's own display name, following ONE hop through
    petSkillName if the record is a SkillSecondary_PetModifier wrapper
    rather than the skill itself (e.g. an augmentSkillName target like
    summon_raven4_petmodifier.dbr has no skillDisplayName of its own --
    its petSkillName points at petskill_raven_stormstrike1.dbr, which
    does), or through buffSkillName if it's a Skill_AttackBuff/
    SkillSecondary_BuffSelfDuration wrapper instead (user-flagged via
    "Gargoyle Visage"/"Bloodbound Helm"/"Frostplume Mantle": augmentSkillName
    targets like pox1.dbr/cadence3.dbr/illomen1.dbr have no skillDisplayName
    OR petSkillName of their own -- their buffSkillName points at
    pox1_buff.dbr/cadence3_buff.dbr/illomen1_buff.dbr, which do -- so "+3 to
    Bloody Pox"/"+3 to Deadly Momentum"/"+3 to Ill Omen" were silently
    dropped entirely, along with the whole modifierSkillName section sharing
    that same augment target for the two that had one)."""
    if txt is None:
        return None
    disp_m = re.search(r'^skillDisplayName=(\S+)', txt, re.M)
    if disp_m:
        return clean_name(SKILL_TAGS.get(disp_m.group(1), '')) or None
    pet_m = re.search(r'^petSkillName=(\S+)', txt, re.M)
    if pet_m:
        return skill_display_name(read_rel(pet_m.group(1)))
    buff_m = re.search(r'^buffSkillName=(\S+)', txt, re.M)
    if buff_m:
        return skill_display_name(read_rel(buff_m.group(1)))
    return None


def resolve_augment_skills(txt):
    """augmentSkillName{1-4} + augmentSkillLevel{1-4} = "+N to <Skill>" skill
    point bonuses (confirmed against Harbinger's Dominator Blade's real
    in-game tooltip: "+3 to Lightning Strike" / "+3 to Undead Legion").
    Previously assumed to be a non-displayed internal field and skipped
    entirely -- it's a real, commonly-shown effect on MI weapons/jewelry."""
    lines = []
    for i in range(1, 5):
        name_m = re.search(rf'^augmentSkillName{i}=(\S+)', txt, re.M)
        lvl_m = re.search(rf'^augmentSkillLevel{i}=(\d+)', txt, re.M)
        if not name_m or not lvl_m:
            continue
        name = skill_display_name(read_rel(name_m.group(1)))
        if name:
            lines.append(f'+{lvl_m.group(1)} to {name}')
    lines += resolve_augment_mastery(txt)
    return lines


def resolve_augment_mastery(txt):
    """augmentMasteryName{i}/augmentMasteryLevel{i} = "+N to all skills in
    <Mastery>" -- a completely separate field pair from augmentSkillName/
    augmentSkillLevel above (user-flagged via "Okaloth's Visage": its
    augmentMasteryName1 points at a Skill_Mastery record, MasteryEnumeration=
    SkillClass09, which resolve_augment_skills() never looked for at all, so
    "+1 to all skills in Oathkeeper" was silently absent)."""
    lines = []
    for i in range(1, 5):
        name_m = re.search(rf'^augmentMasteryName{i}=(\S+)', txt, re.M)
        lvl_m = re.search(rf'^augmentMasteryLevel{i}=(\d+)', txt, re.M)
        if not name_m or not lvl_m:
            continue
        mastery_txt = read_rel(name_m.group(1))
        if mastery_txt is None:
            continue
        enum_m = re.search(r'^MasteryEnumeration=(\S+)', mastery_txt, re.M)
        if not enum_m:
            continue
        mastery = MASTERY_NAMES.get(enum_m.group(1))
        if mastery:
            lines.append(f'+{lvl_m.group(1)} to all skills in {mastery}')
    return lines


def augment_all_skills(txt):
    """augmentAllLevel = "+N to All Skills" -- every mastery at once, and a
    field of its own, unrelated to augmentSkillName/augmentMasteryName. 44 gear
    records carry it and nothing rendered it until the mastery filter needed to
    explain why it had matched them."""
    m = re.search(r'^augmentAllLevel=(\d+)', txt, re.M)
    return [f'+{m.group(1)} to All Skills'] if m else []


CONVERT_RE = re.compile(r'^conversionInType(\d*)=(\S+)', re.M)


MOD_STAT_RE = re.compile(r'^offensive(Slow)?([A-Za-z]+?)(Min|Max|Modifier|DurationMin|DurationModifier)=([^\n]+)', re.M)


# Fields format_skill_modifier_stats() otherwise has no way to recognize --
# not damage types, so MOD_STAT_RE/DAMAGE_TYPES can't catch them (user-
# flagged via "Ugdenbog Boltthrower": its "Deadly Momentum" modifier target,
# gun2h_b103_cadence_deadlymomentum.dbr, carries ONLY
# characterAttackSpeedModifier/MaxModifier -- no damage/conversion fields at
# all -- so the whole section rendered as empty and silently vanished,
# indistinguishable from the genuine "cosmetic pet-swap, no payload" case
# the modSpawnObjects fallback below is for). Labels match PET_FIELD_MAP's
# existing conventions for the same field names where they overlap.
MOD_EXTRA_FIELD_MAP = {
    'characterAttackSpeedModifier': ('Attack Speed', True),
    'characterAttackSpeedMaxModifier': ('Max Attack Speed', True),
    'offensiveCritDamageModifier': ('Critical Damage', True),
    'characterLifeModifier': ('Health', True),
    # Flat (non-Modifier-suffixed) Offensive/Defensive Ability inside a
    # modifier payload -- user-flagged via "Basilisk Mark"'s "Blood of
    # Dreeg" (characterOffensiveAbility=40/characterDefensiveAbility=40) and
    # "Anointed Blade"'s "Maiven's Sphere of Protection"
    # (characterDefensiveAbility=55) -- the latter's WHOLE section was
    # missing since this was its only stat field at all.
    'characterOffensiveAbility': ('Offensive Ability', False),
    'characterDefensiveAbility': ('Defensive Ability', False),
    # Same mislabel MISC_FIELD_MAP above had for this
    # exact field at the base-item level -- confirmed "Shield Block Chance"
    # via tags_ui.txt, not "Damage Blocked" (user-flagged via "Aetherthorn
    # Shield"'s "Arcane Will" modifier: "+50% Shield Block Chance").
    'defensiveBlockModifier': ('Shield Block Chance', True),
}


# defensive{Type}=N (flat, no Min/Max/Modifier suffix) inside a
# modifierSkillName payload -- a DEBUFF the proc applies to the target, not
# a player-facing bonus, hence the negative values (user-flagged via
# "Gargoyle Visage": its "Bloody Pox" modifier, head_b207_bloodypox.dbr, is
# ENTIRELY defensiveBleeding=-12/defensiveLife=-12 with no offensive/
# conversion fields at all, so the whole section rendered empty). Labels
# match PET_FIELD_MAP's resist-field conventions.
MOD_DEFENSIVE_FIELD_MAP = {
    'defensiveBleeding': 'Bleeding Resist',
    'defensiveLife': 'Vitality Resist',
    'defensiveAether': 'Aether Resist',
    'defensiveChaos': 'Chaos Resist',
    'defensivePoison': 'Poison/Acid Resist',
    'defensivePierce': 'Pierce Resist',
    'defensiveFreeze': 'Freeze Resist',
    'defensiveStun': 'Stun Resist',
    'defensiveElementalResistance': 'Elemental Resist',
    'defensiveTotalSpeedResistance': 'Slow Resist',
    # A player-facing bonus this time, not a target debuff (positive value) --
    # user-flagged via "Death's Whisper Hood"'s "Resilience" modifier:
    # defensivePhysical=6 -> "+6% Physical Resistance", entirely unhandled
    # before since "Physical" wasn't in this map at all (only in the
    # base-item-level DAMAGE_TYPES generic loop, which format_skill_modifier_
    # stats() doesn't share). Sign still derived from the raw value like
    # every other entry here, so this doubles as the debuff case too.
    'defensivePhysical': 'Physical Resist',
}


def _first_value(raw):
    return _fmt_num(raw.split(';')[0].strip())


def extract_conversions(txt, prefix):
    """conversionInType/conversionOutType/conversionPercentage (and their
    numbered '2'/'3' siblings) -> "{prefix}{pct}% {In} dmg converted to
    {Out} dmg" lines. Shared by format_skill_modifier_stats() and
    resolve_pet_conversions() -- both a modifierSkillName payload and an
    item's own petBonusName file use this exact field trio."""
    lines = []
    for m in CONVERT_RE.finditer(txt):
        suffix, in_type = m.groups()
        if ';' in in_type:
            continue
        out_m = re.search(rf'^conversionOutType{suffix}=(\S+)', txt, re.M)
        pct_m = re.search(rf'^conversionPercentage{suffix}=(\S+)', txt, re.M)
        if not out_m or ';' in out_m.group(1):
            continue
        pct = _first_value(pct_m.group(1)) if pct_m else '100'
        in_label = _type_dmg_label(in_type).replace(' dmg', '')
        out_label = _type_dmg_label(out_m.group(1)).replace(' dmg', '')
        lines.append(f'{prefix}{pct}% {in_label} dmg converted to {out_label} dmg')
    return lines


def resolve_pet_conversions(txt):
    """The item's own petBonusName file can ALSO carry conversionInType/Out/
    Percentage fields (e.g. Harbinger's Void Blade's petBonus: Physical+Life
    -> Chaos at 100% each) that resolve_pet_bonus() doesn't look for (it
    was written for Augments/Components, which never carry conversion
    fields) -- its PET_FIELD_MAP only covers plain stat fields. This adds
    just the conversion lines as a supplement, so both together cover the
    full petBonusName payload without double-counting the stat fields
    resolve_pet_bonus() already handles."""
    m = re.search(r'^petBonusName=(\S+)', txt, re.M)
    if not m:
        return []
    return extract_conversions(read_rel(m.group(1)) or '', PET_PREFIX)


# The trigger vocabulary is NOT written here any more. It lives once, in
# skill_triggers, filled from the game's own tagAutoSkillCondition strings, and
# the stash reads the same module. Two hand-written
# tables used to sit at this spot -- a seven-entry one for granted skills and a
# two-entry one for the refresh/cooldown lines below, whose three gaps printed
# raw field values ("100% Chance on OnKill to reduce cooldown of Leap") on four
# published cards, and whose granted-skill wording differed from the game's on
# 732 item records.
def resolve_skill_trigger_chance(txt, prefix):
    """itemSkillAutoController -> "{prefix}N% Chance on <condition>" line, or None
    if the item has no auto-controller (some granted skills are always-on, or are
    triggered through modifierSkillName instead).

    Deliberately its own "{name}: ..." line rather than folded into the
    "Grants: X" line's text -- the card UI's groupEffects()/effectSkillName()
    (item_browser_template.html) matches a body line's skill box by taking
    everything after "Grants: " verbatim as the lookup key, so appending the
    condition there would change that key and silently break the box grouping for
    every item this touches, not merely fail to show the chance. The stash appends
    instead, because its page reproduces the game's own tooltip; that difference
    is presentation and is why skill_triggers returns a phrase and no more.
    """
    m = re.search(r'^itemSkillAutoController=(\S+)', txt, re.M)
    if not m:
        return None
    ctrl_txt = read_rel(m.group(1))
    if not ctrl_txt:
        return None
    return prefix + st.controller_phrase(ITEM_TAGS, ctrl_txt)


def refresh_trigger_phrase(txt, field):
    """The "N% Chance on <condition>" opening of a refresh/cooldown line.

    `field` is the record's own chance field, because the two families name their
    fields differently and each line already knows which it is reading. There is
    NO fallback: this used to default to "Attack" when the trigger field was
    missing, which is a confident sentence about when an item fires that nothing
    in the data supports.
    """
    fam = field.replace('Chance', '')
    chance = re.search(rf'^{field}=([\d.;\s]+)', txt, re.M)
    trigger = re.search(rf'^{fam}Trigger=(\S+)', txt, re.M)
    if not chance or not trigger:
        return None
    return st.condition_phrase(ITEM_TAGS, trigger.group(1), chance.group(1))


def format_skill_modifier_stats(txt, prefix):
    """Pull displayable stat lines out of a Skill_Modifier/Skill_Passive
    record (the actual payload a modifierSkillName chain resolves to, once
    any petSkillName wrapper hop is followed) -- conversionInType/
    conversionOutType/conversionPercentage pairs, offensive{Type}* fields,
    skillActiveDuration, and refreshDuration* (user-flagged via "Sunherald's
    Claymore": its Blast Shield modifier -- sword2h_b209_blastshield.dbr --
    carries skillActiveDuration=2 and refreshDurationChance/Amount/Max/
    Trigger/Skill fields this function had never handled at all, silently
    dropping "2 Second Duration" and "20% Chance on Attack to refresh
    duration of Blast Shield by 1 Second (Max 9 Seconds)" entirely -- not a
    formatting bug, a straight-up missing field family). Semicolon-joined
    values (per-internal-level scaling, e.g. "50; 100") take the first
    entry -- verified against Harbinger's Dominator Blade's real tooltip
    ("50 Chaos Damage" for a field stored as offensiveChaosMin=50; 100).
    Multi-type conversion lists (e.g.
    conversionInType=Physical;Pierce;Elemental;...) are generic scaling
    metadata, not a real "converts all these" effect, so are skipped rather
    than rendered as garbage."""
    if txt is None:
        return []
    lines = []  # duration first, then numeric offensive lines, conversions,
                # then refresh-chance last -- matches the real tooltip order
                # verified against Sunherald's Claymore's Blast Shield: "2
                # Second Duration" / "120 Fire Damage" / "20% Chance on
                # Attack to refresh duration...".
    # skillManaCost -- "N Energy Cost" (confirmed via tags_ui.txt's
    # `ManaCost={^E}Energy Cost`). User-flagged via the Rune "Emblem of the
    # Leaping Mantis", whose granted Leap skill shows "33 Energy Cost" in the
    # real tooltip. No leading "+" -- it's a cost, not a bonus.
    mana_m = re.search(r'^skillManaCost=([\d.]+)', txt, re.M)
    if mana_m:
        lines.append(f'{prefix}{_first_value(mana_m.group(1))} Energy Cost')
    dur_m = re.search(r'^skillActiveDuration=([\d.]+)', txt, re.M)
    if dur_m:
        n = _first_value(dur_m.group(1))
        lines.append(f'{prefix}{n} Second Duration')
    # skillCooldownTime -- "N Second Skill Recharge" (can legitimately be
    # negative, e.g. Kymon's Badge's Grenado modifier: skillCooldownTime=
    # -0.5 -> "-0.5 Second Skill Recharge" -- the raw signed value prints
    # as-is, no forced "+"/"-" convention, unlike almost every other stat
    # here). Different field from skillActiveDuration -- confirmed via
    # "Aetherthorn Shield"'s Grasping Vines modifier (skillCooldownTime=1 ->
    # "1 Second Skill Recharge", no "+").
    cd_time_m = re.search(r'^skillCooldownTime=(-?[\d.]+)', txt, re.M)
    if cd_time_m:
        lines.append(f'{prefix}{_first_value(cd_time_m.group(1))} Second Skill Recharge')
    # skillLifePercent -- "N% Health Restored" (user-flagged via "Bargoll's
    # Core"'s "Call of the Grave" modifier: skillLifePercent=12).
    life_pct_m = re.search(r'^skillLifePercent=([\d.]+)', txt, re.M)
    if life_pct_m:
        lines.append(f'{prefix}{_first_value(life_pct_m.group(1))}% Health Restored')
    # skillTargetRadius -- "N Meter Target Area" (a range/radius change on
    # the modified skill, can be negative -- user-flagged via "Coerced
    # Wraith"'s "Devastation" modifier: skillTargetRadius=-2). Raw signed
    # value prints as-is, matching skillCooldownTime's convention above.
    radius_m = re.search(r'^skillTargetRadius=(-?[\d.]+)', txt, re.M)
    if radius_m:
        lines.append(f'{prefix}{_first_value(radius_m.group(1))} Meter Target Area')
    # waveDistance -- "N Meter Range" (tags_ui.txt shares one format string,
    # `SkillDistanceFormat={%.1f0 {^E}Meter %s1}`, between this and
    # skillTargetRadius below -- the trailing %s1 is what differs, "Range"
    # vs "Target Area"). Missed twice before adding it: "Death's Whisper
    # Hood"'s Bone Harvest modifier (waveDistance=2 -> "2 Meter Range") and
    # the Leap rune (waveDistance=16 -> "16 Meter Range").
    wave_m = re.search(r'^waveDistance=([\d.]+)', txt, re.M)
    if wave_m:
        lines.append(f'{prefix}{_first_value(wave_m.group(1))} Meter Range')
    # characterDefensiveBlockRecoveryReduction -- see the module-level
    # comment above MOD_EXTRA_FIELD_MAP for why this needs its own branch
    # instead of living in that map (always-negative display regardless of
    # the raw field's sign).
    block_recovery_m = re.search(r'^characterDefensiveBlockRecoveryReduction=([\d.]+)', txt, re.M)
    if block_recovery_m:
        lines.append(f'{prefix}-{_first_value(block_recovery_m.group(1))}% Shield Recovery Time')
    # skillChanceWeight/projectileLaunchNumber -- "which of several possible
    # modifier targets fires this time" / "hits N times" mechanics, shown
    # up front in the real tooltip alongside skillActiveDuration (verified
    # against Ugdenbog Boltthrower's "Storm Spread" section: "20% Chance to
    # be Used" / "2 Projectile(s)" both precede its damage lines).
    chance_m = re.search(r'^skillChanceWeight=([\d.]+)', txt, re.M)
    if chance_m:
        lines.append(f'{prefix}{_first_value(chance_m.group(1))}% Chance to be Used')
    proj_m = re.search(r'^projectileLaunchNumber=(\d+)', txt, re.M)
    if proj_m and proj_m.group(1) != '1':
        lines.append(f'{prefix}{proj_m.group(1)} Projectile(s)')
    # offensiveSlow{Type}Min + offensiveSlow{Type}DurationMin combine into ONE
    # "{total} {label} over {duration} Seconds" line in the real tooltip
    # (total = value * duration), not two separate "{N} dmg" / "+{N}
    # Duration" lines -- user-flagged via "Hypporaven Plumage"'s "Winds of
    # Asterkarn" modifier (offensiveSlowLifeMin=160, ...DurationMin=2 ->
    # pasted "320 Vitality Decay Damage over 2 Seconds", 160*2=320 exactly)
    # and its "Vire's Might" modifier (220*2=440, also exact) -- two-for-two,
    # no rounding needed. Same fix as process_stats() above,
    # mirrored here for the skill-modifier level. DurationModifier (a %
    # duration-increase bonus, different field) is untouched.
    dot_combo_line = {}
    for cm in re.finditer(r'^offensiveSlow([A-Za-z]+?)Min=([^\n]+)', txt, re.M):
        c_kind, c_val_raw = cm.groups()
        if c_kind not in DAMAGE_TYPES or ';' in c_val_raw:
            continue
        dur_m = re.search(rf'^offensiveSlow{c_kind}DurationMin=([\d.]+)', txt, re.M)
        if not dur_m:
            continue
        dur = float(dur_m.group(1))
        total = _fmt_num(str(float(_first_value(c_val_raw)) * dur))
        max_m = re.search(rf'^offensiveSlow{c_kind}Max=([^\n]+)', txt, re.M)
        if max_m and ';' not in max_m.group(1):
            total = f"{total}–{_fmt_num(str(float(_first_value(max_m.group(1))) * dur))}"
        dur_str = _first_value(dur_m.group(1))
        dot_combo_line[c_kind] = (
            f"{total} {_type_dot_label(c_kind)} over {dur_str} "
            f"Second{'' if dur_str == '1' else 's'}")

    # numeric offensive lines next, conversions after -- matches real
    # tooltip order (verified: "50 Chaos Damage" / "+100% Chaos Damage"
    # precede their "X% converted to Y" siblings).
    handled_minmax = set()
    combo_emitted = set()
    for m in MOD_STAT_RE.finditer(txt):
        slow, kind, suffix, val = m.groups()
        if kind not in DAMAGE_TYPES:
            continue
        if slow and suffix in ('Min', 'Max', 'DurationMin') and kind in dot_combo_line:
            if kind in combo_emitted:
                continue
            combo_emitted.add(kind)
            lines.append(f'{prefix}{dot_combo_line[kind]}')
            continue
        if suffix in ('Min', 'Max'):
            key = (slow, kind)
            if key in handled_minmax:
                continue
            handled_minmax.add(key)
            minv = re.search(rf'^offensive{"Slow" if slow else ""}{kind}Min=([^\n]+)', txt, re.M)
            maxv = re.search(rf'^offensive{"Slow" if slow else ""}{kind}Max=([^\n]+)', txt, re.M)
            if not minv:
                continue
            num = _first_value(minv.group(1))
            if maxv:
                num = f"{num}–{_first_value(maxv.group(1))}"
            label = _type_dot_label(kind) if slow else _type_dmg_label(kind)
            lines.append(f'{prefix}{num} {label}')
        elif suffix in ('DurationMin', 'DurationModifier'):
            # e.g. offensiveSlowBleedingDurationMin=3 -- a flat seconds add,
            # not paired with a Max counterpart (unlike plain Min/Max above,
            # this field family never has one in this dataset). Mirrors
            # TYPE_FIELD_RE's own handling above of the same
            # suffix pair (DurationMin = flat, DurationModifier = percent).
            num = _first_value(val)
            label = _dot_duration_label(kind) if slow else f'{kind} Duration'
            pct = suffix == 'DurationModifier'
            lines.append(f'{prefix}+{num}{"%" if pct else ""} {label}')
        else:
            num = _first_value(val)
            label = (_type_dot_label(kind) if slow else _type_dmg_label(kind))
            lines.append(f'{prefix}+{num}% {label}')
    for field, val in re.findall(r'^([A-Za-z0-9]+)=(-?[\d.]+)', txt, re.M):
        if field in MOD_EXTRA_FIELD_MAP:
            label, is_pct = MOD_EXTRA_FIELD_MAP[field]
            sign = '' if val.startswith('-') else '+'
            lines.append(f"{prefix}{sign}{_first_value(val)}{'%' if is_pct else ''} {label}")
        elif field in MOD_DEFENSIVE_FIELD_MAP:
            sign = '' if val.startswith('-') else '+'
            lines.append(f"{prefix}{sign}{_first_value(val)}% {MOD_DEFENSIVE_FIELD_MAP[field]}")
        elif field == 'offensiveLifeLeechMin':
            # Same "no leading +" convention as the base-item-level version
            # in process_stats() above -- verified against
            # both Gargoyle Visage's Feral Hunger modifier and Bloodbound
            # Helm's Deadly Momentum modifier.
            lines.append(f'{prefix}{_first_value(val)}% of Attack Damage converted to Health')
        elif field == 'weaponDamagePct':
            # e.g. Bloodbound Helm's Cadence modifier, weaponDamagePct=30 ->
            # "30% Weapon Damage" -- also no leading "+" in the real tooltip.
            lines.append(f'{prefix}{_first_value(val)}% Weapon Damage')
        elif field == 'retaliationDamagePct':
            # e.g. Okaloth's Visage's Sigil of Consumption/Smite modifiers ->
            # "30% of Retaliation Damage added to Attack" -- no leading "+".
            lines.append(f'{prefix}{_first_value(val)}% of Retaliation Damage added to Attack')
    # petBurstSpawn/petLimit -- a modifier that grants MORE of an existing
    # summon rather than a stat bonus to it (user-flagged via "Diremane
    # Trophy"'s Blade Spirit modifier, focus_b304_bladespirit.dbr: just
    # petBurstSpawn=1/petLimit=1, no other fields at all, so the section
    # rendered fully empty). Originally fired only when BOTH fields were
    # present together, on the assumption "N Summon Limit" always accompanies
    # "+N Summon" -- wrong: Awakened Fiendbinder's Hood's Raise Skeletons
    # modifier (head_c210_raiseskeletons.dbr) is petLimit=1 alone, no
    # petBurstSpawn at all (real tooltip: "1 Summon Limit", no "+1 Summon"
    # line), which the AND-gate silently dropped -- user-flagged via a
    # pasted GrimTools diff. Each field now fires independently.
    burst_m = re.search(r'^petBurstSpawn=(\d+)', txt, re.M)
    limit_m = re.search(r'^petLimit=(\d+)', txt, re.M)
    if burst_m:
        lines.append(f'{prefix}+{burst_m.group(1)} Summon')
    if limit_m:
        lines.append(f'{prefix}{limit_m.group(1)} Summon Limit')
    # offensiveStunMin -- "Stun target for N Seconds". tags_ui.txt's
    # `DamageStun={^E}Stun target{%t0}` carries the duration in its {%t0}
    # time suffix rather than a leading number, hence the sentence shape
    # rather than the usual "+N Label" (user-flagged via the Leap rune's
    # "Stun target for 0.5 Seconds").
    stun_m = re.search(r'^offensiveStunMin=([\d.]+)', txt, re.M)
    if stun_m:
        n = _first_value(stun_m.group(1))
        lines.append(f'{prefix}Stun target for {n} Second{"" if n == "1" else "s"}')
    # offensiveSlowDefensiveAbility{Min,DurationMin} -- a debuff that reduces
    # the TARGET's Defensive Ability, shown as one combined sentence rather
    # than a separate duration+value line like every other DoT (user-flagged
    # via "Diremane Trophy"'s War Cry modifier: "150 Reduced target's
    # Defensive Ability for 5 Seconds"). "DefensiveAbility" isn't a
    # DAMAGE_TYPES member so the main MOD_STAT_RE loop above never sees it.
    da_val_m = re.search(r'^offensiveSlowDefensiveAbilityMin=([\d.]+)', txt, re.M)
    if da_val_m:
        da_dur_m = re.search(r'^offensiveSlowDefensiveAbilityDurationMin=([\d.]+)', txt, re.M)
        line = f"{prefix}{_first_value(da_val_m.group(1))} Reduced target's Defensive Ability"
        if da_dur_m:
            line += f' for {_first_value(da_dur_m.group(1))} Seconds'
        lines.append(line)
    # offensiveTotalDamageReductionPercent{Min,DurationMin} -- a debuff that
    # reduces the TARGET's outgoing damage, same combined-sentence shape as
    # the DefensiveAbility case above (user-flagged via "Death's Whisper
    # Hood"'s "Winds of Asterkarn" modifier: "20% Reduced target's Damage for
    # 2 Seconds"). Confirmed label via tags_ui.txt:
    # `DamageTotalDamageReductionPercent=% {^E}Reduced target's Damage`.
    # "TotalDamageReductionPercent" isn't a DAMAGE_TYPES member, but MOD_STAT_RE
    # still matches it as kind="TotalDamageReductionPercent"/suffix="Min" (the
    # regex only requires the field to END in "Min"), so the main loop's
    # `kind not in DAMAGE_TYPES: continue` silently dropped it before this.
    dmg_red_m = re.search(r'^offensiveTotalDamageReductionPercentMin=([\d.]+)', txt, re.M)
    if dmg_red_m:
        dmg_red_dur_m = re.search(r'^offensiveTotalDamageReductionPercentDurationMin=([\d.]+)', txt, re.M)
        line = f"{prefix}{_first_value(dmg_red_m.group(1))}% Reduced target's Damage"
        if dmg_red_dur_m:
            line += f' for {_first_value(dmg_red_dur_m.group(1))} Seconds'
        lines.append(line)
    # cooldownCharges -- "+N Charges" (user-flagged via "Garmir's Horn"'s
    # "Doom Bolt" modifier: cooldownCharges=1). Confirmed via tags_ui.txt:
    # `CooldownChargesMod=+{%d0} {^E}Charges`.
    charges_m = re.search(r'^cooldownCharges=(\d+)', txt, re.M)
    if charges_m:
        lines.append(f'{prefix}+{charges_m.group(1)} Charges')
    # skillComboChargeLevel -- "+N Onslaught Stacks" (user-flagged via
    # "Garmir's Horn"'s "Drain Essence" modifier: skillComboChargeLevel=3).
    # Confirmed via tagsgdx3_ui.txt: `ComboMaxChargeMod=+{%d0} {^E}Onslaught
    # Stacks`. Its sibling skillComboChargeDuration isn't shown -- that tag
    # (`ComboChargeDuration={^E}Onslaught Stack Duration`) has no numeric
    # format placeholder at all, so it's a UI section label elsewhere, not a
    # tooltip stat line (also absent from the pasted reference tooltip).
    combo_m = re.search(r'^skillComboChargeLevel=(\d+)', txt, re.M)
    if combo_m:
        lines.append(f'{prefix}+{combo_m.group(1)} Onslaught Stacks')
    lines += extract_conversions(txt, prefix)

    refresh_chance_m = re.search(r'^refreshDurationChance=([\d.]+)', txt, re.M)
    if refresh_chance_m:
        amount_m = re.search(r'^refreshDurationAmount=([\d.]+)', txt, re.M)
        max_m = re.search(r'^refreshDurationMax=([\d.]+)', txt, re.M)
        skill_m = re.search(r'^refreshDurationSkill=(\S+)', txt, re.M)
        amount = _first_value(amount_m.group(1)) if amount_m else '1'
        when = refresh_trigger_phrase(txt, 'refreshDurationChance')
        skill_name = skill_display_name(read_rel(skill_m.group(1))) if skill_m else None
        skill_name = skill_name or (prefix.rstrip(': ') or 'this skill')
        plural = '' if amount == '1' else 's'
        line = f'{prefix}{when} to refresh duration of {skill_name} by {amount} Second{plural}'
        if max_m:
            line += f' (Max {_first_value(max_m.group(1))} Seconds)'
        lines.append(line)

    # refreshCooldown* -- same shape as refreshDuration* above but reduces a
    # skill's COOLDOWN on trigger instead of extending a buff's duration
    # (user-flagged via "Anointed Blade"'s Fire Strike modifier: "25% Chance
    # on Attack to reduce cooldown of Devastation by 3 Seconds" -- a
    # genuinely different field family, not a formatting variant of
    # refreshDuration*, so it needs its own block rather than a shared one).
    cd_chance_m = re.search(r'^refreshCooldownChance=([\d.]+)', txt, re.M)
    if cd_chance_m:
        cd_amount_m = re.search(r'^refreshCooldownAmount=([\d.]+)', txt, re.M)
        cd_skill_m = re.search(r'^refreshCooldownSkill=(\S+)', txt, re.M)
        amount = _first_value(cd_amount_m.group(1)) if cd_amount_m else '1'
        when = refresh_trigger_phrase(txt, 'refreshCooldownChance')
        skill_name = skill_display_name(read_rel(cd_skill_m.group(1))) if cd_skill_m else None
        skill_name = skill_name or (prefix.rstrip(': ') or 'this skill')
        plural = '' if amount == '1' else 's'
        lines.append(f'{prefix}{when} to reduce cooldown of {skill_name} by {amount} Second{plural}')

    if not lines and re.search(r'^modSpawnObjects', txt, re.M):
        # `modSpawnObjects` swaps in a different creature file for the
        # summon entirely -- confirmed NOT cosmetic (user-flagged): checked
        # the swapped-in Pet record's own attackSkillName/
        # specialAttackSkillName against the un-swapped base pet file and
        # both differ (e.g. skeleton_01c_chaos.dbr's basic/special attacks
        # are petskill_skeleton_chaosshard/chaosnova vs. the base
        # skeleton_01c.dbr's fireshard/fireballnova) -- a real attack-kit
        # change, not a texture/mesh swap. The swapped pet's own
        # `description=` tag resolves to a generic base-type name (e.g.
        # "Skeletal Warrior") that doesn't reliably match what the specific
        # variant should be called, so this reports the mechanic rather
        # than guessing a creature name.
        lines.append(f'{prefix}Basic & Special Attack swapped')
    return lines


def resolve_skill_modifiers(txt):
    """modifiedSkillName{i}/modifierSkillName{i} pairs boost a class skill
    the player already trained (e.g. "Modifies Raise Skeletons: +100% Chaos
    dmg, 100% Fire dmg converted to Chaos dmg"). modifierSkillName{i} is
    usually a SkillSecondary_PetModifier wrapper whose own petSkillName
    points at the real Skill_Modifier/Skill_Passive payload; a few (mostly
    cosmetic pet-model swaps, e.g. "Always summons Chaos Skeletal Mages")
    have no numeric payload at all and correctly yield nothing."""
    lines = []
    for i in range(1, 5):
        mod_name_m = re.search(rf'^modifiedSkillName{i}=(\S+)', txt, re.M)
        mod_mod_m = re.search(rf'^modifierSkillName{i}=(\S+)', txt, re.M)
        if not mod_name_m or not mod_mod_m:
            continue
        target_name = skill_display_name(read_rel(mod_name_m.group(1)))
        if not target_name:
            continue
        mod_txt = read_rel(mod_mod_m.group(1))
        if mod_txt is None:
            continue
        if re.search(r'^petSkillName=(\S+)', mod_txt, re.M):
            pet_m = re.search(r'^petSkillName=(\S+)', mod_txt, re.M)
            mod_txt = read_rel(pet_m.group(1))
        # A modifier whose entire payload the specialist has no opinion on would
        # otherwise vanish along with its skill heading -- Krieg's Armament's
        # Reckless Power modifier is exactly that (resistance reduction and
        # nothing else), so one of the set's three modifier blocks was missing.
        lines.extend(supplement_shared_stats(
            mod_txt, f'{target_name}: ',
            format_skill_modifier_stats(mod_txt, f'{target_name}: ')))
    return lines


BASE_DAMAGE_RE = re.compile(r'^offensiveBase([A-Za-z]+)(Min|Max)=(-?[\d.]+)', re.M)


def base_weapon_damage(txt):
    """offensiveBase{Type}Min/Max = the weapon's OWN inherent damage for a
    non-Physical type (e.g. Harbinger's Void Blade: offensiveBaseChaosMin/
    Max=63/84 -- its entire primary damage line) -- process_stats() only
    recognizes offensive{Type}*/offensiveSlow{Type}* (bonus modifiers layered
    on TOP of a base), so these were being silently dropped entirely, not
    just under-labeled. No "+" prefix: this is the base value, not a bonus,
    matching how the in-game tooltip shows it as a plain number range.
    Physical has no "Base" variant in this dataset -- melee weapons store
    their inherent Physical damage directly as plain offensivePhysicalMin/
    Max, which process_stats() already captures (with a "+", technically
    inaccurate for pure-physical weapons but not a missing-data issue)."""
    seen = set()
    lines = []
    for m in BASE_DAMAGE_RE.finditer(txt):
        kind, _, _ = m.groups()
        if kind not in DAMAGE_TYPES or kind in seen:
            continue
        seen.add(kind)
        minv = re.search(rf'^offensiveBase{kind}Min=(-?[\d.]+)', txt, re.M)
        maxv = re.search(rf'^offensiveBase{kind}Max=(-?[\d.]+)', txt, re.M)
        if not minv:
            continue
        num = _fmt_num(minv.group(1))
        if maxv:
            num = f"{num}–{_fmt_num(maxv.group(1))}"
        label = _type_dmg_label(kind)
        lines.append(f"{num} {label}")
    return lines


def base_armor(txt):
    """Flat `defensiveProtection=` is the piece's own inherent Armor value
    (804/2478 armor records carry it) -- process_stats() only recognizes
    defensiveProtectionModifier (a % bonus on top), so every armor piece's
    actual Armor rating was being omitted entirely. No "+" prefix, same
    reasoning as base_weapon_damage."""
    m = re.search(r'^defensiveProtection=(-?[\d.]+)', txt, re.M)
    if not m:
        return []
    # The exact complement of process_stats()'s defensiveProtection branch,
    # which renders the same field as a granted "+N Armor" bonus on anything
    # that is not an equippable armor/weapon piece. Without this guard the two
    # both fire and the line prints twice -- as it did on Bloodied Crystal
    # (component), 2 armor affixes, 3 rings, a medal, a relic and 6 transmutes.
    # One field, two meanings, one Class= test: keep the two in step.
    cls_m = re.search(r'^Class=(\S+)', txt, re.M)
    cls = cls_m.group(1) if cls_m else ''
    if not cls.startswith(('ArmorProtective_', 'WeaponArmor_')):
        return []
    return [f"{_fmt_num(m.group(1))} Armor"]


ATTACK_SPEED_LABELS = {
    'tagAttackSpeedVerySlow': 'Very Slow', 'tagAttackSpeedSlow': 'Slow',
    'tagAttackSpeedAverage': 'Average', 'tagAttackSpeedFast': 'Fast',
    'tagAttackSpeedVeryFast': 'Very Fast',
}


def base_attack_speed(txt):
    """characterBaseAttackSpeedTag names the weapon's inherent speed class
    (e.g. tagAttackSpeedVeryFast) -- purely descriptive (not a numeric bonus
    stackable with characterAttackSpeedModifier), but real in-game tooltips
    show it, so it belongs alongside the other base stats."""
    m = re.search(r'^characterBaseAttackSpeedTag=(\S+)', txt, re.M)
    if not m:
        return []
    label = ATTACK_SPEED_LABELS.get(m.group(1))
    return [f"Attack Speed: {label}"] if label else []


# ------------------------------------------------------- effect composition -
# The ONE order in which a record's effect lines are emitted. Every catalogue
# calls effects_of(); nobody composes their own list.
#
# There used to be four hand-written lists -- two in build_mi_catalogue, one in
# build_affix_catalogue, one in build_item() below -- that differed in
# membership AND order, and the differences were accidental rather than meant.
# The cost was not theoretical: conversions were missing from two of the four,
# so 396 affix records and 33 enchant/materia records rendered their own
# damage conversion nowhere at all, even though extract_conversions() sat in
# this module being called by the other two.
#
# The order is the MI one, which read as the game's own tooltip does: what the
# piece IS, then what it grants, then what it gives a pet.
#
# The third column is the builder's CLAIM: the record fields it is responsible
# for rendering, as a regex over field names. It is not used to dispatch --
# every builder re-reads the whole record -- it exists so the reverse-coverage
# gate can ask "is every field in the stat table rendered by somebody?" without
# a hand-maintained second list going stale the moment a builder is added here.
# process_stats() reports its own claim per line via process_stats_fields(),
# so it declares None rather than a pattern it would have to keep in sync.
EFFECT_BUILDERS = [
    ('base weapon damage', base_weapon_damage,       r'^offensiveBase[A-Za-z]+(Min|Max)$'),
    ('base armor',         base_armor,               r'^defensiveProtection$'),
    ('base attack speed',  base_attack_speed,        r'^characterBaseAttackSpeedTag$'),
    ('stats',              process_stats,            None),
    ('conversions',        lambda txt: extract_conversions(txt, ''),
                                                     r'^conversion(InType|OutType|Percentage)\d*$'),
    ('item skill',         resolve_item_skill,       r'^itemSkill(Name|Level|AutoController)$'),
    ('augment skills',     resolve_augment_skills,
                                                     r'^augment(Skill|Mastery)(Name|Level)\d*$'),
    ('all-skills bonus',   augment_all_skills,       r'^augmentAllLevel$'),
    ('skill modifiers',    resolve_skill_modifiers,  r'^modifi(ed|er)SkillName\d*$'),
    ('pet bonus',          resolve_pet_bonus,        r'^petBonusName$'),
    ('pet conversions',    resolve_pet_conversions,  r'^petBonusName$'),
]


def effects_of(txt):
    """Every effect line a record grants, in one order, for every catalogue.

    Blank lines are NOT dropped here -- each caller already filters them on the
    way into its card dict, and swallowing them here would hide a builder that
    started returning empties."""
    lines = []
    for _, fn, _ in EFFECT_BUILDERS:
        lines += fn(txt)
    return lines


def composed_item_name(txt, base_name):
    """A record's REAL displayed name = `<itemQualityTag> <itemStyleTag>
    <itemNameTag>`, modifier tags omitted when absent. All three resolve
    through ITEM_TAGS.

      - `itemQualityTag` -- material/condition rung on ordinary white gear:
        tagQualityWeaponMetal01/02/04 -> Scrapmetal / Tarnished / Steel.
      - `itemStyleTag` -- ONE field, TWO unrelated jobs: cosmetic style words
        on white gear (tagStyle018 -> "Salvaged"), AND the upgrade tier on
        uniques (tagStyleUniqueTier2/Tier3 -> "Empowered"/"Mythical",
        tagStyleUniqueInverted -> "Polarized"). Do not assume one meaning.

    Order verified against GrimTools: a04_gun2h003.dbr is quality "Scrapmetal"
    + style "Obsolete" + name "Heavy Crossbow" -> "Scrapmetal Obsolete Heavy
    Crossbow".

    LOAD-BEARING, NOT COSMETIC. Reading itemNameTag alone makes genuinely
    different items share a name, so any by-name grouping silently DISCARDS
    all but one. Three crossbows (a01/a02/a08_gun2h003.dbr) differ ONLY by
    itemQualityTag; three helmets only by itemStyleTag. 1075 records under the
    gear folders carry one or both fields.

    `base_name` arrives already resolved and cleaned, because callers reach it
    differently -- some reject a borrowed tag and substitute a generic slot
    label first. The prefixes still apply to whatever identity survived that.
    """
    if not base_name:
        return base_name
    parts = []
    for field in ('itemQualityTag', 'itemStyleTag'):
        m = re.search(rf'^{field}=(\S+)', txt, re.M)
        if not m:
            continue
        word = clean_name(ITEM_TAGS.get(m.group(1)))
        # An unresolvable tag contributes nothing rather than leaking the
        # raw tag id into a display name.
        if word and word not in parts:
            parts.append(word)
    parts.append(base_name)
    return ' '.join(parts)
