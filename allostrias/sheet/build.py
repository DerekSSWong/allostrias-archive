#!/usr/bin/env python3
"""Build the character-sheet bundle from allostrias-archive alone.

  profile.sqlite    who the character is, what is worn, what is invested
  catalogue.sqlite  what those record paths MEAN -- names, rarities, stat rows
  database.arz      the records themselves, via archive/records.py
  resources/*.arc   the icons, the frame, and the display strings
  seedroll.py       the port that turns a stored centre into the value rolled

⚠️ NOTHING HERE READS ANOTHER PROJECT'S OUTPUT. It used to: records and tags
came from `.extracted/`, a text tree gd-lib writes into the game directory, so
allostrias could not build on an install where gd-lib had never run. Both now
come from the archives the archive already parses -- and `.extracted` turned
out to be a SNAPSHOT three days older than the shipped archives, so this is a
correctness change as much as an independence one. tests/test_records.py holds
the two readers to each other wherever the snapshot is still current.

The one piece the archive did not already have is seed replay, ported in beside
this file rather than imported; gd-lib appears nowhere outside a test oracle.

THE PAGE COMPUTES THE SHEET, NOT THIS SCRIPT. What ships is a CONTRIBUTION LIST
-- every stat field with every value feeding it, each tagged with where it came
from and which toggle (if any) gates it. A sheet computed here would be a
photograph: the toggles could not move it, and the whole point of the toggles is
that they do.
"""
import base64
import fnmatch
import io
import json
import os
import re
import sqlite3

from PIL import Image, ImageChops

from . import seedroll
from .. import item_stats
from .. import settings as S
from ..archive import arc
from ..archive.records import Records
from ..archive.textures import Textures

cfg = S.load()
ARCHIVE = S.ROOT
# Build output, and it carries the icon atlas -- Crate's art, which must never
# become committable. cache/ is gitignored for exactly that reason and
# tests/test_no_graphics.py fails if anything graphical is ever staged.
OUT = os.path.join(ARCHIVE, 'cache', 'sheet')

RECORDS = Records(cfg.arz_paths)

# Attachment columns: separate records fed in unrolled. seedroll covers the
# item's own record plus prefix and suffix and nothing else.
# How a worn slot reads in a source label: `Impervious (Shoulders)`.
SLOT_LABEL = {'head': 'Head', 'amulet': 'Amulet', 'chest': 'Chest', 'shoulders': 'Shoulders',
              'hands': 'Hands', 'legs': 'Legs', 'feet': 'Feet', 'waist': 'Waist',
              'ring1': 'Ring 1', 'ring2': 'Ring 2', 'medal': 'Medal', 'relic': 'Relic',
              'mainhand': 'Main Hand', 'offhand': 'Off Hand'}
ATTACH = ('component_path', 'modifier_path', 'transmute_path',
          'relic_bonus_path', 'augment_path')

# A buff the player can have up or down. Keyed on the CLASS of the record the
# player invested in, or of the record its buffSkillName points at.
#
# ⚠️ `SkillBuff_Debuf*` IS DELIBERATELY ABSENT. Those land on the enemy, and
# folding one into the player's sheet is the mistake this project has already
# made once -- an enemy's shredded Defensive Ability is not the player's.
TOGGLE_CLASSES = {
    'Skill_BuffSelfToggled', 'Skill_BuffRadiusToggled', 'Skill_BuffSelfDuration',
    'Skill_BuffRadius', 'Skill_BuffAttackRadiusToggled', 'Skill_Shapeshift',
    'SkillBuff_Passive', 'Skill_BuffSelfShield',
}
# Always on, no question: the player cannot turn a mastery bar or a bound
# constellation off.
PERMANENT_CLASSES = {'Skill_Mastery', 'Skill_Passive'}


def rec(path):
    """One record, or None when no archive defines it.

    Shape and formatting are `.extracted`'s -- defaults dropped, floats at the
    precision the .dbr was authored with -- because every rule below was
    written against that shape. See archive/records.py for why a raw archive
    read is not a drop-in replacement.
    """
    return RECORDS.get(path) if path else None


# The archive's own tag loader, which EXCLUDES tags_console.txt. That file
# redefines ~193 tags with gamepad wording -- "[Press Y to Combine]" where the
# mouse build says "[Right-Click to Combine]" -- and `.extracted` merged it in,
# so the sheet used to print controller prompts on a desktop page. 196 tags
# change wording because of this and every one of them changes toward what this
# player's game actually shows.
TAGS = arc.load_tags(cfg.text_arc_paths)


def tag(t, default=None):
    if not t:
        return default
    v = TAGS.get(t, default)
    if not v:
        return default
    # Colour codes belong to the game's renderer, not to a name -- and they come
    # in TWO spellings. `{^X}` is the documented one; a bare `^X` prefix is not,
    # and it rendered a component as "^kLiving Armor".
    v = re.sub(r'\{\^.\}|\^.', '', v.split('{^')[0] if '{^' in v else v)
    return v.strip() or default


def png_b64(im, quantize=0):
    if quantize:
        im = im.quantize(colors=quantize, method=Image.FASTOCTREE)
    b = io.BytesIO()
    im.save(b, 'PNG', optimize=True)
    return 'data:image/png;base64,' + base64.b64encode(b.getvalue()).decode()


# ---------------------------------------------------------------- stats ----
# Every field the sheet can read. Anything outside this set is dropped at build
# time rather than shipped, because a contribution list nothing renders is
# weight the page pays for and never spends.
STAT_PREFIX = ('character', 'defensive', 'offensive', 'retaliation', 'skill')


# `skill` prefixes a handful of real stats AND a great deal of record metadata
# -- skillMaxLevel, skillTier, skillTargetRadius, skillCooldownTime. A blacklist
# of the metadata seen so far is the wrong shape: the next unlisted one is swept
# in silently and summed into a number with no meaning. Whitelist instead, so an
# unfamiliar skill* field is dropped rather than trusted.
SKILL_STATS = {'skillCooldownReduction', 'skillCooldownReductionChance',
               'skillManaCostReduction', 'skillLifeBonus', 'skillManaBonus'}


def wanted(field):
    if field.startswith('skill'):
        return field in SKILL_STATS
    return field.startswith(STAT_PREFIX)


# What produced a contribution. Three of these are STRONG in the verdict's
# sense -- a skill, a component and an augment are each a slot the player chose
# deliberately -- and the unrolled gear kinds are the ones fed in at their
# stored centre rather than replayed from the item's seed, which is what the
# resistance rule needs a margin for.
GEAR_UNROLLED = ('component', 'augment', 'crafting bonus', 'completion bonus',
                 'transmuted')


class Contrib:
    """field -> [[value, source label, toggle id or None, kind], ...]

    The toggle id is what makes the sheet live. A value with `None` is
    structural -- gear, a mastery bar, a bound constellation -- and cannot be
    switched off in game, so the page never offers to.

    The KIND is what the verdict engine counts with: corroboration asks how many
    independent, freely-chosen sources point at a damage type, and "the player
    socketed a component for this" is a different fact from "the base item
    happened to roll it".
    """

    def __init__(self):
        self.rows = {}

    def add(self, field, value, source, toggle=None, kind='item', via=None):
        """`via` is the RECORD the numbers were actually read from, and only
        the pet bucket carries it.

        A devotion node grants a stat to the player AND the same stat to pets
        from two DIFFERENT records -- and the two can carry the same number,
        so neither the source label nor the value can tell the buckets apart.
        Ulo the Keeper of the Waters gives +15 Petrify Resist to both. `via` is
        what can: a pet contribution names its petbonus record, and nothing in
        the player bucket may name one.

        Appended rather than inserted, so the page's `[v, src, tid]`
        destructuring and check.js's `r[3]` are untouched by its presence.
        """
        if not value or not wanted(field):
            return
        row = [round(float(value), 4), source, toggle, kind]
        if via:
            row.append(via)
        self.rows.setdefault(field, []).append(row)


# ============================================================ pets ========
# The game has a PET BONUSES tab (tagCharHeaderPets), and what it lists are
# BONUSES granted to pets -- "+70% Damage to your pets" -- never a pet's
# totals. That distinction is the whole reason these can be summed at all: a
# pet's own base stats live on its creature record and differ per pet, so a
# total is not a quantity this reader could state, while the bonus is.
#
# ⚠️ A SECOND BUCKET, NOT MORE ROWS IN THE FIRST. Folding "+70% Damage" into
# the player's damage rows is a category error every downstream total would
# inherit, so these never touch `C`.
#
# THREE CHANNELS GRANT THEM, and the middle one is the one that hides:
#   gear         a worn item, affix, component, augment or relic whose record
#                carries petBonusName. Scalar, folds at index 0.
#   item skill   the SKILL a worn item grants, which carries petBonusName on
#                itself. Never in the save's skill list, so walking gear and
#                walking invested skills both miss it from their own side.
#   bought skill an invested skill or devotion node carrying petBonusName. The
#                target stores one value PER RANK, so it folds at the effective
#                rank the same way player skill stats do.
#
# DELIBERATELY EXCLUDED: SkillSecondary_PetModifier (Will of the Crypt, Rotting
# Fumes), reached by a one-hop petSkillName. Those buff ONE pet type and the
# game keeps them on the skill; folding them in would put a skeleton-only
# +142% Elemental on a row that says "all pets" -- a wrong number rather than a
# missing one.
#
# Unlike GD Lens's engine this takes no `active` buff set. It carries the same
# toggle id the player contributions carry and lets the PAGE decide what is
# switched on, which is this build's whole architecture and means the two tabs
# cannot disagree about whether a source is running.
def pet_stats_at(P, target, index, source, toggle=None, kind='item'):
    """Fold one petbonus record into the pet bucket. True if it had anything."""
    d = rec(target)
    if not d:
        return False
    added = False
    for f, vals in d.items():
        if not wanted(f):
            continue
        try:
            arr = [float(v) for v in vals]
        except ValueError:
            continue                          # a path or a tag, never a stat
        v = arr[index] if index < len(arr) else arr[-1]
        if v:
            # `via` is the petbonus record the numbers were actually read from.
            # A devotion node legitimately grants a stat to the player AND the
            # same stat to pets from two DIFFERENT records, so the source path
            # alone cannot tell the buckets apart.
            P.add(f, v, source, toggle, kind=kind, via=target)
            added = True
    return added


def pet_target(path):
    """The petbonus record a record points at, or None."""
    d = rec(path) if path else None
    return (d.get('petBonusName') or [None])[0] if d else None


def record_name(d, path):
    """An item record's display name.

    ⚠️ NOT EVERY ITEM NAMES ITSELF THROUGH `itemNameTag`. A relic carries none
    and uses `description` instead -- `d201_relic.dbr` is "Meditation" -- and so
    do the components. Reading only itemNameTag renders the filename, which is
    what the relic slot and every component line were showing.
    """
    for f in ('itemNameTag', 'description'):
        n = tag((d.get(f) or [None])[0])
        if n:
            return n
    return None


def affix_of(ca, path, kind):
    """(printed name, classification) for an affix, or (None, None) for none.

    Never returns a None NAME for a path that exists: an affix the save carries
    but this cannot name is still ON the item, and dropping it from the name
    would print a plain base and look exactly like an item that has no affix --
    the bug this function exists to fix.
    """
    if not path:
        return None, None
    r = ca.execute('select name, rarity from affix where path=?', (path,)).fetchone()
    return ((r['name'] if r and r['name'] else None) or f'unnamed {kind}',
            r['rarity'] if r else None)


# The nameplate badges. There is no icon field on an item: every one of these
# is a COMPUTED state, and gameiteminfo.dbr holds one texture per state. The
# only per-item inputs are the base's itemClassification and the two affixes'.
#   MI          -- base is Rare. Green from the BASE.
#   double rare -- rare prefix AND rare suffix. Green from the AFFIXES.
# The game states the partition itself: tagTutorialTip69TextB says Monster
# Infrequents are a subset of Rare, and tagLootFilter39 names the double-rare
# pair. Anything else green is a plain Rare, which carries no badge.
def quality(base_cls, pfx_cls, sfx_cls):
    """(displayed tier, badge) from the three classifications."""
    mi = base_cls == 'Rare'
    double = pfx_cls == 'Rare' and sfx_cls == 'Rare'
    badge = ('drmi' if mi and double else 'dr' if double else 'mi' if mi else None)
    if base_cls in ('Epic', 'Legendary', 'Quest'):
        tier = base_cls            # uniques do not roll affixes
    elif mi or pfx_cls == 'Rare' or sfx_cls == 'Rare':
        tier = 'Rare'
    elif pfx_cls or sfx_cls:
        tier = 'Magical'
    else:
        tier = base_cls
    return tier, badge


# An item's icon field is named after its CLASS, not after "bitmap". Ordinary
# gear carries `bitmap`; a relic is an ItemArtifact and carries `artifactBitmap`
# instead, which is why every relic rendered with no graphic. Checked over all
# of records/items: no record declares two of these, so first-hit is
# unambiguous. The other three names belong to kinds this sheet does not draw --
# components (relic/shardBitmap), transmuters (full/emptyBitmap) and lore notes
# (noteBitmap) -- and are listed so the next empty tile is recognisable.
ICON_FIELDS = ('bitmap', 'artifactBitmap')


def item_icon(base):
    """The icon path for a worn item, or None if the record declares none."""
    for f in ICON_FIELDS:
        v = (base.get(f) or [None])[0]
        if v:
            return v
    return None


def skill_mods(ca, d):
    """`+N to <skill>` lines from a record's augmentSkill/augmentMastery pairs.

    These already fed the skill tree through plus_skill; this is only the
    printed form, which the gear tooltip never had.
    """
    out = []
    for i in range(1, 9):
        n, l = d.get(f'augmentSkillName{i}'), d.get(f'augmentSkillLevel{i}')
        if n and l:
            out.append(f'+{int(float(l[0]))} {skill_name(ca, n[0], rec(n[0]) or {})}')
        n, l = d.get(f'augmentMasteryName{i}'), d.get(f'augmentMasteryLevel{i}')
        if n and l:
            out.append(f'+{int(float(l[0]))} to all {skill_name(ca, n[0], rec(n[0]) or {})} skills')
    return out


def bonus_lines(ca, d):
    """A relic's completion bonus, as lines. Stats and skill grants both --
    two of the four worn here carry only skill grants, so a numbers-only
    reader prints nothing and the bonus looks absent rather than unread."""
    if not d:
        return []
    return stat_lines({k: float(v[0]) for k, v in d.items()
                       if wanted(k) and v and _num(v[0])}, {}) + skill_mods(ca, d)


def _num(x):
    try:
        float(x); return True
    except (TypeError, ValueError):
        return False


def class_title(masteries):
    """`Sentinel`, `Reaver` -- what the game calls a mastery combination.

    Derived from the class numbers, not from a table of names typed here: the
    tag is tagSkillClassName followed by the ids in ascending order. Returns
    None when there is no tag rather than inventing one, so an untitled
    combination shows nothing instead of something plausible.
    """
    ids = sorted((re.search(r'playerclass(\d+)', m['path']).group(1)
                  for m in masteries if re.search(r'playerclass(\d+)', m['path'])))
    if not ids:
        return None
    return tag('tagSkillClassName' + ''.join(ids)) or None


def set_bonus(setrec, worn):
    """The set's bonus at `worn` pieces: (stat values, [(skill path, level)]).

    ⚠️ THE TIER ENCODING IS RIGHT-ALIGNED AND THE RECORD NOWHERE SAYS SO. A set
    with M members has M-1 bonus slots, (2) through (M), and a stat's
    `;`-separated array fills the LAST len(array) of them. Left-aligning
    produces an equally well-formed answer with every bonus on the wrong tier
    and nothing looking broken -- see the Explorer's Garments decode that
    established this against an in-game block.

    A single value is therefore the FULL-SET bonus, not the 2-piece one.

    ⚠️ ASSUMED, NOT CONFIRMED: non-numeric fields (a granted skill) carry no
    array and are treated as full-set only, the same as a one-value stat. Every
    set worn here is worn complete, so nothing in this data can tell that apart
    from "active from 2 pieces"; check_sheet.js pins that.
    """
    # rec() has already split on ';', so every field is a list and its LENGTH
    # is the number of tiers the bonus covers.
    members = [m for m in (setrec.get('setMembers') or []) if m]
    M = len(members)
    if worn < 2 or M < 2:
        return {}, [], members
    slot = worn - 2                      # 0-based index into tiers (2)..(M)
    stats, skills = {}, []
    for field, arr in setrec.items():
        if not (wanted(field) and arr):
            continue
        first = (M - 1) - len(arr)       # right-aligned: covers the LAST len(arr)
        if first < 0:
            # More values than the set has tiers. Not a shape seen in any
            # record here, and guessing which end to trim is exactly the
            # mistake this decode exists to avoid -- so say so and stop.
            raise SystemExit(
                f'{field} carries {len(arr)} values for a {M}-member set '
                f'({M - 1} tiers): the tier encoding is not what this assumes')
        if slot < first:
            continue
        if slot - first >= len(arr):
            # Unreachable with the right-aligned arithmetic above; if it fires,
            # the alignment has been changed and is now reading off the end.
            raise SystemExit(
                f'{field}: tier {worn} reads index {slot - first} of {len(arr)} '
                f'-- the tier alignment is wrong, see gate_setbonus.py')
        try:
            v = float(arr[slot - first])
        except ValueError:
            continue
        if v:
            stats[field] = stats.get(field, 0) + v
    for i in range(1, 9):
        n, l = setrec.get(f'augmentSkillName{i}'), setrec.get(f'augmentSkillLevel{i}')
        if n and l and worn == M:        # see the assumption above
            skills.append((n[0], int(float(l[0]))))
    return stats, skills, members


def item_display(base, path, pfx=(None, None), sfx=(None, None)):
    """(name, rarity, style) for a worn item.

    ⚠️ itemStyleTag is what separates a Mythical from its base -- they share
    itemNameTag, so the name alone names two different items.

    ⚠️ AN AFFIXED ITEM IS NOT ITS BASE. The prefix and suffix wrap the base
    name, style word included -- `Warding Mythical Redeemer Gauntlets of
    Heroism`. Reading only the base printed 49 of 77 worn items as if they had
    rolled nothing at all.

    `rarity` is the DISPLAYED tier, not the base's itemClassification: a
    common base with a rare affix is a green item, and reading the base alone
    printed 27 of these as plain white.
    """
    name = record_name(base, path) or os.path.basename(path).replace('.dbr', '')
    style = tag(base.get('itemStyleTag', [None])[0])
    rarity, badge = quality((base.get('itemClassification') or [None])[0],
                            pfx[1], sfx[1])
    if style and name and not name.startswith(style):
        name = f'{style} {name}'
    base_name = name
    name = ' '.join(x for x in (pfx[0], name, sfx[0]) if x)
    return name, rarity, style, base_name, badge


def stat_lines(values, text):
    """Readable lines for an item tooltip, from the ROLLED values.

    This used to be a 107-field table of its own, and anything outside it was
    silently not printed -- honest, but it left 94 of the 185 fields actually
    present on six characters' gear off the tooltip. It now runs the ported
    renderer ([[allostrias.item_stats]]), which covers what the game prints.

    ⚠️ THE RENDERER TAKES RECORD TEXT AND THESE ARE ROLLED NUMBERS, so the
    values are rendered back into the `field=value` shape it parses. That is
    not a workaround: it is the same shape `.extracted` holds and the same one
    `Records.text()` emits, and it is what lets a tooltip show the value this
    item actually rolled rather than the centre its record stores.

    `%g` matches how records are written, so a rolled 4.0 prints as `4` and
    reaches the renderer exactly as a stored 4 would.

    The sheet's own numbers still never come from here -- they come from the
    contribution list, which is keyed on raw field names.
    """
    if not values:
        return []
    nums = {k: v for k, v in values.items() if isinstance(v, (int, float))}
    # ⚠️ DROP A `Max` THAT EQUALS ITS `Min`. seedroll emits both halves of a
    # range even where the record carries only the Min -- Avatar of Order
    # stores `retaliationFireMin=260` and nothing else, and rolls to 306/306.
    # The renderer prints a pair as a range whenever both are present, so
    # feeding it that synthesises "+306-306 Fire Retaliation" for a stat the
    # game shows as "+306". Real records do not look like that, and this is the
    # one place the synthetic text could stop looking like a record.
    nums = {k: v for k, v in nums.items()
            if not (k.endswith('Max') and nums.get(k[:-3] + 'Min') == v)}
    synthetic = '\n'.join(f'{k}={v:g}' for k, v in sorted(nums.items())) + '\n'
    return item_stats.process_stats(synthetic)


def fmt_num(v):
    return f'{v:g}' if abs(v - round(v)) > 1e-9 else str(int(round(v)))


# ---------------------------------------------------------------- sheet ----
# The sheet is DATA, shipped to the page, so the labels a gear tooltip prints
# and the labels a sheet row prints come from one table and cannot disagree.
#
# `k` is how a row gets its number:
#   attr/pool/ability  a solved formula, applied in the page
#   mod                sum of `f`, then x (1 + sum of `f`+"Modifier" / 100)
#   sum                plain sum
#   resist             plain sum, then the difficulty penalty, capped display
#
# ⚠️ `verified` MARKS WHERE THE NUMBER CAME FROM, NOT HOW CONFIDENT IT LOOKS.
# True only for the five formulas checked against a real character sheet. A
# `sum` row is what the records add up to and has never been compared with what
# the game prints -- the page says so rather than letting a tidy number imply a
# verification that did not happen.
# ⚠️ `f` IS NOT EVERY FIELD THE ROW READS. Four of the kinds finish with a
# PERCENTAGE MULTIPLIER whose field is `f[0] + "Modifier"`, and that field used
# to be spelled out nowhere: the page re-derived the name inside each formula,
# and everything else that walks this table -- the gear tooltip's stat lines,
# the row's own hover detail -- simply did not know it existed. Two things went
# wrong from that and both looked like nothing at all: Nazeem's +80% Health
# Regeneration and his armour's +8% were absent from both tooltips, and an item
# whose ONLY bonus was one of these read as an item with no bonus.
#
# So the row names it. `m` is the one place that field is written down, and
# every reader takes it from here.
MOD_KINDS = {'attr', 'pool', 'ability', 'mod'}


def R(label, f=None, k='sum', pct=False, verified=False, **kw):
    r = {'label': label, 'k': k, 'pct': pct}
    if f:
        r['f'] = f if isinstance(f, list) else [f]
    if k in MOD_KINDS:
        if not r.get('f'):
            raise SystemExit(f'{label}: a {k} row needs a field to hang its modifier on')
        r['m'] = r['f'][0] + 'Modifier'
    if verified:
        r['v'] = 1
    r.update(kw)
    return r


DMG = [('Physical', 'Physical'), ('Fire', 'Fire'), ('Cold', 'Cold'),
       ('Lightning', 'Lightning'), ('Acid', 'Poison'), ('Pierce', 'Pierce'),
       ('Vitality', 'Life'), ('Aether', 'Aether'), ('Chaos', 'Chaos')]

# ============================================================ verdicts ====
# ⚠️ EVERY NUMBER IN THIS BLOCK IS ASSERTED, NOT DERIVED.
#
# `status: ASSERTED` · `source: ported verbatim from GD Lens's targets.py, which
# states them as community consensus on endgame Ultimate gearing, interpolated
# down by level. NOT derived from the game database and NOT verified against
# anything.`
#
# Everything else this build emits comes out of the save or the extracted
# database. These are judgement calls about what a character OUGHT to have,
# which is not a question the database can answer -- there is no record anywhere
# saying a level 100 Sentinel wants 2600 Defensive Ability.
#
# ⚠️ AND THEY ARE A SECOND COPY. GD Lens keeps the originals and this page may
# not import from it, so `gate_targets.py` diffs the two whenever GD Lens is
# checked out beside this build, and FAILS on any drift. A copied constant that
# nothing compares is exactly how two tools start recommending different things
# while both look right.
TARGETS = {
    'sigma': 25,
    'resistSigma': 80,
    'residual': 0.11,
    'damageTypes': 3,
    'damageFloor': 0.10,
    'retaliationDamageFloor': 0.05,
    'strongKinds': ['skill', 'component', 'augment'],
    'corroboration': 1,
    'channelSupport': 5,
    'petBuildDamage': 250,
    'mechanismDominance': 0.5,
    'control': {
        'Stun Resist': 80, 'Freeze Resist': 80, 'Trap Resist': 60,
        'Slow Resist': 60, 'Life Leech Resist': 20, 'Petrify Resist': 80,
        'Sleep Resist': 0, 'Disruption Resist': 60, 'Energy Leech Resist': 0,
        'Reflect Resist': 0,
    },
    'endgame': {'OffensiveAbility': 2500, 'DefensiveAbility': 2600,
                'ArmorRating': 2800, 'Health': 16000},
    'pct': {'PhysicalResist': 28, 'ChanceToBlock': 60},
    'levelFloor': 0.35,
    'diffScale': {'0': 0.55, '1': 0.78, '2': 1.0},
}
# Sheet-only verdict constants. GD Lens has no such rule, so they stay out of
# TARGETS -- the copy the drift gate compares -- and are merged in at bundling.
SHEET_TARGETS = {
    # A damage type under this share of EITHER pool -- the Bonus Damage rows
    # summed, or the Damage Modifiers rows summed -- is `avoid` on both rows.
    'poolFloor': 0.10,
    # A type with MORE than this % globally converted straight into one of the
    # build's main types is Neutral on its flat row, not Avoid.
    'convertedToMain': 50,
}

# The game's own type words, and the two it spells differently from the sheet.
CONV_TYPE = {'Poison': 'Acid', 'Life': 'Vitality'}
ELEMENTAL_SPLIT = ('Fire', 'Cold', 'Lightning')
# Which stem carries a type's direct damage, its damage over time and its
# retaliation -- the three channels the verdict counts investment in.
DAMAGE_FIELD = {n: f'offensive{s}' for n, s in DMG}
DOT_FIELD = {'Bleed': 'offensiveSlowBleeding', 'Burn': 'offensiveSlowFire',
             'Frostburn': 'offensiveSlowCold', 'Electrocute': 'offensiveSlowLightning',
             'Poison': 'offensiveSlowPoison', 'Trauma': 'offensiveSlowPhysical',
             'Vitality Decay': 'offensiveSlowLife'}
DOT_OUTPUT_TYPE = {'Bleed': 'Bleeding', 'Burn': 'Fire', 'Frostburn': 'Cold',
                   'Electrocute': 'Lightning', 'Poison': 'Acid',
                   'Trauma': 'Physical', 'Vitality Decay': 'Vitality'}
RETAL_FIELD = {n: f'retaliation{s}Min' for n, s in DMG}
RETAL_FIELD.update({'Elemental': 'retaliationElementalMin',
                    'Burn': 'retaliationSlowFireMin',
                    'Electrocute': 'retaliationSlowLightningMin',
                    'Trauma': 'retaliationSlowPhysicalMin',
                    'Poison': 'retaliationSlowPoisonMin'})
RETAL_TYPE_MOD = {'Fire': 'retaliationFireModifier',
                  'Lightning': 'retaliationLightningModifier',
                  'Physical': 'retaliationPhysicalModifier',
                  'Acid': 'retaliationPoisonModifier'}
RESIST_FIELDS = {n: [f'defensive{s}'] + (['defensiveElementalResistance']
                                         if n in ('Fire', 'Cold', 'Lightning') else [])
                 for n, s in DMG}
RESIST_FIELDS['Bleeding'] = ['defensiveBleeding']
RESIST_MAX = {n: f'defensive{s}MaxResist' for n, s in DMG if n != 'Physical'}
RESIST_MAX['Bleeding'] = 'defensiveBleedingMaxResist'

# A damage CHANNEL is one type delivered one way. Ported from
# stats.damageChannel(): the flat range, the percentage and the DoT duration all
# hang off one stem, so the stem is the unit a player invests in.
INVEST_PREFIX = ('offensive', 'retaliation')
# % All Damage multiplies every type at once and so is an investment in NONE.
INVEST_IGNORE = ('offensiveTotalDamage', 'retaliationTotalDamage')
CHANNEL_SUFFIX = ('DurationModifier', 'DurationMin', 'DurationMax',
                  'Modifier', 'Chance', 'Min', 'Max')


def damage_channel(f):
    if not f.startswith(INVEST_PREFIX) or f.startswith(INVEST_IGNORE):
        return None
    for suf in CHANNEL_SUFFIX:
        if len(f) > len(suf) and f.endswith(suf):
            # offensiveBase<Type> folds into offensive<Type>: a weapon's own
            # swing and a flat bonus added to it are one channel to invest in.
            return f[:-len(suf)].replace('offensiveBase', 'offensive')
    return None


def conversion_pairs(path):
    """`(inType, outType, per-rank percentages)` off a record, both slots.

    A ';'-joined type is the editor's dropdown rather than a conversion, and is
    refused here the way both GD Lens engines refuse it.
    """
    d = rec(path) if path else None
    if not d:
        return []
    out = []
    for suf in ('', '2'):
        i = (d.get('conversionInType' + suf) or [None])[0]
        o = (d.get('conversionOutType' + suf) or [None])[0]
        p = d.get('conversionPercentage' + suf)
        if i and o and p and ';' not in i and ';' not in o:
            try:
                out.append((i, o, [float(x) for x in p]))
            except ValueError:
                continue
    return out


def real_pets(skills):
    """The invested skills whose summons can actually USE a pet bonus.

    ⚠️ NOT EVERY SUMMON IS A PET HERE, and the difference is the whole verdict.
    The game declares two classes: `Class=Pet` scales off pet bonuses, while
    `Class=PetPlayerScaling` inherits the PLAYER's -- Guardian of Empyrion,
    Blade Spirit, Wind Devil and every totem are the latter, and pet bonuses do
    nothing for them however many the gear happens to grant. Characters here
    field one and no real pet at all, so "has spawnObjects" would hand them a
    whole tab of advice nothing can spend -- tests/test_pet_bonuses.py names
    which. This is the game's own class declaration, not a structural proxy
    ([[structural-proxy-is-not-evidence]]); GD Lens's real_pets() reads it the
    same way.

    Scope: INVESTED skills. A summon granted by an item is not counted -- the
    same scope GD Lens has, stated rather than silently assumed.
    """
    out = set()
    for s in skills:
        if s['eff'] <= 0:
            continue
        for target in (rec(s['path']) or {}).get('spawnObjects') or []:
            if ((rec(target) or {}).get('Class') or [''])[0] == 'Pet':
                out.add(s['n'])
                break
    return sorted(out)


def damage_context(worn, skills, C):
    """Everything the verdict needs about damage, resolved here rather than on
    the page: all of it walks game records, which the page cannot read.

    Ported from stats.js's conversions(), conversionIntent(), damageInvestment()
    and the resistUnrolled half of verdictContext().

    ⚠️ ONE DELIBERATE DIVERGENCE. GD Lens finds a modifier's parent by matching
    the record-name STEM, which merges unrelated skills; this build already
    resolves parentage for the mastery panels -- `skillDependancy`, then the
    display-tag family -- and uses the same two steps. Same question, better
    answer, and the answer only decides whether a transmuter's conversion is
    global or scoped to one attack.
    """
    by_path = {s['path']: s for s in skills}
    heads = {}
    for s in skills:
        m = TAG_FAMILY.match(display_tag(s['path']) or '')
        if m and m.group(3) == 'A':
            heads[m.group(1, 2)] = s

    def parent_always_on(path):
        p = next((by_path[d] for d in dependencies(rec(path) or {}) if d in by_path), None)
        if p is None:
            # A transmuter often declares no dependency at all -- Wereraven's
            # Talons of Cthon is one -- and hangs off its family's `A` skill.
            m = TAG_FAMILY.match(display_tag(path) or '')
            p = heads.get(m.group(1, 2)) if m else None
            if p is not None and p['path'] == path:
                p = None
        if p is None:
            return False
        return p['cls'] == 'Skill_Passive' or 'Toggled' in p['cls'] \
            or p['cls'] == 'Skill_Shapeshift'

    gear = []
    for r in worn:
        for col in ('base_path', 'prefix_path', 'suffix_path') + ATTACH:
            if r[col]:
                gear.append(r[col])

    # ---- conversions actually running, and what they say the player INTENDS --
    conv, intent = {}, []

    def take_conv(path, idx, into):
        for i, o, vals in conversion_pairs(path):
            v = vals[idx] if idx < len(vals) else vals[-1]
            if not v:
                continue
            into(CONV_TYPE.get(i, i), CONV_TYPE.get(o, o), v)

    def add_conv(src, dst, v):
        conv[f'{src}|{dst}'] = conv.get(f'{src}|{dst}', 0) + v

    for p in gear:
        take_conv(p, 0, add_conv)
    for s in skills:
        if s['eff'] <= 0 or s['dev']:
            continue
        d = rec(s['path']) or {}
        buff = (d.get('buffSkillName') or [None])[0]
        cls = s['cls']
        is_mod = cls in ('Skill_Modifier', 'Skill_Transmuter')
        glob = not is_mod or parent_always_on(s['path'])
        if cls == 'Skill_Passive' or 'Toggled' in cls or (is_mod and glob):
            take_conv(buff or s['path'], s['eff'] - 1, add_conv)
        # The INTENT list is wider: every conversion a skill with points in it
        # grants, whatever its parent is doing. A transmuter on an attack is the
        # clearest statement there is about what a build means to deal.
        pet = 'Pet' in cls or '/pets/' in s['path']
        for p in (s['path'], buff):
            take_conv(p, s['eff'] - 1,
                      lambda a, b, v: intent.append([a, b, v, pet, glob]))

    # ---- where the points and the sockets WENT ------------------------------
    # INVESTMENT, not output: a skill the player bought counts whether or not it
    # is running, and the unit is the stat LINE, so zero support and thin support
    # can be told apart.
    fed = {}

    def take_invest(path, idx):
        if not path or '/pets/' in path:
            return
        d = rec(path)
        if not d:
            return
        for f, vals in d.items():
            ch = damage_channel(f)
            if not ch:
                continue
            try:
                arr = [float(x) for x in vals]
            except ValueError:
                continue
            v = arr[idx] if idx < len(arr) else arr[-1]
            if v:
                fed[ch] = fed.get(ch, 0) + 1
        # A conversion INTO a type feeds that type's DIRECT channel and only
        # that one: no conversion field anywhere names a DoT, and retaliation is
        # converted by its own separate fields.
        for i, o, vals in conversion_pairs(path):
            v = vals[idx] if idx < len(vals) else vals[-1]
            if not v:
                continue
            t = CONV_TYPE.get(o, o)
            for one in (ELEMENTAL_SPLIT if t == 'Elemental' else (t,)):
                if one in DAMAGE_FIELD:
                    fed[DAMAGE_FIELD[one]] = fed.get(DAMAGE_FIELD[one], 0) + 1

    for p in gear:
        take_invest(p, 0)
        granted = ((rec(p) or {}).get('itemSkillName') or [None])[0]
        if granted:
            take_invest(granted, 0)
            take_invest(((rec(granted) or {}).get('buffSkillName') or [None])[0], 0)
    for s in skills:
        if s['eff'] <= 0 or '/itemskills' in s['path'] or '/default/' in s['path']:
            continue
        take_invest(s['path'], max(0, s['eff'] - 1))
        take_invest(((rec(s['path']) or {}).get('buffSkillName') or [None])[0],
                    max(0, s['eff'] - 1))
    # % Elemental names Fire, Cold and Lightning, so it feeds all three.
    for ch in list(fed):
        if 'Elemental' in ch:
            for e in ELEMENTAL_SPLIT:
                k = ch.replace('Elemental', e)
                fed[k] = fed.get(k, 0) + fed[ch]

    # ---- how much of each resistance is still a GUESS ----------------------
    # A seed-rolled contribution is the real value and needs no margin. What is
    # left is components, augments, crafting bonuses and completion bonuses --
    # the gear kinds fed in at their stored centre.
    unrolled = {}
    for t, fields in RESIST_FIELDS.items():
        n = 0.0
        for f in fields:
            for v, _src, _tid, kind in C.rows.get(f, []):
                if kind in GEAR_UNROLLED:
                    n += abs(v)
        unrolled[t] = round(n, 4)

    return {'conv': conv, 'intent': intent, 'invested': fed, 'resistUnrolled': unrolled}


# Display name -> the game's internal stem. `Life` is Vitality and `Poison` is
# Acid; the field names are actively misleading and the sheet uses the words
# the game prints.
SHEET = [
    ('Attributes', [
        R('Physique', 'characterStrength', k='attr', verified=True, attr='physique'),
        R('Cunning', 'characterDexterity', k='attr', verified=True, attr='cunning'),
        R('Spirit', 'characterIntelligence', k='attr', verified=True, attr='spirit'),
        R('Health', 'characterLife', k='pool', verified=True, pool='health'),
        R('Energy', 'characterMana', k='pool', verified=True, pool='energy'),
    ]),
    ('Combat', [
        R('Offensive Ability', 'characterOffensiveAbility', k='ability',
          verified=True, attr='cunning'),
        R('Defensive Ability', 'characterDefensiveAbility', k='ability',
          verified=True, attr='physique'),
        R('Attack Speed', 'characterAttackSpeedModifier', pct=True),
        R('Cast Speed', 'characterSpellCastSpeedModifier', pct=True),
        R('Movement Speed', 'characterRunSpeedModifier', pct=True),
        R('Total Damage', 'offensiveTotalDamageModifier', pct=True),
        R('Crit Damage', 'offensiveCritDamageModifier', pct=True),
        R('Cooldown Reduction', 'skillCooldownReduction', pct=True),
        R('Energy Cost Reduction', 'skillManaCostReduction', pct=True),
        R('Total Speed', 'characterTotalSpeedModifier', pct=True),
        # A COST, and printed without a leading + in game. Reserved energy is
        # what an aura charges you for keeping it up, so it belongs beside the
        # toggles' own numbers rather than being invisible.
        R('Energy Reserved', 'characterManaLimitReserve'),
    ]),
    ('Defence', [
        R('Armor', 'defensiveProtection', k='mod'),
        R('Armor Absorption', 'defensiveAbsorptionModifier', pct=True),
        R('Damage Absorption', 'defensiveBonusProtection'),
        R('Block Chance', 'defensiveBlockChance', pct=True),
        R('Damage Blocked', 'defensiveBlock'),
        R('Block Recovery', 'characterDefensiveBlockRecoveryReduction', pct=True),
        # character*, not defensive* -- a defensive* spelling sums to a silent 0.
        R('Dodge Chance', 'characterDodgePercent', pct=True),
        R('Deflect Chance', 'characterDeflectProjectile', pct=True),
        R('Health Regeneration', 'characterLifeRegen', k='mod'),
        R('Energy Regeneration', 'characterManaRegen', k='mod'),
    ]),
    # ⚠️ BLEEDING IS A RESIST AND IS NOT IN `DMG`. There is no Bleeding damage
    # modifier -- bleeding is a damage-over-time -- so a resist list built from
    # the damage types alone silently omits one of the nine.
    ('Resistances', [R(n, [f'defensive{s}'] + (['defensiveElementalResistance']
                        if n in ('Fire', 'Cold', 'Lightning') else []),
                       k='resist', pct=True) for n, s in DMG]
                  + [R('Bleeding', 'defensiveBleeding', k='resist', pct=True)]),
    ('Control Resistances', [
        R('Stun', 'defensiveStun', k='resist', pct=True),
        R('Freeze', 'defensiveFreeze', k='resist', pct=True),
        R('Petrify', 'defensivePetrify', k='resist', pct=True),
        R('Trap', 'defensiveTrap', k='resist', pct=True),
        R('Disruption', 'defensiveDisruption', k='resist', pct=True),
        R('Slow', 'defensiveTotalSpeedResistance', k='resist', pct=True),
    ]),
    ('Bonus Damage', [R(n, [f'offensive{s}Min', f'offensive{s}Max'], k='range')
                      for n, s in DMG]),
    # % Elemental is part of the game's Fire, Cold and Lightning modifiers, the
    # same way Elemental Resist is part of each resist row above.
    ('Damage Modifiers', [R(n, [f'offensive{s}Modifier']
                            + (['offensiveElementalModifier'] if n in ELEMENTAL_SPLIT else []),
                            pct=True) for n, s in DMG]),
    ('Damage over Time Modifiers', [
        R(n, f'offensiveSlow{s}Modifier', pct=True)
        for n, s in [('Burn', 'Fire'), ('Frostburn', 'Cold'), ('Electrocute', 'Lightning'),
                     ('Poison', 'Poison'), ('Bleeding', 'Bleeding'),
                     ('Vitality Decay', 'Life'), ('Internal Trauma', 'Physical')]
    ]),
    ('Retaliation', [
        R('Total Retaliation Damage', 'retaliationTotalDamageModifier', pct=True),
    ] + [R(n, [f'retaliation{s}Min', f'retaliation{s}Max'], k='range') for n, s in DMG]),
    # The game's own words (tagCharStatsDamageToHealth / DamageReflect /
    # CurrentLifeReflect). ⚠️ offensiveLifeLeechMin is LIFE STEAL -- "% of Attack
    # Damage converted to Health" -- not the game's Life Leech, which is a
    # different stat; GD Lens labels this field Life Leech.
    ('Leech and Reflect', [
        R('Life Steal', 'offensiveLifeLeechMin', pct=True),
        R('Damage Reflect', 'damageAbsorptionReflectPercent', pct=True),
        R('Life Retaliation', 'offensivePercentCurrentLifeMin', pct=True),
    ]),
    # The bonus ON TOP of the base 80 -- the same fields the resist rule reads
    # its caps from. No Physical row: nothing in the game grants one.
    ('Max Resistances', [R('All', 'defensiveAllMaxResist', pct=True)]
                        + [R(n, f, pct=True) for n, f in RESIST_MAX.items()]),
    ('Misc', [
        R('Light Radius', 'characterLightRadius', pct=True),
        R('Experience Gained', 'characterIncreasedExperience', pct=True),
    ]),
]

# Item tooltip lines reuse the sheet's own labels wherever a field appears on
# it, so a gear panel and a sheet row never name the same field differently.
# A row's additive fields, then the percentage one it finishes with. `m` is
# ALWAYS a percentage, whatever the row's own `pct` says -- `pct` describes the
# number the row prints, and an Armor row prints flat armour while the field
# that scales it is a percent.
#
# This used to name the three attribute modifiers by hand, because attrTotal
# folds them in and nothing walked them; the other seven were still missing.
# Taking them off `m` catches all ten and cannot fall behind the table again.
# ------------------------------------------------------------ verdicts ----
# Which branch of the verdict engine judges each row. Ported from GD Lens's
# SECTION_RULE/ROW_RULE, mapped BY MEANING rather than by section name -- its
# "Defense" section holds the control resists this sheet keeps in a section of
# its own.
#
# ⚠️ `none` IS A VERDICT AND `withheld` IS NOT. `none` means the engine has an
# opinion and the opinion is "no advice here" -- a cost, or a row that is not
# character power. Nothing is withheld on this page today; the constant exists
# because the damage rules WOULD have to be, if the profile they judge against
# could not be computed, and a withheld row must render no icon at all rather
# than the neutral one. Neutral is a judgement; a blank is the absence of one.
SECTION_RULE = {
    'Attributes': 'linear', 'Combat': 'linear', 'Defence': 'linear',
    'Resistances': 'resist', 'Control Resistances': 'control',
    'Bonus Damage': 'linear', 'Damage Modifiers': 'linear',
    'Damage over Time Modifiers': 'linear', 'Retaliation': 'linear',
    'Leech and Reflect': 'linear', 'Max Resistances': 'linear',
    # 'Misc' has NO section rule on purpose: its rows are stamped one by one
    # below, so a row added there without a decision fails the build.
}
# A row in one of these is stamped with the damage TYPE it is about, which is
# what lets the linear rule promote the type a build actually deals and call a
# dead channel `avoid`. The aggregate rows carry none: "Total Retaliation
# Damage" spans every type and judging it against one would be wrong in both
# directions.
# The two sections whose rows form the pools SHEET_TARGETS['poolFloor'] reads.
POOL_SECTIONS = ('Bonus Damage', 'Damage Modifiers')
TYPED_SECTIONS = ('Bonus Damage', 'Damage Modifiers',
                  'Damage over Time Modifiers', 'Retaliation')
DOT_TYPE = {'Burn': 'Fire', 'Frostburn': 'Cold', 'Electrocute': 'Lightning',
            'Poison': 'Acid', 'Bleeding': 'Bleeding', 'Vitality Decay': 'Vitality',
            'Internal Trauma': 'Physical'}
DAMAGE_TYPE_NAMES = {n for n, _ in DMG} | {'Bleeding'}
# HOW the damage is delivered -- a separate question from what type it is.
MECHANISM = {'Retaliation': 'retaliation', 'Bonus Damage': 'hit',
             'Damage Modifiers': 'hit', 'Damage over Time Modifiers': 'hit'}
ROW_RULE = {
    ('Attributes', 'Health'): ('benchmark', 'Health'),
    ('Combat', 'Offensive Ability'): ('benchmark', 'OffensiveAbility'),
    ('Combat', 'Defensive Ability'): ('benchmark', 'DefensiveAbility'),
    ('Defence', 'Armor'): ('benchmark', 'ArmorRating'),
    ('Defence', 'Block Chance'): ('benchmark', 'ChanceToBlock'),
    # Physical Resist is NOT under the resist rule with the other nine. It takes
    # no difficulty penalty at any difficulty and its nominal 80 cap is
    # unreachable in practice, so distance-to-cap would rank it above every real
    # hole. It gets a benchmark instead. (GD Lens's reasoning, kept verbatim.)
    ('Resistances', 'Physical'): ('benchmark', 'PhysicalResist'),
    # A COST, not character power: more energy reserved is not better, so there
    # is nothing to advise. Same call GD Lens makes for Energy Regeneration.
    ('Combat', 'Energy Reserved'): 'none',
    ('Defence', 'Energy Regeneration'): 'none',
    # Not character power. Nothing to advise (GD Lens makes the same call).
    ('Misc', 'Light Radius'): 'none',
    ('Misc', 'Experience Gained'): 'none',
}
# The control targets are keyed by the game's full stat name; this sheet's
# labels drop the word every row in the section shares.
CONTROL_LABEL = {n: n + ' Resist' for n in
                 ('Stun', 'Freeze', 'Petrify', 'Trap', 'Disruption', 'Slow')}



# ---- Pet Bonuses ---------------------------------------------------------
# The game's own tab (tagCharHeaderPets) and its own labels (tagCharStatsPet*).
# Every row is a BONUS granted to pets, never a pet total -- see pet_stats_at().
#
# ⚠️ PET RESIST BONUSES CAP AT 80, confirmed twice against the game's own tab:
# rows summing 108 and 90 both displayed exactly 80, while every row under 80
# matched. Unlike the player's resists there is no difficulty penalty and no
# per-type maximum to add; it is a flat ceiling on the BONUS.
#
# ⚠️ THERE IS NO ARMOUR ROW, and the warning was there when one was invented in
# GD Lens: no tagCharStatsPetArmor string exists, so the player's label had to
# be borrowed to satisfy the label gate. A row whose LABEL has to come from
# another section is a row the game does not have.
PET_RESIST = [('Fire', ['defensiveFire', 'defensiveElementalResistance']),
              ('Cold', ['defensiveCold', 'defensiveElementalResistance']),
              ('Lightning', ['defensiveLightning', 'defensiveElementalResistance']),
              ('Acid', ['defensivePoison']),
              ('Pierce', ['defensivePierce']),
              ('Vitality', ['defensiveLife']),
              ('Aether', ['defensiveAether']),
              ('Chaos', ['defensiveChaos']),
              ('Bleeding', ['defensiveBleeding']),
              ('Physical', ['defensivePhysical'])]
PET_CONTROL = [('Stun', 'defensiveStun'), ('Freeze', 'defensiveFreeze'),
               ('Petrify', 'defensivePetrify'), ('Trap', 'defensiveTrap'),
               ('Sleep', 'defensiveSleep'),
               ('Slow', 'defensiveTotalSpeedResistance')]
PET_ROWS = [
    R('Damage', 'offensiveTotalDamageModifier', pct=True),
    R('Offensive Ability', 'characterOffensiveAbilityModifier', pct=True),
    R('Defensive Ability', 'characterDefensiveAbilityModifier', pct=True),
    R('Life', 'characterLifeModifier', pct=True),
    R('Attack Speed', 'characterAttackSpeedModifier', pct=True),
    R('Cast Speed', 'characterSpellCastSpeedModifier', pct=True),
    R('Run Speed', 'characterRunSpeedModifier', pct=True),
    R('Critical Damage', 'offensiveCritDamageModifier', pct=True),
] + [R(f'{lbl} Resist', fs, pct=True, cap=80) for lbl, fs in PET_RESIST] \
  + [R(f'{lbl} Resist', f, pct=True, cap=80) for lbl, f in PET_CONTROL]

SHEET.append(('Pet Bonuses', PET_ROWS, 'pet'))

def _apply_rules():
    """Stamp every row with its verdict branch, and fail loudly if one is missed.

    A row with no rule would render an icon with no reasoning behind it -- the
    same silent default the `no plausible fallbacks` rule exists to prevent.
    """
    for sec, rows, bucket in ((t + ('',))[:3] for t in SHEET):
        if bucket:
            # ⚠️ ONE BRANCH FOR THE WHOLE BUCKET, and it asks a different
            # question from every other rule here. There is no published
            # endgame target for "+70% pet Damage" and inventing one would be a
            # judgement the game does not make, so the pet rule never grades a
            # value against a number: it asks whether the character has a
            # summon that can use the bonus at all, and whether the pets ARE
            # the build. Same rule and same section-wide stamp as GD Lens's
            # sheet.py. See verdict()'s `pet` branch in shell.html.
            for r in rows:
                r['rule'] = 'pet'
            continue
        for r in rows:
            rule = ROW_RULE.get((sec, r['label']), SECTION_RULE.get(sec))
            if isinstance(rule, tuple):
                rule, r['tkey'] = rule
            if rule is None:
                raise SystemExit(f'no verdict rule for {sec}/{r["label"]}')
            if rule == 'control':
                key = CONTROL_LABEL.get(r['label'])
                if key not in TARGETS['control']:
                    raise SystemExit(f'{sec}/{r["label"]} has no control target')
                r['tkey'] = key
            r['rule'] = rule
            if sec in TYPED_SECTIONS:
                t = DOT_TYPE.get(r['label'], r['label'])
                if t in DAMAGE_TYPE_NAMES:
                    r['dtype'] = t
                    if sec in POOL_SECTIONS:
                        r['dmgPool'] = sec
                if MECHANISM.get(sec):
                    r['mech'] = MECHANISM[sec]


_apply_rules()

SHEET_LINES = []
for _sec, _rows, *_ in SHEET:
    for _r in _rows:
        for _f in _r.get('f', []):
            SHEET_LINES.append((_f, _r['label'], _r['pct']))
        if _r.get('m'):
            SHEET_LINES.append((_r['m'], _r['label'], True))
SHEET_LINES = list(dict.fromkeys(SHEET_LINES))



# ------------------------------------------------------------ gathering ----
def skill_name(ca, path, d, srow=None):
    """A skill's display name, following the wrapper chain.

    ⚠️ ONE HOP IS NOT ENOUGH. A toggled aura's name frequently lives on the
    `*_buff.dbr` it points at rather than on the record the player invested in
    -- `presenceofvirtue1.dbr` carries no `skillDisplayName` at all, so a
    single lookup renders the filename and the buff panel reads as debug output.
    """
    srow = srow if srow is not None else ca.execute(
        'select name from skill where path=?', (path,)).fetchone()
    if srow and srow['name']:
        return srow['name']
    seen, cur, curd = set(), path, d
    for _ in range(4):
        n = tag((curd.get('skillDisplayName') or [None])[0])
        if n:
            return n
        nxt = (curd.get('buffSkillName') or curd.get('petSkillName') or [None])[0]
        if not nxt or nxt in seen:
            break
        seen.add(nxt)
        row = ca.execute('select name from skill where path=?', (nxt,)).fetchone()
        if row and row['name']:
            return row['name']
        cur, curd = nxt, (rec(nxt) or {})
    return os.path.basename(path).replace('.dbr', '')


# A round node in the skill tree is a transmuter, and a transmuter has no art
# of its own -- the game draws one shared glyph for all of them.
TRANSMUTER_ICON = 'skills/icons/skillicon_transmuter01up.tex'
DEVOTION_ICON = 'skills/icons/skillicon_devotionstar01_up.tex'


def skill_icon(d, cls=None):
    """A skill's icon, following the same buffSkillName hop the stats take.

    ⚠️ AN AURA'S ICON IS ON ITS BUFF RECORD, NOT ON THE SKILL THE PLAYER
    INVESTED IN. `bloodofdreeg1.dbr` and `presenceofvirtue1.dbr` carry no
    bitmap field at all; `bloodofdreeg1_buff.dbr` carries
    `skillicon_bloodofdreeg1up.tex`. Reading only the parent left six of
    Nurgle's eleven buffs with no icon -- including both of the ones that
    actually move his sheet.
    """
    seen, cur = set(), d
    for _ in range(4):
        for f in ('skillUpBitmapName', 'skillDownBitmapName'):
            if cur.get(f):
                return cur[f][0]
        nxt = (cur.get('buffSkillName') or cur.get('petSkillName') or [None])[0]
        if not nxt or nxt in seen:
            break
        seen.add(nxt)
        cur = rec(nxt) or {}
    # Still nothing: fall back on the glyph the game itself shares.
    if cls == 'Skill_Transmuter':
        return TRANSMUTER_ICON
    return None


# ---------------------------------------------------------------- tree ----
# Reconstructing a mastery panel, in the order of authority established by an
# earlier pass over every playerclassNN record:
#
#   1. `skillDependancy` on the SKILL record -- the real edge, and where it
#      disagrees with the family it wins.
#   2. the display tag family `tagClass{NN}SkillName{DD}{L}` -- `A` is the head,
#      and B/C/D are its modifiers and transmuters.
#   3. `bitmapPositionY/X` on the UI button record -- ORDERING ONLY. The
#      connector lines are painted into the panel background and cannot be read;
#      nothing here infers a relationship from proximity.
#
# ⚠️ THE FILENAME STEM LOOKS RIGHT AND IS WRONG. It reproduces 65 of 78 families
# and errs both ways -- it splits `shadowstrike` from `shadowstrike_mod1` and
# merges `passive1/2/3`, which are three unrelated skills. Not reintroduced.
TAG_FAMILY = re.compile(r'^tag(?:GDX\d+)?Class(\d+)SkillName(\d+)([A-Z])$')


def display_tag(path):
    """The family tag, following the same hop the name and the icon take.

    A buff or pet skill carries no tag of its own; it lives on what its
    `buffSkillName`/`petSkillName` points at.
    """
    seen, cur = set(), rec(path) or {}
    for _ in range(4):
        t = (cur.get('skillDisplayName') or [None])[0]
        if t and TAG_FAMILY.match(t):
            return t
        nxt = (cur.get('buffSkillName') or cur.get('petSkillName') or [None])[0]
        if not nxt or nxt in seen:
            break
        seen.add(nxt)
        cur = rec(nxt) or {}
    return None


def dependencies(d):
    """`skillDependancy`, spelled the way the game spells it.

    ⚠️ MISSPELLED -- "Dependancy". Searching for the correct spelling returns
    nothing, which is how this field stayed hidden through a whole earlier pass.
    It is also a `;`-separated LIST whose values can carry a stray trailing
    separator, so a raw read yields a path that does not exist and an edge that
    vanishes with no error. rec() already drops the empty fragments.
    """
    return [x for x in d.get('skillDependancy', []) if x]


def button_positions():
    """skill record path -> (y, x) from records/ui/skills/classNN/skill*.dbr.

    Layout only. Two skills being adjacent on the panel says nothing about
    whether one modifies the other.
    """
    pos = {}
    # `records/ui/skills/classNN/skill*.dbr`, asked of the archive index rather
    # than of a directory listing -- fnmatch on the path is the same filter the
    # glob was, and it does not need the records to exist as files anywhere.
    for path in RECORDS.paths('records/ui/skills/'):
        base = path.rsplit('/', 1)[-1]
        if not fnmatch.fnmatch(path, 'records/ui/skills/class*/skill*.dbr'):
            continue
        d = rec(path)
        if not d:
            continue
        name = (d.get('skillName') or [None])[0]
        if not name:
            continue
        try:
            pos[name] = (float((d.get('bitmapPositionY') or [0])[0]),
                         float((d.get('bitmapPositionX') or [0])[0]))
        except ValueError:
            continue
    return pos


BUTTON_POS = button_positions()


def build_tree(entries):
    """Attach each class skill to its parent, then order the panel.

    `entries` is the list of invested class skills, each a dict with 'path'.
    Sets 'parent' (index into `entries`, or None) on every one.
    """
    by_path = {e['path']: i for i, e in enumerate(entries)}
    heads = {}
    for i, e in enumerate(entries):
        t = display_tag(e['path'])
        e['_tag'] = t
        m = TAG_FAMILY.match(t or '')
        e['_fam'] = (m.group(1), m.group(2)) if m else None
        if m and m.group(3) == 'A':
            heads[e['_fam']] = i

    dropped = []
    for i, e in enumerate(entries):
        parent = None
        deps = dependencies(rec(e['path']) or {})
        for dep in deps:
            if dep in by_path:
                parent = by_path[dep]
                break
        else:
            if deps:
                # Declared an edge this character cannot show -- the dependency
                # is real but not invested. Recorded rather than silently lost,
                # because a vanishing edge is exactly the semicolon bug's shape.
                dropped.append((e['path'], deps))
        if parent is None and e['_fam'] and heads.get(e['_fam']) not in (None, i):
            parent = heads[e['_fam']]
        e['parent'] = parent
        e['pos'] = BUTTON_POS.get(e['path'], (9e9, 9e9))
    return dropped


def mastery_of(path):
    """The `_classtraining_classNN.dbr` a playerclass skill belongs to.

    Derived from the path rather than looked up: `+1 Oathkeeper` has to raise
    every Oathkeeper skill, and the mastery record is the only thing that says
    which those are.
    """
    parts = path.split('/')
    if len(parts) < 3 or not parts[2].startswith('playerclass'):
        return None
    cls = parts[2]
    return f"records/skills/{cls}/_classtraining_{cls.replace('playerclass', 'class')}.dbr"


def gather(pr, ca, dir_name, icons):
    ch = dict(pr.execute('select * from character where dir_name=?', (dir_name,)).fetchone())
    worn = pr.execute('select * from character_worn where dir_name=?', (dir_name,)).fetchall()
    inv = {r['skill_path']: r['level'] for r in pr.execute(
        'select skill_path, level, devotion_group from character_skill '
        'where dir_name=? and level>0', (dir_name,))}
    devotion = {r['skill_path']: (r['devotion_group'], r['devotion_experience'])
                for r in pr.execute(
        'select skill_path, devotion_group, devotion_experience from character_skill '
        'where dir_name=?', (dir_name,))}

    C = Contrib()
    # The SECOND bucket. Same shape, same toggle ids, deliberately not the same
    # dict -- see pet_stats_at() for why these must never reach `C`.
    P = Contrib()
    plus_skill, plus_mastery = {}, {}
    equipment, refused = [], []

    for r in worn:
        base = rec(r['base_path'])
        if base is None:
            refused.append({'slot': r['slot'],
                            'why': 'base record is in no game archive'})
            continue
        pfx = rec(r['prefix_path']) if r['prefix_path'] else None
        sfx = rec(r['suffix_path']) if r['suffix_path'] else None
        roll = seedroll.compute(base, r['seed'], pfx, sfx)
        pfx_a = affix_of(ca, r['prefix_path'], 'prefix')
        sfx_a = affix_of(ca, r['suffix_path'], 'suffix')
        pfx_name, sfx_name = pfx_a[0], sfx_a[0]
        slot_label = SLOT_LABEL[r['slot']]
        affixes = {k: v for k, v in (('prefix', pfx_name), ('suffix', sfx_name)) if v}
        aff_src = {k: f'{v} ({slot_label})' for k, v in affixes.items()}
        name, rarity, style, base_name, badge = item_display(
            base, r['base_path'], pfx_a, sfx_a)

        if roll.unmodeled:
            # A desynced stream is worse than no numbers, so the item shows but
            # contributes nothing and says why.
            refused.append({'slot': r['slot'], 'name': name,
                            'why': 'unrolled fields: ' + ', '.join(sorted(roll.unmodeled))})
            rolled = {}
        else:
            rolled = roll.stats
            # Credit each source separately. `roll.parts` splits every field
            # into base/prefix/suffix and sums EXACTLY back to roll.stats, so
            # the sheet's totals do not move -- only the attribution gets
            # finer, from "Redeemer Gauntlets +40" to the affix that rolled it.
            # An affix is labelled by its OWN name plus the slot, e.g.
            # `Impervious (Shoulders)`: the slot keeps two items rolling the
            # same affix apart in one tooltip.
            src = {'base': name, 'prefix': aff_src.get('prefix'),
                   'suffix': aff_src.get('suffix')}
            for f, per in roll.parts.items():
                for where, v in per.items():
                    if v:
                        C.add(f, v, src.get(where) or name, kind=where)

        # Attachments are separate records and are fed in unrolled.
        attached = []
        for col in ATTACH:
            if not r[col]:
                continue
            got = False
            for tbl, idc, vc in (('item', 'item_id', 'num'), ('affix', 'affix_id', 'value'),
                                 ('bonus', 'bonus_id', 'value')):
                row = ca.execute(f'select id from {tbl} where path=?', (r[col],)).fetchone()
                if not row:
                    continue
                got = True
                # A crafting modifier and a relic's completion bonus carry no
                # name tag of any kind -- in game they show as their effect, not
                # as a word. Naming them after their file is worse than saying
                # what they are, so an unnamed record is labelled by its role.
                arow = ca.execute('select name from affix where path=?', (r[col],)).fetchone()
                label = (arow['name'] if arow and arow['name'] else None) \
                    or record_name(rec(r[col]) or {}, r[col]) \
                    or {'relic': 'completion bonus', 'modifier': 'crafting bonus',
                        'augment': 'augment', 'transmute': 'transmuted'}.get(
                            col.split('_')[0], col.split('_')[0])
                attached.append({'kind': col.split('_')[0], 'name': label})
                kind = {'relic': 'completion bonus', 'modifier': 'crafting bonus',
                        'component': 'component', 'augment': 'augment',
                        'transmute': 'transmuted'}[col.split('_')[0]]
                # A component or augment is named on its own; the unnamed
                # kinds (crafting/completion bonus, transmuted) keep the item.
                att_src = label if kind in ('component', 'augment') else f'{name} · {label}'
                for s in ca.execute(f'select field, {vc} v from {tbl}_stat where {idc}=?', (row['id'],)):
                    C.add(s['field'], s['v'], att_src, kind=kind)
                break
            # Channel 1, the attachment half: a component, augment or relic
            # bonus carrying petBonusName. Scalar, so index 0.
            tgt = pet_target(r[col])
            if tgt:
                pet_stats_at(P, tgt, 0, att_src, kind=kind)
            if not got:
                refused.append({'slot': r['slot'], 'name': name,
                                'why': f'attachment not in catalogue: {r[col]}'})
            d = rec(r[col]) or {}
            for i in range(1, 9):
                n, l = d.get(f'augmentSkillName{i}'), d.get(f'augmentSkillLevel{i}')
                if n and l:
                    plus_skill[n[0]] = plus_skill.get(n[0], 0) + int(float(l[0]))
                n, l = d.get(f'augmentMasteryName{i}'), d.get(f'augmentMasteryLevel{i}')
                if n and l:
                    plus_mastery[n[0]] = plus_mastery.get(n[0], 0) + int(float(l[0]))

        for i in range(1, 9):
            n, l = base.get(f'augmentSkillName{i}'), base.get(f'augmentSkillLevel{i}')
            if n and l:
                plus_skill[n[0]] = plus_skill.get(n[0], 0) + int(float(l[0]))
            n, l = base.get(f'augmentMasteryName{i}'), base.get(f'augmentMasteryLevel{i}')
            if n and l:
                plus_mastery[n[0]] = plus_mastery.get(n[0], 0) + int(float(l[0]))

        # Channel 1, the item half.
        tgt = pet_target(r['base_path'])
        if tgt:
            pet_stats_at(P, tgt, 0, name, kind='base')
        for col, ckind in (('prefix_path', 'prefix'), ('suffix_path', 'suffix')):
            tgt = pet_target(r[col])
            if tgt:
                pet_stats_at(P, tgt, 0, aff_src.get(ckind) or name, kind=ckind)

        icon = item_icon(base)
        equipment.append({
            'slot': r['slot'], 'n': name, 'rarity': rarity, 'style': style,
            'affixes': affixes, 'slotLabel': slot_label,
            'icon': icons.want(icon), 'lv': int(float((base.get('levelRequirement') or [0])[0])),
            'lines': stat_lines(rolled, {}), 'attached': attached,
            'set': None, 'path': r['base_path'], 'badge': badge,
            'granted': (base.get('itemSkillName') or [None])[0],
            'grantLv': (base.get('itemSkillLevel')
                        or base.get('itemSkillLevelEq') or [None])[0],
            # The granted skill by NAME. It follows the same buffSkillName hop
            # the toggles do -- an aura's name is on its buff record, not on
            # the skill the item names -- so reuse skill_name rather than
            # reading skillDisplayName here and rendering a filename.
            'grantName': (skill_name(ca, (base.get('itemSkillName') or [None])[0],
                                     rec((base.get('itemSkillName') or [None])[0]) or {})
                          if base.get('itemSkillName') else None),
            'mods': skill_mods(ca, base),
            'bonus': bonus_lines(ca, rec(r['relic_bonus_path'])) if r['relic_bonus_path'] else [],
            'setPath': (base.get('itemSetName') or [None])[0],
        })

    # ---- set bonuses -------------------------------------------------------
    # A SECOND PASS, because a set's bonus depends on how many of its pieces
    # are worn and that is not known until every piece has been seen. Nothing
    # was feeding these at all: Nurgle wears three of three and was missing
    # +100% Acid, +100% Acid Decay and +100% Total Retaliation Damage.
    by_set = {}
    for e in equipment:
        if e['setPath']:
            by_set.setdefault(e['setPath'], []).append(e)
    for path, pieces in by_set.items():
        srec = rec(path)
        if srec is None:
            refused.append({'slot': pieces[0]['slot'], 'name': pieces[0]['n'],
                            'why': f'set record missing: {path}'})
            continue
        stats, skills, members = set_bonus(srec, len(pieces))
        sname = tag((srec.get('setName') or [None])[0]) or 'Set'
        label = f'set · {sname}'
        for f, v in stats.items():
            C.add(f, v, label, kind='set')
        for sp, lv in skills:
            plus_skill[sp] = plus_skill.get(sp, 0) + lv
        info = {'n': sname, 'worn': len(pieces), 'total': len(members),
                'lines': stat_lines(stats, {})
                         + [f'+{lv} {skill_name(ca, sp, rec(sp) or {})}' for sp, lv in skills],
                'members': [{'n': item_display(rec(m) or {}, m)[0],
                             'worn': any(p['path'] == m for p in pieces)}
                            for m in members]}
        for e in pieces:
            e['set'] = info
    for e in equipment:
        del e['setPath']

    return ch, inv, devotion, C, P, equipment, refused, plus_skill, plus_mastery, worn


def devotion_level(path, carrier, xp, stated):
    """A celestial power's LEVEL -- which is not the `level` beside it in the save.

    ⚠️ A BOUND DEVOTION SKILL IS NOT LEVEL 1. Every constellation node the
    character has ever bound stores `level=1`, and reading that fed Dryad's
    Blessing's FIRST row into the sheet -- +20% Physical Resist and +100 health,
    where the same skill at the level a level-100 character has earned gives
    +70% and +848.

    A celestial power banks experience of its own instead, and the ladder it
    climbs is `skillExperienceLevels` on the record -- or on the record its
    `buffSkillName` points at, which is where both the ladder and the stats live
    for the ones that hop (Eldritch Fire has neither on the skill itself). So
    the level is DERIVED from that ladder here.

    The save's fourth int per skill is then the INDEPENDENT CONFIRMATION rather
    than the source, and it is worth having precisely because it was decoded
    under a different layout in a different block: it agrees with the derived
    level on every devotion entry of every save this was built against, in both
    directions. The two readings disagreeing means one of them is wrong and
    neither may be guessed past, so it raises rather than picking a winner.
    """
    ladder = None
    for q in (carrier, path):
        got = (rec(q) or {}).get('skillExperienceLevels')
        if got:
            ladder = [float(v) for v in got]
            break
    if ladder is None:
        # A node with no ladder has nothing to earn: it is one of the four
        # plain stars of a constellation, permanently at 1.
        if xp or stated != 1:
            raise SystemExit(f'{path}: no skillExperienceLevels, but the save '
                             f'states level {stated} on {xp} experience')
        return 1
    level = 1 + sum(1 for t in ladder if xp >= t)
    if level != stated:
        raise SystemExit(f'{path}: {xp} experience is level {level} on its own '
                         f'ladder, but the save states {stated}')
    return level


def granted_level(base):
    """The level an ITEM grants its skill at: `itemSkillLevelEq` on the granting
    record, 1 on a base item and 2 on its mythical upgrade.

    That is the same rule gd-lib's `apply_skill_level` encodes, confirmed there
    against a real tooltip, and the same number this page already prints in the
    Equipment panel's "Grants" line -- the buff pane was the one place still
    folding every granted aura in at level 1, so Mythical Runic Bracers'
    Prismatic Shield read one row short of what the tooltip beside it claimed.

    ⚠️ THE FIELD IS SOMETIMES AN EQUATION (`itemLevel/4+1`). Every one of those
    in this dataset grants an ATTACK skill, which never reaches the buff pane;
    an equation on a skill that does get here would need the item's own level
    and is not guessed at.
    """
    raw = (base.get('itemSkillLevel') or base.get('itemSkillLevelEq') or ['1'])[0]
    if not re.fullmatch(r'\d+', raw.strip()):
        raise SystemExit(f'itemSkillLevelEq={raw!r} is an equation, not a level')
    return max(1, int(raw))


def skills_and_toggles(ca, inv, devotion, plus_skill, plus_mastery, C, P, equipment, icons):
    """Invested skills, and which of them the player can switch.

    Three outcomes per skill and the difference is the whole correctness story:
      permanent  a mastery bar or a bound constellation -- folded in, no switch
      toggle     a self or radius buff -- folded in only when its switch is on
      excluded   everything else, listed with the reason rather than dropped
    """
    skills, toggles, excluded = [], [], []

    def stats_at(path, eff, source, toggle):
        """Add a record's stats at its EFFECTIVE level.

        ⚠️ The stat is an array indexed by level and GEAR MOVES THE INDEX.
        Reading index `invested-1` is wrong by whatever `+N to the mastery`
        the character is wearing.
        """
        # ⚠️ READ THE RECORD, NOT THE CATALOGUE. `skill_stat` is scoped to the
        # player tree plus what items reference, and it does NOT follow
        # buffSkillName -- so `eldritchmeditationaura_buff.dbr`, where a relic's
        # aura keeps its +155% Acid and Vitality, is absent from it entirely.
        # Reading the catalogue here returned "no stats" and the aura silently
        # became a buff with no switch. The .dbr is always there and is the
        # thing the catalogue is derived from; the catalogue stays the source
        # for names, where its scope is not in the way.
        d = rec(path)
        if not d:
            return False
        idx = max(0, eff - 1)
        added = False
        for f, vals in d.items():
            if not wanted(f):
                continue
            try:
                arr = [float(v) for v in vals]
            except ValueError:
                continue                      # a path or a tag, never a stat
            v = arr[idx] if idx < len(arr) else arr[-1]
            if v:
                C.add(f, v, source, toggle, kind='skill')
                added = True
        return added

    for path, lvl in sorted(inv.items()):
        s = ca.execute('select id, name, class, max_level from skill where path=?', (path,)).fetchone()
        d = rec(path) or {}
        cls = s['class'] if s else (d.get('Class') or ['?'])[0]
        name = skill_name(ca, path, d, s)
        # ⚠️ A MASTERY BAR IS NOT RAISED BY `+N to the mastery`. The bar level is
        # what the player invested; `+4 Oathkeeper` raises Oathkeeper's SKILLS.
        # Augmenting the bar reads four more rows down its attribute array and
        # was worth +22 Physique here -- which surfaced only because the OA/DA
        # gate has a known-good total to miss.
        # The stats may be on this record, or one hop away through buffSkillName.
        buff_path = (d.get('buffSkillName') or [None])[0]
        buff = rec(buff_path) if buff_path else None
        holder_cls = (buff.get('Class', ['?'])[0] if buff else cls)
        carrier = buff_path if buff else path

        # ⚠️ STILL THE SAME DISCRIMINATOR, read one field further in. The save's
        # fourth int per skill is ZERO on every non-devotion record and the
        # devotion skill's LEVEL on the rest, so "> 0" partitions exactly as
        # the old "is it non-zero" did -- and now carries the level with it.
        dev, dev_xp = devotion.get(path, (0, 0))
        dev = dev > 0
        # ⚠️ AND `+N to all skills` DOES NOT RAISE A DEVOTION SKILL EITHER. Gear
        # moves mastery skills; a celestial power's level is earned, so it comes
        # off the save's devotion entry and nothing else is added to it.
        eff = (devotion_level(path, carrier, dev_xp, devotion[path][0]) if dev
               else lvl if cls == 'Skill_Mastery'
               else lvl + plus_skill.get(path, 0)
                    + plus_mastery.get(mastery_of(path) or '', 0))

        entry = {'n': name, 'cls': cls, 'lv': lvl, 'eff': eff, 'path': path,
                 'max': (s['max_level'] if s else None),
                 'icon': icons.want(skill_icon(d, cls) or (DEVOTION_ICON if dev else None)),
                 'dev': dev,
                 'mastery': tag((rec(mastery_of(path) or '') or {}).get(
                     'skillDisplayName', [None])[0]) if mastery_of(path) else None}
        skills.append(entry)

        # ⚠️ CHANNEL 3, AND IT FOLDS AT THE RANK, NOT AT 0. The petbonus record
        # an invested skill points at stores one value PER RANK, so Master of
        # Death 12 reads index 11. Gear bonuses and rank-1 devotion nodes both
        # fold at 0, so a build with only those passes either way -- the
        # difference shows only on a character with an always-on pet skill
        # above rank 1 ([[characterise-dont-sample]]).
        #
        # petBonusName sits on the record the player invested in, not on the
        # buff it points at, so this uses `path` where the stats use `carrier`.
        ptgt = (d.get('petBonusName') or [None])[0]
        plabel = f'{"devotion" if dev else "skill"} · {name}'

        if cls in PERMANENT_CLASSES:
            stats_at(carrier, eff, f'{"devotion" if dev else "mastery"} · {name}', None)
            if ptgt:
                pet_stats_at(P, ptgt, max(0, eff - 1), plabel, None, kind='skill')
            entry['role'] = 'permanent'
        elif cls in TOGGLE_CLASSES or holder_cls in TOGGLE_CLASSES:
            tid = f't{len(toggles)}'
            if ptgt:
                pet_stats_at(P, ptgt, max(0, eff - 1), plabel, tid, kind='skill')
            if stats_at(carrier, eff, f'buff · {name}', tid):
                toggles.append({'id': tid, 'n': name, 'icon': entry['icon'],
                                'cls': cls, 'eff': eff,
                                'kind': 'form' if cls == 'Skill_Shapeshift' else
                                        ('duration' if 'Duration' in cls else 'toggle')})
                entry['role'] = 'toggle'
                entry['toggle'] = tid
            else:
                entry['role'] = 'no stats'
        else:
            entry['role'] = 'excluded'
            excluded.append({'n': name, 'cls': cls,
                             'why': 'lands on the enemy' if 'Debuf' in cls or
                                    name in ('Vulnerability', 'Wasting') else
                                    'needs its parent skill active'})

    # Auras a worn item grants are the same shape, one hop further out:
    # item -> itemSkillName -> aura -> buffSkillName -> stats.
    for e in equipment:
        if not e['granted']:
            continue
        d = rec(e['granted']) or {}
        cls = (d.get('Class') or ['?'])[0]
        buff_path = (d.get('buffSkillName') or [None])[0]
        buff = rec(buff_path) if buff_path else None
        holder_cls = (buff.get('Class', ['?'])[0] if buff else cls)
        if not (cls in TOGGLE_CLASSES or holder_cls in TOGGLE_CLASSES):
            continue
        name = skill_name(ca, e['granted'], d)
        lv = granted_level(rec(e['path']) or {})
        tid = f't{len(toggles)}'
        # ⚠️ CHANNEL 2, AND petBonusName IS ON THE SKILL, NOT ON THE BUFF IT
        # POINTS AT -- so this does not take the buffSkillName hop the stats
        # take. An item-granted skill never appears in the save's skill list,
        # which is why walking gear and walking invested skills both miss it.
        gtgt = (d.get('petBonusName') or [None])[0]
        if gtgt:
            pet_stats_at(P, gtgt, 0, f'{e["n"]} · {name}', tid, kind='item skill')
        if stats_at(buff_path or e['granted'], lv, f'{e["n"]} · {name}', tid):
            toggles.append({'id': tid, 'n': name, 'icon': icons.want(skill_icon(d, cls)),
                            'cls': cls, 'eff': lv, 'kind': 'granted',
                            'from': e['n']})
    # The skill window shows the MASTERY panels only. Devotion still feeds the
    # sheet -- it is permanent and unswitchable -- it simply is not a mastery
    # tree and nesting it under one would be a lie about the game's UI.
    tree = [s for s in skills
            if 'playerclass' in s['path'] and s['cls'] != 'Skill_Mastery']
    dropped = build_tree(tree)
    for s in skills:
        s.pop('_tag', None)
        s.pop('_fam', None)
    return skills, toggles, excluded, tree, dropped


# ----------------------------------------------------------------- icons ----
class Icons:
    """Collects every texture the page will ask for, then packs one sheet.

    `want()` during the walk, `pack()` once at the end: an icon is requested by
    several characters and several slots, and a sheet with a tile per request
    would be mostly duplicates.
    """

    def __init__(self, items, ui):
        self.items, self.ui = items, ui
        self.paths = {}

    def want(self, path):
        if not path:
            return None
        return self.paths.setdefault(path.strip(), len(self.paths))

    def pack(self):
        got = {}
        for path, idx in self.paths.items():
            im = self.items.get(path) or self.ui.get(path)
            if im is not None:
                got[idx] = im
        order = sorted(got, key=lambda i: (-got[i].height, -got[i].width))
        W = 512
        x = y = shelf = 0
        frames = {}
        for i in order:
            im = got[i]
            if x + im.width > W:
                x, y, shelf = 0, y + shelf, 0
            frames[i] = [x, y, im.width, im.height]
            x += im.width
            shelf = max(shelf, im.height)
        sheet = Image.new('RGBA', (W, y + shelf), (0, 0, 0, 0))
        for i, f in frames.items():
            sheet.paste(got[i], (f[0], f[1]))
        return sheet, frames


def options_frame(ui):
    """The options window, split into a sliceable frame plus its two crests."""
    im = ui.get('mainmenu/optionswindow/optionswindow_backgroundimage.tex')
    if im is None:
        raise SystemExit('UI.arc has no optionswindow_backgroundimage')
    im = im.convert('RGBA')
    w, h = im.size
    px = im.load()
    wide = lambda y: sum(1 for x in range(w) if px[x, y][3] > 8) > w * 0.8

    # The frame's own edges are the first and last rows that span it.
    top = next(y for y in range(h) if wide(y))
    bot = next(y for y in range(h - 1, -1, -1) if wide(y))

    def overhang(rows):
        """Columns painted OUTSIDE the frame edge -- the crest, plus at the
        bottom the corner feet, which are separated out by taking the middle
        cluster only. Corner feet belong to the corners and slice fine."""
        xs = sorted({x for y in rows for x in range(w) if px[x, y][3] > 8})
        if not xs:
            raise SystemExit('no ornament found outside a frame edge')
        groups, cur = [], [xs[0]]
        for x in xs[1:]:
            if x - cur[-1] <= 40:
                cur.append(x)
            else:
                groups.append(cur)
                cur = [x]
        groups.append(cur)
        mid = min(groups, key=lambda g: abs((g[0] + g[-1]) / 2 - w / 2))
        return mid[0], mid[-1]

    # ⚠️ THE CUT SPAN MUST BE SYMMETRIC ABOUT THE TEXTURE'S CENTRE. The page
    # pins each crest with left:50%, so a span that is even slightly off-centre
    # lands off-centre on the panel -- and the interpolated heal then shows
    # along one edge as a step in the glow. Widen whichever side is short.
    def centred(x0, x1):
        c = (w - 1) / 2
        r = int(max(c - x0, x1 - c) + 0.5)
        return max(0, int(c - r)), min(w - 1, int(c + r))

    tx0, tx1 = centred(*overhang(range(0, top)))
    bx0, bx1 = centred(*overhang(range(bot + 1, h)))

    # A slice deep enough to hold the corner scrollwork, measured: how far in
    # from each edge before the border stops changing.
    def settles(profile, limit):
        for n in range(20, limit):
            if all(profile(k) < 3000 for k in range(n, n + 15)):
                return n
        raise SystemExit('the frame border never settles; the slice is unknown')
    # Reference against known-clean stretches: a column left of the crest and
    # clear of the corner, and a row halfway down the side. Measuring against
    # the texture's centre instead reads the crest as border and never settles.
    ref_col = tx0 - 60
    if ref_col <= 0:
        raise SystemExit('no clean column left of the crest')
    colprof = lambda x: sum(abs(px[x, y][i] - px[ref_col, y][i])
                            for y in range(0, 120) for i in range(3))
    rowprof = lambda y: sum(abs(px[x, y][i] - px[x, h // 2][i])
                            for x in range(0, 120) for i in range(3))
    N = max(settles(colprof, 200), settles(rowprof, 200))
    if N * 2 >= min(w, h):
        raise SystemExit(f'slice {N} does not fit a {w}x{h} frame')

    # Cut the crests, then heal the edge behind them from a clean column --
    # one that is clear of both the corner and the crest.
    clean = (N + tx0) // 2
    if not (N < clean < tx0):
        raise SystemExit('no clean column between the corner and the crest')

    # ⚠️ THE CREST CANNOT BE MASKED OUT PIXEL BY PIXEL. Its wings carry rule
    # segments that must line up with the frame's own rule, and the frame's
    # rule STRETCHES while a pinned sprite does not -- mask it and a wider
    # panel breaks those wings into floating dashes.
    #
    # So cut the whole span as one sprite, and heal the gap by interpolating
    # across it from the columns either side. The endpoints then match their
    # neighbours exactly, so the seam is invisible at any width: at 1:1 the
    # sprite covers the interpolation entirely, and when the edge stretches
    # what shows either side is a smooth continuation of the rule and its
    # glow rather than a repeat of the ornament.
    lum = lambda c: (c[0] * 299 + c[1] * 587 + c[2] * 114) // 1000
    healed = im.copy()
    hp = healed.load()

    def cut(x0, x1, y0, y1):
        for y in range(y0, y1):
            a, b = px[x0 - 1, y], px[x1 + 1, y]
            span = x1 - x0 + 2
            for x in range(x0, x1 + 1):
                t = (x - x0 + 1) / span
                hp[x, y] = tuple(round(a[i] * (1 - t) + b[i] * t) for i in range(4))
        return im.crop((x0, y0, x1 + 1, y1))

    crest_t = cut(tx0, tx1, 0, N)
    crest_b = cut(bx0, bx1, h - N, h)

    # The brown bands inside the top and bottom borders -- the strips the window
    # puts its title and its footer in. Each is the gap between two gold rules,
    # measured on a column clear of the crest so the ornament cannot be mistaken
    # for a rule.
    # Each rule is a couple of pixels thick, so group the bright rows into rules
    # first -- taking raw rows gives the two halves of ONE rule and a
    # zero-height band.
    def rules_in(ys):
        bright = [y for y in ys if lum(px[clean, y]) > 100]
        out, cur = [], [bright[0]] if bright else []
        for y in bright[1:]:
            if y - cur[-1] <= 2:
                cur.append(y)
            else:
                out.append(cur); cur = [y]
        if cur:
            out.append(cur)
        return out

    top_rules = rules_in(range(N))
    if len(top_rules) < 2:
        raise SystemExit('the top border has no rules to bound a title band')
    band0, band1 = top_rules[-2][-1] + 1, top_rules[-1][0]
    if band1 - band0 < 10:
        raise SystemExit(f'the title band is only {band1 - band0}px; that is not it')

    # ⚠️ THE BOTTOM BAND IS BOUNDED BY THE FIRST TWO RULES, NOT THE LAST TWO.
    # The border is a mirror: reading inwards from the panel, the top strip ends
    # with its rules and the bottom strip begins with them. Taking the last two
    # here lands between two strands of the scrollwork, which is not a band and
    # is not the same height twice.
    bot_rules = rules_in(range(h - N, h))
    if len(bot_rules) < 2:
        raise SystemExit('the bottom border has no rules to bound a footer band')
    foot0, foot1 = bot_rules[0][-1] + 1, bot_rules[1][0]
    if foot1 - foot0 < 10:
        raise SystemExit(f'the footer band is only {foot1 - foot0}px; that is not it')

    return {
        'optFrame': png_b64(healed, quantize=255), 'optSlice': N,
        'titleTop': band0, 'titleHeight': band1 - band0,
        # Measured from the frame's BOTTOM edge, because that is the edge the
        # band keeps station with however tall the panel is stretched.
        'footBottom': h - foot1, 'footHeight': foot1 - foot0,
        'crestTop': png_b64(crest_t), 'crestTopSize': list(crest_t.size),
        'crestBottom': png_b64(crest_b), 'crestBottomSize': list(crest_b.size),
        'crestTopInset': 0,
        'crestBottomInset': 0,
    }


def options_button(ui):
    """The options menu's button, and where its end ornaments stop.

    The cap is MEASURED, like every other boundary in build_chrome: per column,
    the largest channel step to the NEXT column. Scrollwork is hard-edged and
    reads in the hundreds; the fill is a smooth gradient and reads under 30, so
    the ornament ends where that drops off a cliff. Brightness alone does not
    work here -- the `over` state's glow is brightest in the MIDDLE, which is
    exactly the part that has to be declared featureless.

    Each state is measured independently and they must agree, so a state whose
    ornament is a different width fails here instead of being sliced through.

    All four the set ships are bundled, and the KEYS NAME THE TEXTURE, not the
    page's use of it -- which state means "on" is a decision the stylesheet
    makes and states there, so this stays a reading of UI.arc.
    """
    states, caps = {}, {}
    for key, name in (('btnUp', 'up'), ('btnOver', 'over'), ('btnDown', 'down'),
                      ('btnDisabled', 'disabled')):
        im = ui.get(f'optionsmenu/optionsbutton{name}.tex')
        if im is None:
            raise SystemExit(f'UI.arc has no optionsmenu/optionsbutton{name}')
        im = im.convert('RGBA')
        px, (w, h) = im.load(), im.size
        step = [max(max(abs(px[x, y][i] - px[x + 1, y][i]) for i in range(4))
                    for y in range(h)) for x in range(w - 1)]
        # A quarter of the sharpest edge in the whole button: well above the
        # fill's gradient and well below any part of the ornament, which is
        # what the two orders of magnitude between them buys.
        flat = max(step) / 4
        caps[key] = next(x for x in range(w // 3)
                         if max(step[x:w - 1 - x]) < flat)
        states[key] = im

    cap = caps['btnUp']
    if len(set(caps.values())) != 1:
        raise SystemExit(f'the button states cap at different widths: {caps}')
    if not 8 < cap < w // 3:
        raise SystemExit(f'an end cap of {cap}px on a {w}px button is not an ornament')
    if len({im.size for im in states.values()}) != 1:
        raise SystemExit('the button states are not all the same size')

    out = {k: png_b64(v) for k, v in states.items()}
    out['btnCap'] = cap
    out['btnHeight'] = h
    return out


def build_chrome(ui):
    """The page's frame and grounds, cut from UI.arc.

    Built here rather than read from the item-browser prototype's bundle: two
    pages sharing a skin should share the extractor, not one page's output file.
    """
    out = {}

    # `mainmenu/borderthin` -- a single gold hairline on 8px corners. The
    # heavier `mainmenu/border` double rule costs 25px of padding on every
    # panel edge, which on a three-column sheet is most of a column.
    p = {k: ui.get(f'mainmenu/borderthin_{k}.tex')
         for k in ('lt', 'ct', 'rt', 'lm', 'rm', 'lb', 'cb', 'rb')}
    C, R = p['lt'].width, 8
    sh = Image.new('RGBA', (C * 2 + R, C * 2 + R), (0, 0, 0, 0))
    sh.paste(p['lt'], (0, 0)); sh.paste(p['rt'], (C + R, 0))
    sh.paste(p['lb'], (0, C + R)); sh.paste(p['rb'], (C + R, C + R))
    # Sample the rails away from either end: the 1024-long edges are flat here,
    # but the first and last pixels carry the corner join.
    sh.paste(p['ct'].crop((400, 0, 400 + R, C)), (C, 0))
    sh.paste(p['cb'].crop((400, 0, 400 + R, C)), (C, C + R))
    sh.paste(p['lm'].crop((0, 400, C, 400 + R)), (0, C))
    sh.paste(p['rm'].crop((0, 400, C, 400 + R)), (C + R, C))
    out['border'] = png_b64(sh)
    out['borderSlice'] = C

    # The inventory tile ships near-white because the game multiplies it by the
    # slot's tint at draw time; baking that keeps the CSS to one background.
    slot = ui.get('character/itembackground.tex')
    tint = Image.new('RGB', slot.size, (58, 50, 39))
    out['slot'] = png_b64(Image.merge('RGBA', (
        *ImageChops.multiply(slot.convert('RGB'), tint).split(), slot.split()[3])))

    out['divider'] = png_b64(ui.get('generic/listboxdivider.tex'))

    # The panel-internal rule, for the one seam inside the character sheet:
    # `mainmenu/borderthindivider_ct`, the same hairline family as the frame
    # the panel already wears rather than a second rule invented for it.
    #
    # ⚠️ CROPPED TO ITS OWN INK. The texture is 400x12 and only the top rows
    # carry the rule -- the rest is the gap the game leaves between the rail
    # and what it separates. Shipping the padding would give the divider a
    # 12px box with its line at the very top, so the space either side of it
    # would be uneven by 10px for no reason anyone could see.
    #
    # ⚠️ AND MIRRORED, because the rail is NOT symmetric: it fades in over 70px
    # and out over 160. It is a left-to-right border piece, and stretched
    # across a panel on its own it reads as a rule that dies away towards the
    # right rather than as a divider. So take it up to the end of its own flat
    # run and mirror that -- both ends then carry the game's own fade, the flat
    # middle is what stretches, and every boundary is measured off the alpha
    # rather than typed.
    rail = ui.get('mainmenu/borderthindivider_ct.tex')
    if rail is None:
        raise SystemExit('UI.arc has no mainmenu/borderthindivider_ct')
    rail = rail.convert('RGBA')
    bb = rail.getbbox()
    if bb is None:
        raise SystemExit('the thin divider rail is fully transparent')
    rail = rail.crop((0, bb[1], rail.width, bb[3]))
    px = rail.load()
    alpha = [max(px[x, y][3] for y in range(rail.height)) for x in range(rail.width)]
    flat = max(alpha) * 0.9
    half = max(x for x, a in enumerate(alpha) if a >= flat) + 1
    if not rail.width // 4 < half < rail.width:
        raise SystemExit(f'the rail plateau ends at {half} of {rail.width}; that is not a fade')
    left = rail.crop((0, 0, half, rail.height))
    sym = Image.new('RGBA', (half * 2, rail.height), (0, 0, 0, 0))
    sym.paste(left, (0, 0))
    sym.paste(left.transpose(Image.FLIP_LEFT_RIGHT), (half, 0))
    out['dividerRule'] = png_b64(sym)
    out['dividerRuleH'] = sym.height

    # The mastery-selection slate: a chalk sigil, already vignetted at its own
    # edges, which is why it can sit under a panel without a mask.
    out['sheetBg'] = png_b64(
        ui.get('skills/classselection/skills_currentclassselectionimage01.tex'), quantize=255)

    # The mastery bars, keyed by the class number the record's own
    # MasteryEnumeration carries (SkillClass01 = Soldier) and the one the
    # record's folder is named for -- so the page picks a bar off the mastery's
    # path rather than off a name-to-colour table typed somewhere.
    #
    # All ten ship whether or not a character here has the mastery: it is a
    # closed set the game defines, and emitting only the ones in use would
    # leave a bar silently unpainted the first time someone rolls an Arcanist.
    # Quantized like the atlas -- at the size a panel header paints one, the
    # worst channel error measured is 14/255 and the mean 1.8, against 5x the
    # bytes for the exact image.
    # The skill and equipment panels' frame: the HUD's menu-folder background.
    # ⚠️ CROPPED, and the crop is the whole trick. The texture is 174x100 but
    # only x=21..165 is a frame -- columns 0..20 are a clasp ornament and
    # 165..173 a notch, BOTH sitting at mid-height where a 9-slice cannot put
    # them. Slicing the raw texture repeats an ornament down every edge.
    # What is left is a clean 2px gold rule around a dark textured ground.
    folder = ui.get('hud/orbhud/hud_menufolderbackground.tex')
    if folder is None:
        raise SystemExit('UI.arc has no hud/orbhud/hud_menufolderbackground')
    folder = folder.convert('RGBA')
    out['folder'] = png_b64(folder.crop((21, 0, 165, 100)))
    out['folderSlice'] = 2

    # The two ornaments, cut out and shipped SEPARATELY. They are why the
    # frame had to be cropped, and they are not lost by it: the game pins each
    # to the middle of its edge once, so the page does the same with an
    # absolutely-positioned sprite rather than asking a 9-slice to repeat it.
    # Both centre on y=50/100, i.e. the panel's vertical middle.
    for key, box in (('clasp', (0, 0, 21, 100)), ('notch', (165, 0, 174, 100))):
        part = folder.crop(box)
        bb = part.getbbox()
        if bb is None:
            raise SystemExit(f'the {key} region of the menu folder is empty')
        out[key] = png_b64(part.crop(bb))
        out[key + 'Size'] = [bb[2] - bb[0], bb[3] - bb[1]]

    # The character sheet's frame: the main menu's options window.
    #
    # ⚠️ ITS FOUR CORNERS 9-SLICE FINE -- THE TWO CRESTS DO NOT. The corner
    # scrollwork is in the corners, so a slice keeps it; the crests sit at the
    # MIDDLE of the top and bottom edges, which is the one place a 9-slice has
    # to stretch. So each crest is cut out, the edge behind it healed with a
    # clean column, and the crest re-pinned over the middle as a sprite. Every
    # boundary below is measured off the texture, not typed.
    out.update(options_frame(ui))

    # The buff pane's tiles are the OPTIONS MENU'S OWN BUTTON, all four states.
    # Which state means what is the stylesheet's call, not this function's.
    #
    # ⚠️ IT IS A HORIZONTAL 3-SLICE, NOT A 9-SLICE. The art is 208x44 with
    # scrollwork at each END and a flat rule along the top and bottom, so the
    # middle stretches sideways and the button keeps the texture's own height.
    # Stretching it vertically as well would thin that rule on one tile and
    # thicken it on the next.
    out.update(options_button(ui))

    # The character drawer's handle, which is the devotion panel's own tab:
    # a tall rail with a '>' when shut and the small '<' button when open.
    # `up`/`over` are the mouse states, as on every other button in UI.arc.
    #
    # ⚠️ THE TWO ARE NOT THE SAME SIZE AND MUST NOT BE MADE SO BY SCALING. The
    # open tab is 60x244 and the close one 20x40, but the 60x244 is mostly
    # filigree: the rune PLATE inside it is 28x39, within a pixel of the close
    # tab's whole 20x38. So each is drawn at its own native size and the two
    # arrows come out the same on screen, which is the parity that reads. The
    # game ships no tall close art, and stretching the small one to the big
    # one's box is a 3x/6.1x upscale of a 20x40 texture.
    #
    # Both sizes go out with the art so the stylesheet states neither.
    for key, name in (('tabOpen', 'tabopenup'), ('tabOpenOver', 'tabopenover'),
                      ('tabClose', 'tabcloseup'), ('tabCloseOver', 'tabcloseover')):
        im = ui.get(f'skills/devotion/devotionbuttons_{name}.tex')
        if im is None:
            raise SystemExit(f'UI.arc has no devotionbuttons_{name}')
        im = im.convert('RGBA')
        out[key] = png_b64(im)
        out[key + 'Size'] = list(im.size)
    for a, b in (('tabOpen', 'tabOpenOver'), ('tabClose', 'tabCloseOver')):
        if out[a + 'Size'] != out[b + 'Size']:
            raise SystemExit(f'{a} and {b} are different sizes; one would jump on hover')

    # The four verdict marks, by the paths the request named. All four are the
    # game's own: a quest's main-objective star for a priority, the tracked and
    # untracked quest gems for nice-to-have and neutral, and the item's
    # can't-use cross for avoid. Cropped to their ink -- they ship at 12-18px
    # and two of the four carry transparent margin, which would make the same
    # nominal size read at three different weights beside a stat label.
    for key, path in (('vdPriority', 'quest/questwidget_mainquest.tex'),
                      ('vdNice', 'quest/questlogtracked.tex'),
                      ('vdIgnore', 'quest/questlognottracked.tex'),
                      ('vdAvoid', 'character/itemunusablemark.tex')):
        im = ui.get(path)
        if im is None:
            raise SystemExit(f'UI.arc has no {path}')
        im = im.convert('RGBA')
        bb = im.getbbox()
        if bb is None:
            raise SystemExit(f'{path} is fully transparent')
        out[key] = png_b64(im.crop(bb))

    # The collapse arrow. `up`/`over`/`down` on these are BUTTON STATES, not
    # directions -- the 01..04 suffix is how many chevrons the faction button
    # draws. 01 is the single one, it points up, and the collapsed state is
    # that same art flipped rather than a second texture.
    for key, name in (('panelArrow', 'up01'), ('panelArrowOver', 'over01')):
        im = ui.get(f'vendors/faction_vendor_buttonitempanel{name}.tex')
        if im is None:
            raise SystemExit(f'UI.arc has no faction_vendor_buttonitempanel{name}')
        out[key] = png_b64(im.convert('RGBA'))

    # The nameplate badges, by the paths gameiteminfo.dbr itself names -- the
    # same record the tier colours come from. Reading the field rather than
    # typing the texture path keeps the two in step.
    gii = rec('records/game/gameiteminfo.dbr') or {}
    for key, field in (('mi', 'monsterInfrequentSymbol'),
                       ('dr', 'doubleRareSymbol'),
                       ('drmi', 'doubleRareMonsterInfrequentSymbol')):
        path = (gii.get(field) or [None])[0]
        if not path:
            raise SystemExit(f'gameiteminfo.dbr declares no {field}')
        im = ui.get(path)
        if im is None:
            raise SystemExit(f'UI.arc has no {path}')
        out.setdefault('badges', {})[key] = png_b64(im.convert('RGBA'))

    # The mastery portraits, behind the page. Same class numbering as the bars
    # and the same closed set of ten, so the page picks one off a mastery's
    # record path. Quantized like the atlas: these are 640x605 apiece and the
    # exact images would be 8 MB of data URI for art that sits behind a scrim.
    out['classImages'] = {}
    for n in range(1, 11):
        im = ui.get(f'skills/skillallocation/skills_classimage{n:02d}.tex')
        if im is None:
            raise SystemExit(f'UI.arc has no class image for class {n:02d}')
        out['classImages'][f'{n:02d}'] = png_b64(im.convert('RGBA'), quantize=255)

    out['masteryBars'] = {}
    for n in range(1, 11):
        bar = ui.get(f'skills/skillallocation/skills_class{n:02d}trainingbar.tex')
        if bar is None:
            raise SystemExit(f'UI.arc has no training bar for class {n:02d}')
        out['masteryBars'][f'{n:02d}'] = png_b64(bar.convert('RGBA'), quantize=255)
    return out


def main(profile_db=None, out_dir=None):
    """Build the bundle. Both overrides exist for the frozen-save gate, which
    reads a profile the live saves did not fill and must not write its bundle
    over the one the page is serving."""
    out_dir = out_dir or OUT
    os.makedirs(out_dir, exist_ok=True)
    pr = sqlite3.connect(profile_db or os.path.join(ARCHIVE, 'cache/profile.sqlite'))
    ca = sqlite3.connect(os.path.join(ARCHIVE, 'cache/catalogue.sqlite'))
    pr.row_factory = ca.row_factory = sqlite3.Row

    items_tx, ui_tx = Textures('Items.arc'), Textures('UI.arc')
    icons = Icons(items_tx, ui_tx)

    out = []
    for row in pr.execute('select dir_name from character order by level desc, name'):
        dn = row['dir_name']
        ch, inv, devotion, C, P, equipment, refused, plus_skill, plus_mastery, worn = \
            gather(pr, ca, dn, icons)
        skills, toggles, excluded, tree, dropped = skills_and_toggles(
            ca, inv, devotion, plus_skill, plus_mastery, C, P, equipment, icons)
        # After the skills, because it reads their EFFECTIVE levels -- a
        # conversion on a transmuter is read at the rank gear has lifted it to.
        vctx = damage_context(worn, skills, C)
        # Which summons can use a pet bonus -- a record walk, so it is answered
        # here with everything else the page cannot derive.
        vctx['pets'] = real_pets(skills)
        masteries = [s for s in skills if s['cls'] == 'Skill_Mastery']
        out.append({
            'dir': dn, 'name': ch['name'], 'level': ch['level'],
            'hardcore': bool(ch['hardcore']), 'male': bool(ch['male']),
            'difficulty': ch['difficulty_tier'], 'money': ch['money'],
            'devotion': [ch['devotion_total'] - ch['devotion_points'], ch['devotion_total']],
            'points': {'attribute': ch['attribute_points'], 'skill': ch['skill_points'],
                       'devotion': ch['devotion_points']},
            'base': {'physique': ch['physique'], 'cunning': ch['cunning'],
                     'spirit': ch['spirit'], 'health': ch['health_base'],
                     'energy': ch['energy_base']},
            'masteries': [{'n': m['n'], 'lv': m['lv']} for m in masteries],
            # The combined class title the character-select screen prints:
            # tagSkillClassName<NN><MM>, the two class numbers ASCENDING, which
            # is the same id the mastery record's folder and MasteryEnumeration
            # carry. One mastery is the bare <NN>; none has no tag at all.
            'title': class_title(masteries),
            'equipment': equipment, 'skills': skills, 'tree': tree,
            'treeDropped': dropped, 'toggles': toggles, 'vctx': vctx,
            'excluded': excluded, 'refused': refused, 'contrib': C.rows,
            'petContrib': P.rows,
        })
        roots = sum(1 for s in tree if s['parent'] is None)
        print(f"  {ch['name']:12s} lvl {ch['level']:<4} {len(equipment)} worn  "
              f"{len(tree)} mastery skills ({roots} roots)  {len(toggles)} toggles  "
              f"{len(C.rows)} stat fields  {len(refused)} refused"
              + (f"  ⚠ {len(dropped)} uninvested edge(s)" if dropped else ""))

    sheet, frames = icons.pack()
    print(f'icon sheet {sheet.size}, {len(frames)} icons')

    chrome = build_chrome(ui_tx)
    bundle = {'characters': out, 'sheet': SHEET, 'targets': {**TARGETS, **SHEET_TARGETS}, 'frames': frames,
              'sheetSize': list(sheet.size), 'atlas': png_b64(sheet, quantize=255),
              'chrome': chrome}
    p = os.path.join(out_dir, 'sheet.json')
    json.dump(bundle, open(p, 'w'), separators=(',', ':'))
    print(f'bundle {os.path.getsize(p)/1e6:.2f} MB')


if __name__ == '__main__':
    main()
