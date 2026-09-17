"""records/items/** -> the `item` and `item_stat` tables.

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

ITEM_PREFIX = 'records/items/'


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


def extract(conn, db, tags: dict[str, str]) -> dict[str, int]:
    """Fill `item` and `item_stat`. Returns counts for the build report."""
    conn.execute('DELETE FROM item_stat')
    conn.execute('DELETE FROM item')

    item_rows, stat_rows = [], []
    next_id = 1
    skipped = 0
    for path, attrs in db.iter_records(ITEM_PREFIX):
        record_class = V.first_str(attrs, 'Class') or ''
        is_equipment, family, slot = classify(record_class)
        if not (is_equipment or record_class in CARRIED_CLASSES):
            skipped += 1
            continue

        item_id = next_id
        next_id += 1
        tag = name_tag_of(attrs)
        style_tag, style = style_of(attrs, tags)
        item_rows.append((
            item_id,
            path,
            record_class,
            family,
            slot,
            path.split('/')[2],
            1 if is_equipment else 0,
            tag,
            V.clean_name(tags.get(tag)) if tag else None,
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
                stat_rows.append((item_id, row.field, row.idx, None, row.txt,
                                  None, None, None))
                continue
            lo, hi, status = R.band(row.field, row.num, R.BASE_JITTER,
                                    scale_pct, record_class,
                                    rolls=record_rolls)
            stat_rows.append((item_id, row.field, row.idx, row.num, None,
                              lo, hi, status))

    conn.executemany(
        'INSERT INTO item (id, path, class, family, slot, folder, '
        'is_equipment, name_tag, name, style_tag, style, classification, '
        'level_req, set_path) '
        'VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)', item_rows)
    conn.executemany(
        'INSERT INTO item_stat (item_id, field, idx, num, txt, lo, hi, roll) '
        'VALUES (?,?,?,?,?,?,?,?)', stat_rows)
    conn.commit()
    styled = sum(1 for row in item_rows if row[9] is not None)
    unresolved = sum(1 for row in item_rows
                     if row[9] is not None and row[10] is None)
    return {'items': len(item_rows), 'stats': len(stat_rows),
            'machinery skipped': skipped, 'with a style': styled,
            'style tag resolving to nothing': unresolved}
