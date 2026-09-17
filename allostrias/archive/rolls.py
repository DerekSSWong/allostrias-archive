"""What a stored stat value actually rolls between.

A record stores the MIDPOINT of a stat, not the value you get. The width comes
from `lootRandomizerJitter` on the same record. Ported from gd-lib's
affix_table.roll_band, which solved and verified it; the verification notes are
kept because they are what stop the rule being "improved" back into a wrong
one.

Only the BAND lives here. Replaying a specific item's seed to get the value it
actually rolled is a different problem (gd-lib's rolls.py) and is not needed
until saved items are read.
"""
import math


def roll_band(value: float, jitter: float) -> tuple[float, float]:
    """(lo, hi) the game will actually roll for a stored value.

    SOLVED, NOT FITTED. The record stores the midpoint and
    `lootRandomizerJitter` the half-width as a percentage, floored -- but
    never below 1:

        half = max(1, floor(|v| * jitter / 100));  lo = v - half, hi = v + half

    The `max(1, ...)` IS PART OF THE FORMULA, not a guard on it. Plain floor
    collapses the band on small values and the game disagrees: `of Menhir's
    Wall` stores +2% Defensive Ability at jitter 28 and rolls 1-3, where
    floor(0.56) = 0 would give a fixed 2. round() fixes that case and breaks
    five others (10 at jitter 28 rolls 8-12; round gives 7-13).

    THE MULTIPLICATIVE FORM IS WRONG and it is the one you would write first:
    round(v * (1 +/- j/100)) misses 10 of 25 checked values. `of Blood`'s focus
    variant stores 95 at jitter 5 and rolls 91-99; multiplicative says 90-100.
    Floor of the half-width, not a scaling of the endpoints.

    Verified upstream against 25 values read off grimdb (v=4..124, jitter
    5..28, 25/25 exact), then against `Wraithbound` in full -- 118 of 120
    numeric lines exact across four slot families.

    TWO LINES REMAIN OPEN and no rule here explains them, both `characterLife`
    on an accessory: v=150 j=18 shows 124/177 against 123/177, and v=200 j=15
    shows 170/229 against 170/230. Both observed bands are an ODD number wide,
    which no symmetric half-width can produce, and the narrowing is on a
    different side each time -- so it is not a rounding mode. Recorded rather
    than fitted: a rule invented to cover two points out of 120 would be the
    believable wrong answer, not a finding.

    No jitter means the value is fixed, so the band collapses to a point
    instead of being guessed at.

    EVERY LINE ROLLS INDEPENDENTLY. There is no single "quality" per affix.
    Observed on a real drop: `of the Eagle` carries Strength/Dexterity/
    Intelligence all at midpoint 5 with one jitter of 35, so all three share
    the band 4-6 -- and the item rolled +6 / +4 / +4. Same band, three separate
    draws, both extremes hit. One line's roll says nothing about another's, and
    no record anywhere states how many draws are taken.
    """
    if not jitter:
        return (value, value)
    half = max(1, math.floor(abs(value) * jitter / 100.0))
    return (value - half, value + half)


# ---------------------------------------------------------------------------
# Which fields roll, and which take the item scale.
#
# Ported from gd-lib's rolls.py, itself ported from Item Assistant
# (github.com/marius00/iagd, MIT). The lists there are a DRAW ORDER and the
# order is load-bearing for replaying a specific item's seed. Here only
# MEMBERSHIP is used -- a band needs to know whether a field rolls, not when --
# so the lists are kept in their original order but nothing depends on it.
#
# A field absent from every list is NOT assumed fixed. It comes back as
# 'unmodeled' with no band, because inventing a range for a stat that does not
# roll is a believable wrong answer, and so is hiding a range that does.
# ---------------------------------------------------------------------------
BASE_JITTER = 20.0          # every item base jitters at 20%; affixes carry their own

_CHAR = (
    'characterStrength', 'characterDexterity', 'characterIntelligence',
    'characterLife', 'characterMana', 'characterStrengthModifier',
    'characterDexterityModifier', 'characterIntelligenceModifier',
    'characterLifeModifier', 'characterManaModifier', 'characterLifeMultModifier',
    'characterOffensiveAbility', 'characterDefensiveAbility',
    'characterOffensiveAbilityModifier', 'characterDefensiveAbilityModifier',
    'characterLifeRegen', 'characterLifeRegenModifier', 'characterManaRegenModifier',
    'characterConstitutionModifier', 'characterHealIncreasePercent',
    'characterTotalSpeedModifier', 'characterAttackSpeedModifier',
    'characterAttackSpeedMaxModifier', 'characterSpellCastSpeedModifier',
    'characterSpellCastSpeedMaxModifier', 'characterRunSpeedModifier',
    'characterRunSpeedMaxModifier', 'characterDefensiveBlockRecoveryReduction',
    'characterEnergyAbsorptionPercent', 'characterDodgePercent',
    'characterDeflectProjectile', 'characterManaLimitReserve',
    'characterManaLimitReserveModifier',
)
# Flat added damage, stored as a Min/Max pair. offensivePhysical is the weapon's
# OWN damage on a Weapon* class -- fixed there, a real rolled pair on armour and
# jewellery -- so it is gated on the item's Class, not on the field name.
_FLAT = (
    'offensivePhysical', 'offensiveBonusPhysical', 'offensivePierce',
    'offensiveFire', 'offensiveCold', 'offensiveLightning', 'offensivePoison',
    'offensiveLife', 'offensiveAether', 'offensiveChaos', 'offensiveElemental',
)
_SLOW_FLAT = (
    'offensiveSlowPhysical', 'offensiveSlowBleeding', 'offensiveSlowFire',
    'offensiveSlowCold', 'offensiveSlowLightning', 'offensiveSlowPoison',
    'offensiveSlowLife', 'offensiveSlowAether', 'offensiveSlowChaos',
    'offensiveSlowLifeLeach', 'offensiveSlowManaLeach',
)
_DMG = (
    'offensiveTotalDamageModifier', 'offensiveCritDamageModifier',
    'offensivePhysicalModifier', 'offensivePierceModifier', 'offensiveFireModifier',
    'offensiveColdModifier', 'offensiveLightningModifier', 'offensivePoisonModifier',
    'offensiveLifeModifier', 'offensiveAetherModifier', 'offensiveChaosModifier',
    'offensiveElementalModifier', 'offensiveSlowPhysicalModifier',
    'offensiveSlowPhysicalDurationModifier', 'offensiveSlowBleedingModifier',
    'offensiveSlowBleedingDurationModifier', 'offensiveSlowFireModifier',
    'offensiveSlowFireDurationModifier', 'offensiveSlowColdModifier',
    'offensiveSlowColdDurationModifier', 'offensiveSlowLightningModifier',
    'offensiveSlowLightningDurationModifier', 'offensiveSlowPoisonModifier',
    'offensiveSlowPoisonDurationModifier', 'offensiveSlowLifeModifier',
    'offensiveSlowLifeDurationModifier', 'offensiveSlowAetherModifier',
    'offensiveSlowChaosModifier',
)
# Stun DURATION as a percentage -- absent from the upstream draw order, like
# retaliationFear, and demonstrably rolling: Arbiter stores
# offensiveStunModifier=30 and grimdb shows "+24/36% Stun Duration", which is
# roll_band(30, 20). Non-scaling: Arbiter's other modifiers come out unscaled
# too, so nothing here takes the item scale.
_MISC_MOD = ('offensiveStunModifier',)

_LEECH = ('offensiveLifeLeech',)
_OFF_REFLEX = ('offensiveStun', 'offensiveKnockdown', 'offensiveSleep',
               'offensiveFreeze', 'offensivePetrify')
# (field, takes the item scale). Speed slows scale; ability reductions do not.
_OFF_SLOW = (
    ('offensiveSlowTotalSpeed', True), ('offensiveSlowAttackSpeed', True),
    ('offensiveSlowSpellCastSpeed', True), ('offensiveSlowRunSpeed', True),
    ('offensiveSlowOffensiveAbility', False), ('offensiveSlowDefensiveAbility', False),
)
_OFF_REDUC = (
    'offensivePhysicalReductionPercent', 'offensiveElementalReductionPercent',
    'offensiveTotalDamageReductionPercent', 'offensiveTotalDamageReductionAbsolute',
    'offensiveTotalResistanceReductionPercent',
    'offensiveTotalResistanceReductionAbsolute',
    'offensivePhysicalResistanceReductionPercent',
    'offensivePhysicalResistanceReductionAbsolute',
    'offensiveElementalResistanceReductionPercent',
    'offensiveElementalResistanceReductionAbsolute',
)
_RETAL_FLAT = (
    'retaliationPhysical', 'retaliationPierce', 'retaliationFire', 'retaliationCold',
    'retaliationLightning', 'retaliationPoison', 'retaliationLife',
    'retaliationAether', 'retaliationChaos', 'retaliationElemental',
)
_RETAL_DUR = (
    'retaliationSlowPhysical', 'retaliationSlowPierce', 'retaliationSlowFire',
    'retaliationSlowCold', 'retaliationSlowLightning', 'retaliationSlowPoison',
    'retaliationSlowLife', 'retaliationSlowAether', 'retaliationSlowChaos',
    'retaliationSlowBleeding',
)
_RETAL_DUR_PCT = ('retaliationSlowAttackSpeed', 'retaliationSlowRunSpeed')
_RETAL_MOD = (
    'retaliationTotalDamageModifier', 'retaliationPhysicalModifier',
    'retaliationPierceModifier', 'retaliationFireModifier', 'retaliationColdModifier',
    'retaliationLightningModifier', 'retaliationPoisonModifier',
    'retaliationLifeModifier', 'retaliationAetherModifier', 'retaliationChaosModifier',
    'retaliationElementalModifier', 'retaliationDamageMultModifier',
)
# retaliationFear is absent from the upstream draw order but demonstrably
# rolls: Dirge of Arkovia stores retaliationFearMin=2 and grimdb shows
# "1/3 Seconds of Terrify Retaliation", which is roll_band(2, 20) exactly.
# Safe to add HERE because this module only computes bands -- it is not the
# seed replay, where inserting a field would shift every later draw.
_RETAL_REFLEX = ('retaliationStun', 'retaliationFreeze', 'retaliationConfusion',
                 'retaliationFear')
# The resistance CAPS (defensive*MaxResist) draw nothing and are absent by design.
_DEF = (
    'defensiveBlockModifier', 'defensiveBlockAmountModifier',
    'defensiveProtectionModifier', 'defensiveAbsorptionModifier',
    'defensivePhysical', 'defensivePierce', 'defensiveFire', 'defensiveCold',
    'defensiveLightning', 'defensivePoison', 'defensiveLife', 'defensiveAether',
    'defensiveChaos', 'defensiveElementalResistance', 'defensiveBleeding',
    'defensiveSlowLifeLeach', 'defensiveSlowManaLeach', 'defensiveManaBurn',
    'defensiveAllResistance', 'defensivePhysicalModifier', 'defensivePierceModifier',
    'defensiveFireModifier', 'defensiveColdModifier', 'defensiveLightningModifier',
    'defensivePoisonModifier', 'defensiveLifeModifier', 'defensiveAetherModifier',
    'defensiveChaosModifier', 'defensiveElementalModifier', 'defensiveBleedingModifier',
    'defensiveSlowLifeLeachModifier', 'defensiveSlowManaLeachModifier',
    'defensivePhysicalDuration', 'defensiveFireDuration', 'defensiveColdDuration',
    'defensiveLightningDuration', 'defensivePoisonDuration', 'defensiveLifeDuration',
    'defensiveAetherDuration', 'defensiveChaosDuration', 'defensiveBleedingDuration',
    'defensiveSlowLifeLeachDuration', 'defensiveSlowManaLeachDuration',
    'defensivePhysicalDurationModifier', 'defensiveFireDurationModifier',
    'defensiveColdDurationModifier', 'defensiveLightningDurationModifier',
    'defensivePoisonDurationModifier', 'defensiveLifeDurationModifier',
    'defensiveAetherDurationModifier', 'defensiveChaosDurationModifier',
    'defensiveBleedingDurationModifier', 'defensiveSlowLifeLeachDurationModifier',
    'defensiveSlowManaLeachDurationModifier', 'defensiveDisruption', 'defensiveStun',
    'defensiveStunModifier', 'defensiveFreeze', 'defensiveTrap', 'defensivePetrify',
    'defensiveSleep', 'defensiveSleepModifier', 'defensiveKnockdown',
    'defensiveKnockdownModifier', 'defensiveTaunt', 'defensiveFear',
    'defensiveConfusion', 'defensiveConvert', 'defensiveTotalSpeedResistance',
    'defensiveCrowdControl', 'defensiveReflect', 'defensiveReflectModifier',
    'defensivePercentCurrentLife', 'defensivePercentReflectionResistance',
)
_CONV = ('conversionPercentage', 'conversionPercentage2')
_SKILL = (
    'skillCooldownReduction', 'skillManaCostReduction',
    'skillComboChargeSpendReduction', 'skillProjectileSpeedModifier',
    'skillCooldownReductionModifier', 'skillManaCostReductionModifier',
)
# These two modifiers ignore the item scale even though their peers take it.
_NON_SCALING = frozenset({'offensiveCritDamageModifier',
                          'offensiveTotalDamageModifier'})

# Present on items, never drawn: echoed at the record value, unscaled.
FIXED = frozenset({
    'characterBaseAttackSpeed', 'characterManaRegen', 'characterConstitution',
    'characterAttackSpeed', 'characterSpellCastSpeed', 'characterRunSpeed',
    'characterIncreasedExperience', 'characterIncreasedGold',
    'characterLightRadius', 'characterGlobalReqReduction',
    'characterLevelReqReduction', 'characterModifierPoints',
    'defensiveProtection',          # armour: 0 draws
    'defensiveBlock', 'defensiveBlockChance', 'blockAbsorption', 'blockRecoveryTime',
})

# Suffixes that turn a base field name into the actual record fields.
_PAIR_KINDS = {'flat': ('Min', 'Max')}
_COMP_KINDS = {
    'retal_dur': ('Min', 'DurationMin', 'Chance'),
    'retal_reflex': ('Min', 'Chance'),
    'off_reflex': ('Min', 'Chance'),
    'off_slow': ('Min', 'DurationMin', 'Chance'),
    'leech': ('Min',),
    'off_reduc': ('Min', 'DurationMin'),
}


def _expand(fields, suffixes):
    return {f + s for f in fields for s in suffixes}


# field -> takes the item scale
_SCALES: dict[str, bool] = {}
for _f in _CHAR:
    _SCALES[_f] = False
for _f in _expand(_FLAT, _PAIR_KINDS['flat']):
    _SCALES[_f] = True
for _f in _expand(_SLOW_FLAT, _PAIR_KINDS['flat']):
    _SCALES[_f] = True
for _f in _DMG:
    _SCALES[_f] = _f not in _NON_SCALING
for _f in _expand(_LEECH, _COMP_KINDS['leech']):
    _SCALES[_f] = False
for _f in _expand(_OFF_REFLEX, _COMP_KINDS['off_reflex']):
    _SCALES[_f] = False
for _f, _sc in _OFF_SLOW:
    for _s in _COMP_KINDS['off_slow']:
        _SCALES[_f + _s] = _sc
for _f in _expand(_OFF_REDUC, _COMP_KINDS['off_reduc']):
    _SCALES[_f] = False
for _f in _expand(_RETAL_FLAT, _PAIR_KINDS['flat']):
    _SCALES[_f] = False
for _f in _expand(_RETAL_DUR + _RETAL_DUR_PCT, _COMP_KINDS['retal_dur']):
    _SCALES[_f] = False
for _f in _RETAL_MOD:
    _SCALES[_f] = False
for _f in _expand(_RETAL_REFLEX, _COMP_KINDS['retal_reflex']):
    _SCALES[_f] = False
for _f in _DEF:
    _SCALES[_f] = False
for _f in _CONV:
    _SCALES[_f] = False
for _f in _SKILL:
    _SCALES[_f] = False
for _f in _MISC_MOD:
    _SCALES[_f] = False

ROLLED = frozenset(_SCALES)
CONVERSION = frozenset(_CONV)

# Statuses a band can carry. Anything not positively known is 'unmodeled', and
# an unmodeled field gets NO band rather than a guessed one.
ROLLED_STATUS, FIXED_STATUS, UNMODELED_STATUS = 'rolled', 'fixed', 'unmodeled'
# A whole record kind that the game never jitters -- distinct from 'fixed',
# which is a field that draws nothing on a record that DOES roll.
UNROLLED_STATUS = 'unrolled'

# WHICH RECORDS ROLL AT ALL. Both halves of this are verified against grimdb
# (2026-09-17) because both were got wrong in turn, in opposite directions:
#
#   ROLLS -- equipment bases, their prefix and suffix, and RELICS.
#     Dirge of Arkovia (ItemArtifact) stores 28 / 18 / 2 and grimdb shows
#     23-33% / 15-21% / 1-3s, which is roll_band(v, 20) exactly. Its pet
#     bonus rolls too: 50 / 100 / 15 shown as 40-60 / 80-120 / 12-18.
#
#   DOES NOT ROLL -- components (ItemRelic) and their kin. Mark of the
#     Myrmidon stores 120 / 25 / 15 / 180 and grimdb shows those flat. The
#     first version of this banded them to 96-144 / 20-30 / 12-18 / 144-216,
#     every number wrong and every one plausible; the correction then swung
#     too far and stopped relics rolling as well.
#
# Augments (ItemEnchantment) do not roll either -- VERIFIED: Coven Bloodied
# Ash stores 8 and 10 and grimdb shows a flat "8% Health Regeneration" and
# "10% Bleeding Resistance". This was an assumption until 2026-09-17.
#
# A COMPONENT'S "9-12 Vitality Damage" IS NOT A ROLL. Seal of Blight stores
# offensiveLifeMin=9 and offensiveLifeMax=12: that is the damage SPREAD of a
# single hit, shown as a range by the game and flat as far as rolling goes.
# Reading a Min/Max pair as a roll band would make every component look
# jittered and would be wrong in exactly the believable direction.
ROLLING_CLASSES = frozenset({'ItemArtifact'})


def is_fixed(field: str, item_class: str = '') -> bool:
    """True when the field is present on items but never drawn.

    `item_class` matters for exactly one family: a weapon's own physical
    damage is its stated range and draws nothing, while the same field on
    armour or jewellery is a real rolled pair.
    """
    if field in FIXED:
        return True
    if field.startswith('offensivePhysical') and field[-3:] in ('Min', 'Max') \
            and item_class.startswith('Weapon'):
        return True
    if field.startswith('character') and field.endswith('ReqReduction'):
        return True
    if field.startswith('offensiveBase') and field[-3:] in ('Min', 'Max'):
        return True                      # weapon base damage
    if field.startswith('offensiveSlow') and field.endswith('DurationMin'):
        return True
    # Resistance CAPS. Upstream's note says they draw no RNG; ASSUMED fixed on
    # that alone, not verified against a max-resist reading in game.
    if field.startswith('defensive') and field.endswith('MaxResist'):
        return True
    if field.startswith('offensive') and field.endswith('RatioMin'):
        return True
    if (field.endswith('Chance') and not field.endswith('GlobalChance')
            and field.startswith(('offensive', 'retaliation', 'skill'))):
        return True                      # per-proc chance companion
    if field in ('offensiveGlobalChance', 'retaliationGlobalChance'):
        return True
    if field.startswith(('offensive', 'retaliation')) and field.endswith('Global'):
        return True                      # grouped-proc flag
    return False


def scale(value: float, scale_pct: float) -> int:
    """attributeScalePercent applied, then truncated -- as the game does it."""
    return int(value * (100.0 + scale_pct) / 100.0)


def band(field: str, value: float, jitter: float = BASE_JITTER,
         scale_pct: float = 0.0, item_class: str = '',
         rolls: bool = True) -> tuple[float | None, float | None, str]:
    """(lo, hi, status) for one stored stat value.

    `rolls=False` means the whole RECORD is never jittered -- a component,
    augment or relic -- and every value is exactly what is stored.

    Returns no band for anything not positively known to roll. A field this
    module has never heard of comes back 'unmodeled' with lo/hi None, which is
    visibly missing; giving it the value as a fixed point would claim it does
    not roll, and giving it a band would claim it does.
    """
    if not rolls:
        return (value, value, UNROLLED_STATUS)
    if is_fixed(field, item_class):
        return (value, value, FIXED_STATUS)
    if field in CONVERSION:
        # Damage conversion jitters MULTIPLICATIVELY, unlike everything else,
        # and clamps to 0..100.
        if jitter <= 0.0:
            return (value, value, ROLLED_STATUS)
        frac = jitter * 0.01
        return (max(0.0, value * (1.0 - frac)),
                min(100.0, value * (1.0 + frac)), ROLLED_STATUS)
    if field not in ROLLED:
        return (None, None, UNMODELED_STATUS)
    lo, hi = roll_band(value, jitter)
    if _SCALES[field] and scale_pct:
        lo, hi = scale(lo, scale_pct), scale(hi, scale_pct)
    return (lo, hi, ROLLED_STATUS)
