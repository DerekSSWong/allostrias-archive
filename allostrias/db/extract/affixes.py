"""records/items/lootaffixes/** -> the `affix` and `affix_stat` tables.

An affix is a LootRandomizer record: a bundle of stat midpoints plus one
`lootRandomizerJitter` that widens all of them into bands. It is not an item
and has no slot of its own -- which slots it can roll onto is decided by the
pool tables that reference it, and is extracted separately.

Two properties of this data that the table shape has to respect:

  * A NAME IS NOT AN IDENTITY. Four different records are called "Impervious"
    on a belt, pairing Pierce Resist with Fire, Cold, Lightning or Poison, and
    each has up to six level tiers. Eighteen records, eighteen distinct stat
    sets, one display name. So `name` is indexed but never unique, and nothing
    keys off it.
  * DUPLICATES ARE KEPT. 738 records are byte-identical to a sibling and share
    the same pool tables. That redundancy may be how the loot system weights
    those affixes, so dropping it would change drop rates in a way nothing
    here could detect. See the schema note.
"""
from ...archive import values as V
from ...archive.rolls import roll_band

AFFIX_PREFIX = 'records/items/lootaffixes/'
AFFIX_CLASS = 'LootRandomizer'

# Bookkeeping rather than rolled stats: these describe the affix itself and
# must not be handed to roll_band, which would invent a band for a price.
BOOKKEEPING = frozenset({
    'Class', 'templateName', 'FileDescription',
    'lootRandomizerName', 'lootRandomizerCost', 'lootRandomizerJitter',
    'itemClassification', 'levelRequirement', 'marketAdjustmentPercent',
})


def kind_of(path: str) -> str | None:
    """Prefix or Suffix, from the folder. The records carry no such field --
    the only statement of which half of the name an affix occupies is where it
    is filed."""
    parts = path.split('/')
    if 'prefix' in parts:
        return 'Prefix'
    if 'suffix' in parts:
        return 'Suffix'
    return None


def extract(conn, db, tags: dict[str, str]) -> dict[str, int]:
    conn.execute('DELETE FROM affix_stat')
    conn.execute('DELETE FROM affix')

    affix_rows, stat_rows = [], []
    next_id = 1
    skipped_class = skipped_kind = 0
    for path, attrs in db.iter_records(AFFIX_PREFIX):
        if V.first_str(attrs, 'Class') != AFFIX_CLASS:
            skipped_class += 1        # pool tables and other machinery
            continue
        kind = kind_of(path)
        if kind is None:
            skipped_kind += 1         # completion bonuses, not name affixes
            continue

        affix_id = next_id
        next_id += 1
        tag = V.first_str(attrs, 'lootRandomizerName')
        jitter = V.first(attrs, 'lootRandomizerJitter', 0.0) or 0.0
        affix_rows.append((
            affix_id, path, kind, tag,
            V.clean_name(tags.get(tag)) if tag else None,
            V.first_str(attrs, 'itemClassification'),
            V.first(attrs, 'levelRequirement'),
            jitter,
            V.first(attrs, 'lootRandomizerCost'),
        ))
        for row in V.stat_rows(attrs):
            if row.field in BOOKKEEPING:
                continue
            if row.txt is not None:
                stat_rows.append((affix_id, row.field, row.idx, None, None,
                                  None, row.txt))
            else:
                lo, hi = roll_band(row.num, jitter)
                stat_rows.append((affix_id, row.field, row.idx, row.num,
                                  lo, hi, None))

    conn.executemany(
        'INSERT INTO affix (id, path, kind, name_tag, name, rarity, '
        'level_req, jitter, cost) VALUES (?,?,?,?,?,?,?,?,?)', affix_rows)
    conn.executemany(
        'INSERT INTO affix_stat (affix_id, field, idx, value, lo, hi, txt) '
        'VALUES (?,?,?,?,?,?,?)', stat_rows)
    conn.commit()
    return {'affixes': len(affix_rows), 'affix stats': len(stat_rows),
            'non-randomizer skipped': skipped_class,
            'unfiled skipped': skipped_kind}
