#!/usr/bin/env python3
"""Replay the game's item-roll RNG to recover an item's REAL stat values.

Read by the character sheet and the Gear Stash view. `archive/rolls.py` is the
other half: it carries only the roll BAND, the range a stored centre can roll
between; this replays one item's seed to the value it did roll.

Provenance, and it matters because nothing here is original: Item Assistant
(github.com/marius00/iagd, MIT, (c) 2019 marius00),
`IAGrim/Services/ItemStats/SeedStats/` -> gd-lib's `rolls.py` -> here. The
order tables and the jitter formulas are IAGD's. Porting rather than importing
is the pattern this repo already uses for the .arz/.arc parsers and the
eligibility walk.

⚠️ VERIFIED BY RUNNING, NOT BY READING. Two gates, run after ANY edit here:
  tests/test_seedroll.py       against gd-lib's original, with the corrections
                               below applied to the oracle, over every worn item.
  tests/test_seedroll_game.py  against the GAME: Item Assistant stores the game's
                               own tooltip text for every item it holds, and every
                               number this renders must be on it.
A transcription slip in an order table does not raise -- it desyncs the stream
and returns plausible numbers, which is the one failure mode a reader cannot
catch.

⚠️ THE DRAW ORDER IS THE WHOLE ALGORITHM. One MINSTD stream is shared by every
stat on the item, so a field drawn out of turn -- or a rollable field present on
the record that this file does not know about -- shifts every later value. That
is why an unknown rollable field is a REFUSAL (`Roll.unmodeled` -> caller falls
back to unrolled values) and never a shrug: a desynced stream still produces
perfectly plausible numbers.

⚠️ NOT A GENERAL ITEM READER. It covers the item's own record plus its prefix and
suffix -- what IAGD covers. Components, augments, crafting bonuses and relic
completion bonuses are separate records fed to the sheet unrolled, on the
unverified assumption that they do not jitter.
"""
import math, struct

# ---------------------------------------------------------------------------
# MINSTD (Park-Miller) with Schrage's method, as the game does it.
# ---------------------------------------------------------------------------
_A, _Q, _R, _M = 16807, 127773, 2836, 2147483647


def _i32(x):
    x &= 0xFFFFFFFF
    return x - 0x100000000 if x >= 0x80000000 else x


def _f32(x):
    """Coerce to C++ `float`. The scale pass is computed in float32 IN THE GAME and
    the difference is visible: 90*130/100 truncates to 117, while 90*1.3f is
    116.9999924 and truncates to 116."""
    return struct.unpack('f', struct.pack('f', x))[0]


class Minstd:
    """The shared per-item stream. Construction performs the one priming draw the
    game does before any stat is rolled."""

    def __init__(self, seed):
        self.state = self.step(_i32(seed & 0xFFFFFFFF))

    @staticmethod
    def step(s):
        hi, lo = s // _Q if s >= 0 else -((-s) // _Q), s % _Q if s >= 0 else -((-s) % _Q)
        r = _A * lo - _R * hi
        if r < 0:
            r += _M
        return r

    def next(self):
        self.state = self.step(self.state)
        return self.state


def _range_mod(s, spread):
    """`s % (2*spread + 1)` in the game's UNSIGNED arithmetic. A negative spread
    (from a negative stat value) wraps to a huge modulus, which is why this cannot
    be written with Python's own `%`."""
    modulus = (2 * spread + 1) & 0xFFFFFFFF
    if modulus == 0:
        modulus = 1
    return _i32((s & 0xFFFFFFFF) % modulus)


def _trunc(x):
    return math.trunc(x)


def _round_away(x):
    return math.floor(x + 0.5) if x >= 0 else math.ceil(x - 0.5)


# ---------------------------------------------------------------------------
# The jitter functions. Integer-uniform rolls -- NOT the multiplicative
# base*(1 +/- jitter) that forum posts quote, which only matches at the endpoints.
# ---------------------------------------------------------------------------
BASE_JITTER = 20.0


def jitter_char(value, pct, rng):
    """Char / Damage / Retaliation / Defense stores. Minimum +/-1 spread, and a
    result under 1 in magnitude snaps back to the base value -- the draw is still
    consumed, which is the part that matters for everything after it."""
    if value == 0.0 or pct == 0.0:
        return value                      # no draw
    spread = int(value * pct * 0.01)
    if spread == 0:
        spread = 1
    rolled = float(_range_mod(rng.next(), spread)) - spread + value
    return value if abs(rolled) < 1.0 else rolled


def jitter_skill(value, pct, rng):
    """Skill store: no min-1 clamp, and it draws even at 0 percent."""
    if value == 0.0:
        return value                      # no draw
    spread = int(value * pct * 0.01)
    rolled = float(_range_mod(rng.next(), spread)) - spread + value
    return value if abs(rolled) < 1.0 else rolled


def apply_scale(jittered, scale_pct):
    """attributeScalePercent + affix lootRandomizerScale, in float32, then truncated."""
    num = _f32(_f32(jittered) * _f32(100.0 + scale_pct))
    return _trunc(_f32(num / _f32(100.0)))


def jitter_conversion(value, pct, rng):
    """Damage conversion: a multiplicative float32 jitter, one draw per valid slot."""
    if pct <= 0.0:
        return value
    j = pct * 0.01
    factor = _f32(rng.next() * (2.0 ** -31) * (2.0 * j) + (1.0 - j))
    rolled = value * factor
    return 0.0 if rolled < 0.0 else (100.0 if rolled > 100.0 else rolled)


# ---------------------------------------------------------------------------
# Draw order. One list per store, in the sequence the game's loaders read them.
# ⚠️ THE ORDER IS DATA, NOT STYLE: reordering a list, or dropping a field that
# never appears on an item, moves every draw after it.
# ---------------------------------------------------------------------------
CHAR = [
    'characterStrength', 'characterDexterity', 'characterIntelligence', 'characterLife', 'characterMana',
    'characterStrengthModifier', 'characterDexterityModifier', 'characterIntelligenceModifier', 'characterLifeModifier',
    'characterManaModifier', 'characterLifeMultModifier', 'characterOffensiveAbility', 'characterDefensiveAbility',
    'characterOffensiveAbilityModifier', 'characterDefensiveAbilityModifier', 'characterLifeRegen', 'characterLifeRegenModifier',
    'characterManaRegenModifier', 'characterConstitutionModifier', 'characterHealIncreasePercent', 'characterTotalSpeedModifier',
    'characterAttackSpeedModifier', 'characterAttackSpeedMaxModifier', 'characterSpellCastSpeedModifier', 'characterSpellCastSpeedMaxModifier',
    'characterRunSpeedModifier', 'characterRunSpeedMaxModifier', 'characterDefensiveBlockRecoveryReduction', 'characterEnergyAbsorptionPercent',
    'characterDodgePercent', 'characterDeflectProjectile', 'characterManaLimitReserve', 'characterManaLimitReserveModifier',
]

# Flat added damage: each present Min/Max is one (min, spread) draw pair, then scaled.
# offensivePhysical is the item's own weapon damage on a Weapon* class -- fixed, no
# draw -- but a real rolled pair on armour and jewellery, so it is gated on Class.
FLAT = [
    'offensivePhysical',
    'offensiveBonusPhysical', 'offensivePierce', 'offensiveFire', 'offensiveCold', 'offensiveLightning',
    'offensivePoison', 'offensiveLife', 'offensiveAether', 'offensiveChaos', 'offensiveElemental',
]

SLOW_FLAT = [
    'offensiveSlowPhysical', 'offensiveSlowBleeding', 'offensiveSlowFire', 'offensiveSlowCold',
    'offensiveSlowLightning', 'offensiveSlowPoison', 'offensiveSlowLife', 'offensiveSlowAether', 'offensiveSlowChaos',
    'offensiveSlowLifeLeach', 'offensiveSlowManaLeach',
]

OFF_REFLEX = ['offensiveStun', 'offensiveKnockdown', 'offensiveSleep', 'offensiveFreeze', 'offensivePetrify',
              'offensiveConfusion']            # NOT IAGD's -- see ADDITIONS
# Confusion's Max draws on its own, straight after (its Min is the OffReflex draw).
REFLEX_MAX = ['offensiveConfusionMax']

# (field, scales): speed slows take the item scale, ability reductions do not.
OFF_SLOW = [
    ('offensiveSlowTotalSpeed', True), ('offensiveSlowAttackSpeed', True),
    ('offensiveSlowSpellCastSpeed', True), ('offensiveSlowRunSpeed', True),
    ('offensiveSlowOffensiveAbility', False), ('offensiveSlowDefensiveAbility', False),
    # NOT IAGD's -- see ADDITIONS. Unscaled: the game shows 13/10/14/11% on four
    # items where a scaled draw gives 18/10/14/13.
    ('offensiveFumble', False),
]

DMG = [
    # NOT IAGD's -- see ADDITIONS. Scaled: 5 reads 7% at attributeScalePercent 30.
    'offensivePercentCurrentLifeMin',
    'offensiveTotalDamageModifier', 'offensiveCritDamageModifier',
    'offensivePhysicalModifier', 'offensivePierceModifier', 'offensiveFireModifier', 'offensiveColdModifier', 'offensiveLightningModifier',
    'offensivePoisonModifier', 'offensiveLifeModifier', 'offensiveAetherModifier', 'offensiveChaosModifier', 'offensiveElementalModifier',
    'offensiveSlowPhysicalModifier', 'offensiveSlowPhysicalDurationModifier',
    'offensiveSlowBleedingModifier', 'offensiveSlowBleedingDurationModifier',
    'offensiveSlowFireModifier', 'offensiveSlowFireDurationModifier',
    'offensiveSlowColdModifier', 'offensiveSlowColdDurationModifier',
    'offensiveSlowLightningModifier', 'offensiveSlowLightningDurationModifier',
    'offensiveSlowPoisonModifier', 'offensiveSlowPoisonDurationModifier',
    'offensiveSlowLifeModifier', 'offensiveSlowLifeDurationModifier',
    'offensiveSlowAetherModifier', 'offensiveSlowChaosModifier',
]

MODIFIER_CHANCE_SPLIT = {
    'offensivePhysicalModifier', 'offensivePierceModifier', 'offensiveFireModifier', 'offensiveColdModifier',
    'offensiveLightningModifier', 'offensivePoisonModifier', 'offensiveLifeModifier', 'offensiveAetherModifier',
    'offensiveChaosModifier', 'offensiveElementalModifier',
}

LEECH = ['offensiveLifeLeech']

OFF_REDUC = [
    'offensivePhysicalReductionPercent', 'offensiveElementalReductionPercent',
    'offensiveTotalDamageReductionPercent', 'offensiveTotalDamageReductionAbsolute',
    'offensiveTotalResistanceReductionPercent', 'offensiveTotalResistanceReductionAbsolute',
    'offensivePhysicalResistanceReductionPercent', 'offensivePhysicalResistanceReductionAbsolute',
    'offensiveElementalResistanceReductionPercent', 'offensiveElementalResistanceReductionAbsolute',
]

RETAL_FLAT = [
    'retaliationPhysical', 'retaliationPierce', 'retaliationFire', 'retaliationCold', 'retaliationLightning',
    'retaliationPoison', 'retaliationLife', 'retaliationAether', 'retaliationChaos', 'retaliationElemental',
]

RETAL_DUR = [
    'retaliationSlowPhysical', 'retaliationSlowPierce', 'retaliationSlowFire', 'retaliationSlowCold',
    'retaliationSlowLightning', 'retaliationSlowPoison', 'retaliationSlowLife', 'retaliationSlowAether',
    'retaliationSlowChaos', 'retaliationSlowBleeding',
]
RETAL_DUR_PCT = ['retaliationSlowAttackSpeed', 'retaliationSlowRunSpeed']

RETAL_MOD = [
    'retaliationTotalDamageModifier',
    'retaliationPhysicalModifier', 'retaliationPierceModifier', 'retaliationFireModifier', 'retaliationColdModifier',
    'retaliationLightningModifier', 'retaliationPoisonModifier', 'retaliationLifeModifier', 'retaliationAetherModifier',
    'retaliationChaosModifier', 'retaliationElementalModifier',
]
# The one retaliation modifier that draws AFTER the Defense store, not with its peers.
RETAL_MULT_POST_DEF = ['retaliationDamageMultModifier']

RETAL_REFLEX = ['retaliationStun', 'retaliationFreeze', 'retaliationConfusion']

# The resistance CAPS (defensive*MaxResist) draw nothing and are absent by design.
DEF = [
    'defensiveBlockModifier', 'defensiveBlockAmountModifier', 'defensiveProtectionModifier',
    'defensiveAbsorptionModifier',
    'defensivePhysical', 'defensivePierce', 'defensiveFire', 'defensiveCold', 'defensiveLightning',
    'defensivePoison', 'defensiveLife', 'defensiveAether', 'defensiveChaos',
    'defensiveElementalResistance', 'defensiveBleeding',
    'defensiveSlowLifeLeach', 'defensiveSlowManaLeach',
    'defensiveManaBurn', 'defensiveAllResistance',
    'defensivePhysicalModifier', 'defensivePierceModifier', 'defensiveFireModifier', 'defensiveColdModifier',
    'defensiveLightningModifier', 'defensivePoisonModifier', 'defensiveLifeModifier', 'defensiveAetherModifier',
    'defensiveChaosModifier', 'defensiveElementalModifier', 'defensiveBleedingModifier',
    'defensiveSlowLifeLeachModifier', 'defensiveSlowManaLeachModifier',
    'defensivePhysicalDuration', 'defensiveFireDuration', 'defensiveColdDuration', 'defensiveLightningDuration',
    'defensivePoisonDuration', 'defensiveLifeDuration', 'defensiveAetherDuration', 'defensiveChaosDuration',
    'defensiveBleedingDuration', 'defensiveSlowLifeLeachDuration', 'defensiveSlowManaLeachDuration',
    'defensivePhysicalDurationModifier', 'defensiveFireDurationModifier', 'defensiveColdDurationModifier',
    'defensiveLightningDurationModifier', 'defensivePoisonDurationModifier', 'defensiveLifeDurationModifier',
    'defensiveAetherDurationModifier', 'defensiveChaosDurationModifier', 'defensiveBleedingDurationModifier',
    'defensiveSlowLifeLeachDurationModifier', 'defensiveSlowManaLeachDurationModifier',
    'defensiveDisruption', 'defensiveStun', 'defensiveStunModifier', 'defensiveFreeze',
    'defensiveTrap', 'defensivePetrify', 'defensiveSleep', 'defensiveSleepModifier',
    'defensiveKnockdown', 'defensiveKnockdownModifier', 'defensiveTaunt', 'defensiveFear',
    'defensiveConfusion', 'defensiveConvert', 'defensiveTotalSpeedResistance', 'defensiveCrowdControl',
    'defensiveReflect', 'defensiveReflectModifier', 'defensivePercentCurrentLife', 'defensivePercentReflectionResistance',
]

BLOCK_FIXED = ['defensiveBlock', 'defensiveBlockChance', 'blockAbsorption', 'blockRecoveryTime']

CONV = ['conversionPercentage', 'conversionPercentage2']

SKILL = [
    'skillCooldownReduction', 'skillManaCostReduction', 'skillComboChargeSpendReduction',
    'skillProjectileSpeedModifier', 'skillCooldownReductionModifier', 'skillManaCostReductionModifier',
]
# These two draw EARLY when they come from an affix -- see draw_skill_early().
SKILL_EARLY = ['skillCooldownReduction', 'skillManaCostReduction']

# Damage modifiers attributeScalePercent does NOT scale. Settled against the
# game's own tooltips (tests/test_seedroll_game.py), 2026-09-28: Crit Damage is
# unscaled on all 142 scaled items that carry it. `offensiveTotalDamageModifier`
# ("% to All Damage") was listed here too, from IAGD by way of gd-lib, and the
# game disagrees: it read low on 53 of 55 scaled items, +44% where the game
# shows +61%. It scales. CORRECTIONS names that departure from gd-lib.
NON_SCALING = {'offensiveCritDamageModifier'}
CORRECTIONS = {'offensiveTotalDamageModifier': 'scales with attributeScalePercent'}

# Fields IAGD (and so gd-lib) refuses, modelled here from the game's own
# tooltips, 2026-09-28. Each is PLACED BUT NOT PINNED: the in-game values bound
# where it draws to a span, as (the ORDER field it draws after, the ORDER field
# it draws before -- None for the end of the order). Inside the span every
# placement gives the same numbers UNLESS some source also carries a field that
# draws inside it -- so compute() REFUSES exactly that item, and every other item
# rolls exactly whichever placement is true. tests/test_seedroll_game.py also
# proves it from the catalogue for the item records carrying one. A field in
# FIXED is modelled as no draw, equally consistent with every placement.
#   offensiveFumble      4 items (Maleficus x2, Madness x2) exact. After the
#                        damage modifiers up to Chaos, before the conversion.
#   defensiveElementalResistanceChance  1 item (Defender of Devil's Crossing).
#                        A chance with no resistance beside it; the game prints
#                        nothing for it. Taken as no draw -- a draw anywhere
#                        after defensiveProtectionModifier matches equally.
#   offensivePercentCurrentLifeMin  1 item (Demonslayer's Life-Ender), "7%
#                        Reduction to Enemy's Health". A scaled scalar, after
#                        the character stats, before the Vitality modifier.
#                        The "Sapping" prefix carries it too, and where an
#                        affix's draw falls against the base's is not settled
#                        by one base-only item -- so an affix carrying it is
#                        still REFUSED (BASE_ONLY).
#   offensiveConfusion   1 item (Magestorm Preserver Warmaul of Insanity), "5%
#                        Chance of Confuse target for 3 - 7 Seconds", from the
#                        suffix "of Insanity". Min and Max are TWO draws -- the
#                        game's detail view rolls both, (2-5)-(4-9) -- and with
#                        one draw the conversion after it reads 33% for the
#                        game's 35%. After the damage modifiers, before the
#                        conversion.
ADDITIONS = {
    'offensiveConfusion': ('offensiveSlowLifeModifier', 'conversionPercentage'),
    'offensiveConfusionMax': ('offensiveSlowLifeModifier', 'conversionPercentage'),
    'offensivePercentCurrentLifeMin': ('characterSpellCastSpeedModifier', 'offensiveLifeModifier'),
    'offensiveFumble': ('offensiveChaosModifier', 'conversionPercentage'),
    'defensiveElementalResistanceChance': ('defensiveProtectionModifier', None),
}
BASE_ONLY = {'offensivePercentCurrentLifeMin'}

# The crafting bonus ROLLS (settled against the game 2026-09-28). It jitters with its
# own lootRandomizerJitter and draws from the item's one stream, so leaving it out
# shifts every later draw: a medal's +8% Health Regeneration reads 9% in game, and its
# Bleeding Resist 23 where the unmodified replay said 20. It draws as one more source
# inside the Char store, BEFORE the base: all 11 crafted items IAGD holds match the
# game with it at any of slots 0-2 of prefix -> suffix -> base, and 2 of 11 fail
# after the base. Slots 0-2 differ only when a prefix or suffix carries the same
# field as the bonus, which none of the 11 does -- so that case is REFUSED rather
# than guessed. The 11 carry Char bonuses only, so only the Char store is pinned;
# a bonus with a damage, defence or retaliation field is REFUSED too.
MODIFIER_KINDS = {'Char'}
MODIFIER_SLOT = 2


def _build_order():
    o = []
    o += [('Char', f, False) for f in CHAR]
    o += [('Flat', f, True) for f in FLAT]
    o += [('SlowFlat', f, True) for f in SLOW_FLAT]
    o += [('Dmg', f, f not in NON_SCALING) for f in DMG]
    o += [('Leech', f, False) for f in LEECH]
    o += [('OffReflex', f, False) for f in OFF_REFLEX]
    o += [('ReflexMax', f, False) for f in REFLEX_MAX]
    o += [('OffSlow', f, sc) for f, sc in OFF_SLOW]
    o += [('OffReduc', f, False) for f in OFF_REDUC]
    o += [('RetalFlat', f, False) for f in RETAL_FLAT]
    o += [('RetalDur', f, False) for f in RETAL_DUR]
    o += [('RetalMod', f, False) for f in RETAL_MOD]
    o += [('RetalDur', f, False) for f in RETAL_DUR_PCT]
    o += [('RetalReflex', f, False) for f in RETAL_REFLEX]
    o += [('Def', f, False) for f in DEF]
    o += [('RetalMod', f, False) for f in RETAL_MULT_POST_DEF]
    o += [('Conv', f, False) for f in CONV]
    o += [('Skill', f, False) for f in SKILL]
    return o


ORDER = _build_order()

_PAIR = {'Flat': ('Min', 'Max'), 'RetalFlat': ('Min', 'Max'), 'SlowFlat': ('Min', 'Max')}
_COMP = {'RetalDur': ('Min', 'DurationMin', 'Chance'), 'RetalReflex': ('Min', 'Chance'),
         'OffReflex': ('Min', 'Chance'), 'OffSlow': ('Min', 'DurationMin', 'Chance'),
         'Leech': ('Min',), 'OffReduc': ('Min', 'DurationMin')}


def _build_modeled():
    m = set()
    for kind, field, _ in ORDER:
        if kind in _PAIR:
            m |= {field + s for s in _PAIR[kind]}
        elif kind in _COMP:
            m |= {field + s for s in _COMP[kind]}
        else:
            m.add(field)
    return m


MODELED = _build_modeled()

# Present on items, never drawn: echoed at the record value.
FIXED = {
    'characterBaseAttackSpeed', 'characterManaRegen', 'characterConstitution', 'characterAttackSpeed',
    'characterSpellCastSpeed', 'characterRunSpeed', 'characterIncreasedExperience', 'characterIncreasedGold',
    'characterLightRadius', 'characterGlobalReqReduction', 'characterLevelReqReduction', 'characterModifierPoints',
    'defensiveProtection',      # armour: 0 draws
    'defensiveElementalResistanceChance',   # see ADDITIONS
}

STAT_PREFIXES = ('offensive', 'defensive', 'retaliation', 'character', 'skill', 'conversion',
                 'blockAbsorption', 'blockRecovery')

COSMETIC_PREFIXES = (
    'augment', 'modif', 'item', 'drop', 'physics', 'mesh', 'bitmap', 'baseTexture', 'bumpTexture', 'glowTexture',
    'shader', 'weaponTrail', 'hitSound', 'swipeSound', 'blockSound', 'attackEffect', 'basicProjectile', 'actor',
    'casts', 'maxTransparency', 'outline', 'scale', 'templateName', 'Class', 'FileDescription', 'levelRequirement',
    'itemLevel', 'armorClassification', 'characterBaseAttackSpeedTag', 'armorFemaleMesh', 'armorMaleMesh',
    'decoration', 'attributeScalePercent', 'petBonusName',
)


def is_fixed(f):
    if f in FIXED or f in BLOCK_FIXED:
        return True
    if f.startswith('character') and f.endswith('ReqReduction'):
        return True
    if f.startswith('offensiveBase') and (f.endswith('Min') or f.endswith('Max')):
        return True          # weapon base damage
    if f.startswith('offensiveSlow') and f.endswith('DurationMin'):
        return True
    # Resistance CAPS. Absent from the Def order table on purpose -- IAGD's own
    # comment there says they draw no RNG -- but absent from its fixed set too, so
    # upstream refuses any item carrying one. A medal with three of them is common
    # enough that refusing is the wrong answer; ASSUMED fixed on that comment alone,
    # not verified against a max-resist reading in game.
    if f.startswith('defensive') and f.endswith('MaxResist'):
        return True
    if f.startswith('offensive') and f.endswith('RatioMin'):
        return True
    if (f.endswith('Chance') and not f.endswith('GlobalChance')
            and f.startswith(('offensive', 'retaliation', 'skill'))):
        return True          # per-proc chance companion
    if f in ('offensiveGlobalChance', 'retaliationGlobalChance'):
        return True
    if f.startswith(('offensive', 'retaliation')) and f.endswith('Global'):
        return True          # grouped-proc flag
    return False


def is_concerning(f):
    """A rollable field this engine does not model. Its presence means the stream
    may have desynced, so the whole item's roll must be discarded."""
    if f.startswith(COSMETIC_PREFIXES):
        return False
    if f in MODELED or is_fixed(f):
        return False
    if f.startswith('conversion'):
        return False         # handled explicitly by the Conv kind
    return f.startswith(STAT_PREFIXES)


def parse_stats(record):
    """A DBR as {field: [values]} -> ({field: float}, {field: str}). A field that is
    not a number is kept only as text (Class and the conversion type names are read
    from there); it never enters the numeric side, so it can never be jittered."""
    values, text = {}, {}
    for k, vs in record.items():
        v = vs[0] if vs else ''
        try:
            values[k] = float(v)
        except ValueError:
            if v:
                text[k] = v
    return values, text


class Roll:
    """stats: field -> rolled value, summed across the item's sources.
    parts: field -> {'base'|'prefix'|'suffix': value}, summing EXACTLY to stats[field].
    unmodeled: rollable fields this engine does not know. NON-EMPTY MEANS DISCARD THE
    WHOLE ROLL -- a missed draw makes every later value wrong while leaving it
    perfectly plausible.
    conversions: every damage conversion the item carries, as {field, in, out,
    value}, in draw order. stats[<field>] holds only the FIRST pair's value; an
    item whose base and affix convert different types has two, and the game
    prints both (four items in IAGD, 8 of 8 values exact, 2026-09-28)."""

    def __init__(self, stats, parts, unmodeled, proc_lines, conversions=()):
        self.stats, self.parts = stats, parts
        self.unmodeled, self.proc_lines = unmodeled, proc_lines
        self.conversions = list(conversions)


def _drawn_fields(entry):
    """The record fields an ORDER entry draws for -- companions it only echoes
    (a Chance, a DurationMin) excluded."""
    kind, field, _ = entry
    if kind in _PAIR:
        return {field + s for s in _PAIR[kind]}
    if kind in _COMP:
        return {field + 'Min'}
    return {field}


def _span_conflicts(sources):
    """An ADDITION present on the item, and a field some source draws strictly
    inside its span: the one case where the placement changes the numbers."""
    present = {f for src in sources for f, v in src.items() if v}
    pos = {}
    for i, entry in enumerate(ORDER):
        for f in _drawn_fields(entry):
            pos.setdefault(f, i)
    names = {e[1]: i for i, e in enumerate(ORDER)}
    out = []
    for add, (after, before) in ADDITIONS.items():
        mine = [e for e in ORDER if e[1] == add]
        if not mine or not (_drawn_fields(mine[0]) & present):
            continue
        lo, hi = names[after], names[before] if before else len(ORDER)
        inside = sorted(f for f in present if f in pos and lo < pos[f] < hi
                        and ORDER[pos[f]][1] not in ADDITIONS)
        if inside:
            out.append(f'{add} [placement unpinned: {inside[0]} draws inside its span]')
    return out


def compute(base, seed, prefix=None, suffix=None, scale_override=None, modifier=None):
    """Roll one item. `base`/`prefix`/`suffix`/`modifier` are raw DBRs as `rec()`
    returns them; `modifier` is the crafting bonus (see MODIFIER_KINDS).

    Draw order across sources is per-store and NOT uniform: Char, Skill and the
    retaliation modifiers draw prefix -> suffix -> base (the base LAST), while the
    damage and defence stores draw base first. Each source jitters with its OWN
    percent -- an affix uses its `lootRandomizerJitter`, and an affix that declares
    none does not jitter at all.

    ⚠️ THE PER-SOURCE SPLIT IS RECONSTRUCTED, THE TOTAL IS NOT. Each source's own
    jittered draw is real, but the item scale is applied to their SUM and truncated
    once, so the parts cannot all be scaled independently and still add up. The
    largest part absorbs that sub-1 residue, which is what keeps `sum(parts) ==
    stats` exact -- the invariant the whole sheet rests on."""
    values, text = parse_stats(base)
    has_p, has_s = prefix is not None, suffix is not None
    p_values, p_text = parse_stats(prefix) if has_p else ({}, {})
    s_values, s_text = parse_stats(suffix) if has_s else ({}, {})
    has_m = modifier is not None
    m_values, _ = parse_stats(modifier) if has_m else ({}, {})
    mod_pct = m_values.get('lootRandomizerJitter', 0.0)

    pfx_pct = p_values.get('lootRandomizerJitter', 0.0)
    sfx_pct = s_values.get('lootRandomizerJitter', 0.0)
    sp = (scale_override if scale_override is not None
          else values.get('attributeScalePercent', 0.0)
          + p_values.get('lootRandomizerScale', 0.0) + s_values.get('lootRandomizerScale', 0.0))

    rng = Minstd(seed)
    result, parts, proc_lines, handled_dur = {}, {}, [], set()
    conversions = []
    is_offhand = text.get('Class') == 'WeaponArmor_Offhand'

    SRC = ('base', 'prefix', 'suffix')

    def part(field, which, value):
        if value:
            parts.setdefault(field, {})[which] = parts.setdefault(field, {}).get(which, 0.0) + value

    def present(f):
        return f in values or f in p_values or f in s_values or f in m_values

    # An affix's skillCooldownReduction/skillManaCostReduction draws at the START of
    # the damage store, not at the deferred Skill position where the base record's
    # own copy draws. Missing this desyncs every draw in between.
    pfx_has_skill = has_p and any(f in p_values for f in SKILL_EARLY)
    sfx_has_skill = has_s and any(f in s_values for f in SKILL_EARLY)
    state = {'early_done': not (pfx_has_skill or sfx_has_skill), 'early': {}}

    def draw_skill_early():
        if state['early_done']:
            return
        state['early_done'] = True
        for which, src, pct, active in (('prefix', p_values, pfx_pct, pfx_has_skill),
                                        ('suffix', s_values, sfx_pct, sfx_has_skill)):
            if not active:
                continue
            for f in SKILL_EARLY:
                if f in src:
                    j = jitter_skill(src[f], pct, rng)
                    state['early'][f] = state['early'].get(f, 0.0) + j
                    part(f, which, j)

    def echo_fixed(field, comps):
        """DurationMin / Chance companions: 0 draws, taken from the first source that
        declares one, base first."""
        for comp in comps:
            cf = field + comp
            for which, src in zip(SRC, (values, p_values, s_values)):
                if cf in src:
                    result[cf] = src[cf]
                    part(cf, which, src[cf])
                    break

    for kind, field, scales in ORDER:
        min_f, max_f = field + 'Min', field + 'Max'

        if kind in ('Flat', 'SlowFlat', 'RetalFlat'):
            if kind == 'Flat' and field == 'offensivePhysical' and text.get('Class', '').startswith('Weapon'):
                # A weapon's own physical damage: 0 draws, shown at the base range.
                # Echoed rather than skipped -- the sheet's flat-damage rows read it,
                # and dropping it silently disarms the character.
                for f in (min_f, max_f):
                    if f in values:
                        result[f] = values[f]
                        part(f, 'base', values[f])
                continue
            if kind == 'SlowFlat':
                if is_offhand:
                    continue
                # A base Min with no DurationMin cannot render "over N seconds": no draw.
                if min_f in values and (field + 'DurationMin') not in values:
                    continue
            if not any(f in src for src in (values, p_values, s_values) for f in (min_f, max_f)):
                continue
            draw_skill_early()
            ch_f = field + 'Chance'
            tot_min = tot_spread = 0.0
            any_drawn = False
            for which, src, pct, active, is_base in (('base', values, BASE_JITTER, True, True),
                                                     ('prefix', p_values, pfx_pct, has_p, False),
                                                     ('suffix', s_values, sfx_pct, has_s, False)):
                if not active or (min_f not in src and max_f not in src):
                    continue
                if kind == 'Flat' and not is_base and is_offhand:
                    continue                      # off-hand destroys an affix's flat damage
                mn, mx = src.get(min_f, 0.0), src.get(max_f, 0.0)
                j_min = jitter_char(mn, pct, rng)
                j_spread = jitter_char(max(0.0, mx - mn), pct, rng)
                # A source with its own Chance is a separate proc line, not part of the
                # merged total -- only when affixes are in play, since a base-only item
                # has nothing to merge with.
                if kind in ('Flat', 'SlowFlat') and (has_p or has_s) and ch_f in src:
                    s_min = _trunc(apply_scale(j_min, sp))
                    s_max = _trunc(s_min + j_spread)
                    proc_lines.append(dict(field=field, min=s_min, max=None if s_max == s_min else s_max,
                                           duration=src.get(field + 'DurationMin'), chance=src[ch_f]))
                    continue
                any_drawn = True
                tot_min += j_min
                tot_spread += j_spread
                part(min_f, which, j_min)
                part(max_f, which, j_min + j_spread)
            if not any_drawn:
                continue
            scaled = tot_min if kind == 'RetalFlat' else apply_scale(tot_min, sp)
            result[min_f] = _trunc(scaled)
            result[max_f] = _trunc(scaled + tot_spread)

        elif kind in ('RetalDur', 'RetalReflex', 'OffReflex', 'Leech', 'OffSlow', 'OffReduc'):
            if not present(min_f):
                continue
            draw_skill_early()
            tot = 0.0
            for which, src, pct, active in (('base', values, BASE_JITTER, True),
                                            ('prefix', p_values, pfx_pct, has_p),
                                            ('suffix', s_values, sfx_pct, has_s)):
                if active and min_f in src:
                    j = jitter_char(src[min_f], pct, rng)
                    tot += j
                    part(min_f, which, j)
            if kind == 'OffSlow':
                result[min_f] = apply_scale(tot, sp) if scales else _round_away(tot)
            elif kind in ('RetalDur', 'OffReflex'):
                result[min_f] = _round_away(tot)
            else:                                  # RetalReflex, Leech, OffReduc: no scale, no round
                result[min_f] = tot
            echo_fixed(field, _COMP[kind][1:])

        elif kind == 'Conv':
            sfx = '2' if field.endswith('2') else ''
            in_key, out_key = 'conversionInType' + sfx, 'conversionOutType' + sfx
            acc, acc_order = {}, []
            for which, src, src_text, pct, active in (('base', values, text, BASE_JITTER, True),
                                                      ('prefix', p_values, p_text, pfx_pct, has_p),
                                                      ('suffix', s_values, s_text, sfx_pct, has_s)):
                if not active:
                    continue
                v = src.get(field, 0.0)
                in_type = src_text.get(in_key, '')
                if not in_type or v == 0.0:
                    continue                       # invalid pair: destroyed, no draw
                draw_skill_early()
                key = (in_type, src_text.get(out_key, ''))
                if key not in acc:
                    acc_order.append(key)
                j = jitter_conversion(v, pct, rng)
                acc[key] = acc.get(key, 0.0) + j
                if key == acc_order[0]:
                    part(field, which, j)
            if not acc_order:
                continue
            result[field] = acc[acc_order[0]]
            conversions += [{'field': field, 'in': i, 'out': o, 'value': acc[(i, o)]}
                            for i, o in acc_order]

        else:                                      # Char / Dmg / Def / RetalMod / Skill scalars
            if not present(field):
                continue
            if kind != 'Char':
                draw_skill_early()
            if kind == 'Dmg' and field in handled_dur:
                continue                           # drawn as half of its Slow pair
            bv = values.get(field, 0.0)
            pv, sv = p_values.get(field, 0.0), s_values.get(field, 0.0)

            if (kind == 'Dmg' and field.startswith('offensiveSlow') and field.endswith('Modifier')
                    and not field.endswith('DurationModifier')):
                dur_f = field[:-len('Modifier')] + 'DurationModifier'
                if present(dur_f):
                    # One object per source, so a source draws its (value, duration) pair
                    # CONSECUTIVELY -- not all values and then all durations.
                    v_tot = d_tot = 0.0
                    for which, src, pct, active in (('base', values, BASE_JITTER, True),
                                                    ('prefix', p_values, pfx_pct, has_p),
                                                    ('suffix', s_values, sfx_pct, has_s)):
                        if not active:
                            continue
                        jv = jitter_char(src.get(field, 0.0), pct, rng)
                        jd = jitter_char(src.get(dur_f, 0.0), pct, rng)
                        v_tot += jv
                        d_tot += jd
                        part(field, which, jv)
                        part(dur_f, which, jd)
                    result[field] = apply_scale(v_tot, sp) if scales else v_tot
                    result[dur_f] = apply_scale(d_tot, sp)
                    handled_dur.add(dur_f)
                    continue

            if kind == 'Skill':
                if field in SKILL_EARLY and (pfx_has_skill or sfx_has_skill):
                    bj = jitter_skill(bv, BASE_JITTER, rng)
                    part(field, 'base', bj)
                    result[field] = state['early'].get(field, 0.0) + bj
                    continue
                pj = jitter_skill(pv, pfx_pct, rng) if has_p else 0.0
                sj = jitter_skill(sv, sfx_pct, rng) if has_s else 0.0
                bj = jitter_skill(bv, BASE_JITTER, rng)
            elif kind in ('Dmg', 'Def', 'RetalMod', 'ReflexMax'):
                bj = jitter_char(bv, BASE_JITTER, rng)
                pj = jitter_char(pv, pfx_pct, rng) if has_p else 0.0
                sj = jitter_char(sv, sfx_pct, rng) if has_s else 0.0
            else:                                  # Char: the base draws LAST
                order = [('prefix', pv, pfx_pct, has_p), ('suffix', sv, sfx_pct, has_s),
                         ('base', bv, BASE_JITTER, True)]
                if has_m:
                    order.insert(MODIFIER_SLOT, ('modifier', m_values.get(field, 0.0), mod_pct, True))
                drawn = {w: jitter_char(v, pct, rng) if on else 0.0 for w, v, pct, on in order}
                pj, sj, bj = drawn['prefix'], drawn['suffix'], drawn['base']
                mj = drawn.get('modifier', 0.0)
                part(field, 'modifier', mj)
                total = pj + sj + bj + mj
                for which, j in (('base', bj), ('prefix', pj), ('suffix', sj)):
                    part(field, which, j)
                result[field] = apply_scale(total, sp) if scales else total
                continue

            if field in MODIFIER_CHANCE_SPLIT and (has_p or has_s):
                ch_f = field + 'Chance'
                tot, any_plain = 0.0, False
                for which, src, j in (('base', values, bj), ('prefix', p_values, pj), ('suffix', s_values, sj)):
                    if field not in src:
                        continue
                    if src.get(ch_f, 0) > 0:
                        proc_lines.append(dict(field=field, min=apply_scale(j, sp) if scales else j,
                                               max=None, duration=None, chance=src[ch_f]))
                    else:
                        any_plain = True
                        tot += j
                        part(field, which, j)
                if any_plain:
                    result[field] = apply_scale(tot, sp) if scales else tot
                continue

            for which, j in (('base', bj), ('prefix', pj), ('suffix', sj)):
                part(field, which, j)
            total = pj + sj + bj
            result[field] = apply_scale(total, sp) if scales else total

    # Fields that never draw are echoed at their record value; anything rollable and
    # unknown is reported, and the caller must then throw the whole roll away.
    unmodeled = []
    for f in set(values) | set(p_values) | set(s_values):
        if f in result:
            continue
        if is_fixed(f) and f.startswith(STAT_PREFIXES):
            for which, src in zip(SRC, (values, p_values, s_values)):
                if f in src:
                    result[f] = src[f]
                    part(f, which, src[f])
                    break
        elif is_concerning(f):
            unmodeled.append(f)
    unmodeled += [f + ' [on an affix: placement unpinned]' for f in BASE_ONLY
                  if f in p_values or f in s_values]
    unmodeled += _span_conflicts([values, p_values, s_values, m_values])
    # A crafting bonus is modelled for the stores its draws were pinned in and
    # nowhere else: a field of any other kind refuses the whole roll.
    kinds = {f: k for k, f, _ in ORDER}
    unmodeled += [f + ' [crafting bonus and an affix share it: draw order unpinned]'
                  for f in m_values if kinds.get(f) in MODIFIER_KINDS
                  and (f in p_values or f in s_values)]
    for f in m_values:
        if f in result and kinds.get(f) in MODIFIER_KINDS:
            continue
        if is_concerning(f) or (f in MODELED and kinds.get(f) not in MODIFIER_KINDS):
            unmodeled.append(f + ' [crafting bonus: draw order unpinned]')

    # The parts are per-source draws; the total had one scale-and-truncate applied to
    # their sum. Hand the difference to the largest part so the two agree exactly.
    for f, total in result.items():
        got = parts.get(f)
        if not got:
            continue
        residue = total - sum(got.values())
        if residue:
            biggest = max(got, key=lambda k: abs(got[k]))
            got[biggest] += residue

    return Roll(result, parts, sorted(unmodeled), proc_lines, conversions)


# The roll engine's inputs that are NOT player stats, so `is_stat` drops them and the
# baked index has to be told to keep them anyway. Numeric first, then the text fields.
ROLL_INPUTS = ('attributeScalePercent', 'lootRandomizerJitter', 'lootRandomizerScale')
ROLL_TEXT = ('Class', 'conversionInType', 'conversionOutType',
             'conversionInType2', 'conversionOutType2')


def tables():
    """The draw order and the field sets, for the browser engine to read.

    ⚠️ SHIPPED, NOT REWRITTEN. `rolls.js` implements the same control flow against
    THIS data; keeping the tables in one place is what stops the two engines from
    drifting a field apart -- three bugs in this project have come from a rule
    corrected on one side only (gd-lens-engine-parity)."""
    return {
        'order': [[k, f, 1 if sc else 0] for k, f, sc in ORDER],
        'pair': {k: list(v) for k, v in _PAIR.items()},
        'comp': {k: list(v) for k, v in _COMP.items()},
        'fixed': sorted(FIXED),
        'blockFixed': list(BLOCK_FIXED),
        'skillEarly': list(SKILL_EARLY),
        'modSplit': sorted(MODIFIER_CHANCE_SPLIT),
        'statPrefixes': list(STAT_PREFIXES),
        'cosmeticPrefixes': list(COSMETIC_PREFIXES),
        'modeled': sorted(MODELED),
        'baseJitter': BASE_JITTER,
        'text': list(ROLL_TEXT),
        'inputs': list(ROLL_INPUTS),
    }
