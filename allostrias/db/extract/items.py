"""Every equippable or carried record -> the `item` and `item_stat` tables.

Most of records/items/ is not items. 12,528 of the 26,001 records are loot
machinery -- drop tables, randomizers, chests, level tables -- and lumping
them in would make every count downstream meaningless.

The split is by `Class`, and it is an EXPLICIT enumeration rather than a
pattern. Two reasons:

  * The obvious pattern rules are wrong. 'has a name tag' misses components,
    augments and relics, which name themselves through `description` instead.
    'lives in a gear folder' misses faction gear and crafted items.
  * An unlisted class is a BUILD FAILURE, not a silent drop. If a game update
    adds a class, someone has to decide which side it falls on; the
    alternative is a catalogue quietly missing a category nobody noticed.

Equipment classes are `Family_Slot`, so the 23 of them are also the slot
taxonomy -- no second mapping to keep in sync.
"""
from ...archive import rolls as R
from ...archive import values as V

# Equipment: the Class is 'Family_Slot' and the record occupies a gear slot.
EQUIPMENT_FAMILIES = (
    'ArmorProtective',   # head, shoulders, chest, hands, legs, feet, waist
    'ArmorJewelry',      # amulet, medal, ring
    'WeaponMelee',
    'WeaponHunting',     # ranged
    'WeaponArmor',       # offhand, shield
)

# Obtainable, but not worn in a gear slot.
CARRIED_CLASSES = frozenset({
    'ItemEnchantment',        # augments
    'ItemRelic',              # components
    'ItemArtifact',           # relics
    'ItemArtifactFormula',    # blueprints
    'ItemTransmuter',         # illusions
    'ItemTransmuterSet',
    'ItemAscensionFormula',
    'ItemRandomSetFormula',
    'ItemRerollFormula',
    'ItemSetFormula',
    'ItemFactionBooster',
    'ItemFactionWarrant',
    'ItemUsableSkill',
    'ItemAttributeReset',
    'ItemDevotionReset',
    'ItemDifficultyUnlock',
    'ItemNote',               # lore notes; they occupy inventory
    'QuestItem',
    'OneShot_Food',
    'OneShot_Gold',
    'OneShot_PotionHealth',
    'OneShot_PotionMana',
    'OneShot_Sack',
    'OneShot_Scroll',
    'OneShot_SkillUnlock',
})

# Not items. Listed so that "everything else" is an error rather than a
# default -- see the module docstring.
MACHINERY_CLASSES = frozenset({
    '',                          # untyped records under lootaffixes/
    'AreaOfInterest',
    'Decoration',
    'Destructible',
    'FixedItemBlastContainer',
    'FixedItemContainer',
    'LevelTable',
    'LootItemTable_DynWeight',
    'LootMasterTable',
    'LootRandomizer',            # an affix, handled by extract/affixes.py
    'LootRandomizerTable',
    'Prop',
    'Proxy',
    'ProxyAccessoryPool',
    'SetPiece',
    'SetPiecePart',
    'SetPiecePool',
})

# ⚠️ THE PATH SCOPE USED TO BE `records/items/` AND THAT SILENTLY LOST ITEMS.
# A character wearing `storyelements/rewards/q003c_ring_slithring.dbr` -- a
# quest reward, a real ring on a real finger -- resolved to nothing in the
# catalogue, found 2026-09-23 by the gate that joins worn gear back to it.
#
# So the scope is a BLACKLIST now, not a whitelist, and the direction is the
# whole point: a whitelist of folders means the next patch that puts wearable
# gear somewhere new is missed in silence, which is the bug that was just paid
# for. A blacklist lets new folders in and costs, at worst, a record nobody
# can obtain sitting unreferenced in a table.
#
# What is excluded, and why it is not gear:
#   records/sandbox/   developers' test junk -- folders named after people,
#                      `test_axe.dbr`, `ring_demo.dbr`. 191 equippable records.
#   records/creatures/ what NPCs and the player MODEL wear, not inventory:
#                      `npc_child_boy_clothes01.dbr`. 215 equippable records.
# Everything else equippable is kept: 17 records, 6 of them quest rewards.
ITEM_PREFIX = 'records/items/'
NON_ITEM_PREFIXES = ('records/sandbox/', 'records/creatures/')


class UnknownItemClass(Exception):
    """A Class that is on none of the three lists. Decide which it belongs on."""


def classify(record_class: str) -> tuple[bool, str, str | None]:
    """(is_equipment, family, slot) for a Class, or raise if unrecognised."""
    family, _, slot = record_class.partition('_')
    if family in EQUIPMENT_FAMILIES and slot:
        return True, family, slot
    if record_class in CARRIED_CLASSES:
        return False, record_class, None
    if record_class in MACHINERY_CLASSES:
        return False, record_class, None
    raise UnknownItemClass(
        f'unrecognised item Class {record_class!r}. Add it to '
        'CARRIED_CLASSES or MACHINERY_CLASSES in extract/items.py -- '
        'a game update may have introduced a new item category.')


def is_item(record_class: str) -> bool:
    is_equipment, _family, _slot = classify(record_class)
    return is_equipment or record_class in CARRIED_CLASSES


def name_tag_of(attrs: dict) -> str | None:
    """The tag naming this record.

    Equipment uses `itemNameTag`. Components, augments, relics, blueprints and
    transmuters use `description` instead -- same job, different field -- so
    reading only itemNameTag leaves ~1,600 items nameless.
    """
    return V.first_str(attrs, 'itemNameTag') or V.first_str(attrs, 'description')


def style_of(attrs: dict, tags: dict[str, str]) -> tuple[str | None, str | None]:
    """(style tag, resolved style) -- the tier word rendered before the name.

    Returned as a PAIR on purpose. One tag in the archives resolves to no text,
    and "this record has a style we cannot name" is a different fact from "this
    record has no style". Collapsing them would silently turn the first into
    the second.
    """
    tag = V.first_str(attrs, 'itemStyleTag')
    if not tag:
        return None, None
    return tag, V.clean_name(tags.get(tag)) or None


def quality_of(attrs: dict, tags: dict[str, str]) -> tuple[str | None, str | None]:
    """(quality tag, resolved quality) -- the word rendered before the style,
    kept as a pair for the same reason style_of() is."""
    tag = V.first_str(attrs, 'itemQualityTag')
    if not tag:
        return None, None
    return tag, V.clean_name(tags.get(tag)) or None


class Collector:
    """items' part of the shared tree pass (extract/shared_pass.py).

    It needs 75,720 of the 82,448 records, so a walk of its own read the whole
    tree a second time: 18.6 s of a 72 s build.

    ⚠️ `offer` reads the RAW attributes, not `kept`. `levelRequirement` is the
    one field that tells them apart: 142 items store it as 0, which
    non_default() would drop, turning `level_req` 0 into NULL. Everything else
    read here survives non_default() unchanged -- stat_rows() applies it itself.

    `finish` must run BEFORE any other consumer's: they read `item`.
    """

    def __init__(self, conn, _db, tags: dict[str, str]):
        self.conn, self.tags = conn, tags
        self.item_rows, self.stat_rows = [], []
        self.skipped = 0

    def offer(self, path: str, attrs: dict, _kept: dict):
        if path.startswith(NON_ITEM_PREFIXES):
            return
        record_class = V.first_str(attrs, 'Class') or ''
        try:
            is_equipment, family, slot = classify(record_class)
        except UnknownItemClass:
            # ⚠️ AN UNKNOWN CLASS IS STILL A BUILD FAILURE **INSIDE**
            # records/items/, which is the guarantee this module was built on:
            # a game update that adds an item category must be decided about,
            # not silently dropped. Outside it the walk crosses the whole game
            # -- levels, fx, skills, controllers -- where an unrecognised Class
            # means "not an item" and nothing more.
            if path.startswith(ITEM_PREFIX):
                raise
            self.skipped += 1
            return
        if not (is_equipment or record_class in CARRIED_CLASSES):
            self.skipped += 1
            return

        tags = self.tags
        item_id = len(self.item_rows) + 1
        tag = name_tag_of(attrs)
        style_tag, style = style_of(attrs, tags)
        quality_tag, quality = quality_of(attrs, tags)
        self.item_rows.append((
            item_id,
            path,
            record_class,
            family,
            slot,
            path.split('/')[2],
            1 if is_equipment else 0,
            tag,
            V.clean_name(tags.get(tag)) if tag else None,
            quality_tag,
            quality,
            style_tag,
            style,
            V.first_str(attrs, 'itemClassification'),
            V.first(attrs, 'levelRequirement'),
            V.first_str(attrs, 'itemSetName'),
        ))
        # Equipment bases and relics jitter at a flat 20%; components,
        # augments and blueprints are read at their stored values. See
        # rolls.ROLLING_CLASSES -- both halves are verified against grimdb,
        # and both were wrong at some point in opposite directions.
        scale_pct = V.first(attrs, 'attributeScalePercent', 0.0) or 0.0
        record_rolls = is_equipment or record_class in R.ROLLING_CLASSES
        for row in V.stat_rows(attrs):
            if row.txt is not None:
                self.stat_rows.append((item_id, row.field, row.idx, None, row.txt,
                                       None, None, None))
                continue
            lo, hi, status = R.band(row.field, row.num, R.BASE_JITTER,
                                    scale_pct, record_class,
                                    rolls=record_rolls)
            self.stat_rows.append((item_id, row.field, row.idx, row.num, None,
                                   lo, hi, status))

    def finish(self) -> dict[str, int]:
        """Fill `item` and `item_stat`. Returns counts for the build report."""
        conn, item_rows = self.conn, self.item_rows
        conn.execute('DELETE FROM item_stat')
        conn.execute('DELETE FROM item')
        conn.executemany(
            'INSERT INTO item (id, path, class, family, slot, folder, '
            'is_equipment, name_tag, name, quality_tag, quality, style_tag, style, '
            'classification, level_req, set_path) '
            'VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)', item_rows)
        conn.executemany(
            'INSERT INTO item_stat (item_id, field, idx, num, txt, lo, hi, roll) '
            'VALUES (?,?,?,?,?,?,?,?)', self.stat_rows)
        conn.commit()
        styled = sum(1 for row in item_rows if row[11] is not None)
        unresolved = sum(1 for row in item_rows
                         if row[11] is not None and row[12] is None)
        return {'items': len(item_rows), 'stats': len(self.stat_rows),
                'machinery skipped': self.skipped, 'with a style': styled,
                'style tag resolving to nothing': unresolved}
