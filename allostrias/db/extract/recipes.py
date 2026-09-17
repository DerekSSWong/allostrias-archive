"""Blueprints and item sets.

RECIPES. A blueprint states its output twice and its inputs in two shapes:

  * `artifactName` is the output, and it names an ITEM DIRECTLY in 727 of 927
    blueprints. Exactly ONE points at a loot table. The received wisdom that
    it "is often a loot table" is the reverse of what the data says, and
    treating it that way left 727 recipes with no output at all.
  * `forcedRandomArtifactName` is the concrete item for the minority where
    artifactName is a table -- 191 blueprints. Where both exist, the forced
    name is the thing you actually receive.
  * `reagentBaseBaseName` accepts ALTERNATIVES: 115 blueprints list up to
    seven acceptable items for that one slot. The numbered slots never do.
    Flattening them would turn one requirement into seven.

SETS. A set's bonuses are arrays indexed by piece count, and the index is
RIGHT-ALIGNED -- the last entry always applies at the full set:

    pieces(i) = members - (len(array) - 1 - i)

Most arrays are exactly as long as the member list, so the distinction never
shows. Eleven are shorter: [0, 0, 0, 3] on a six-piece set means +3 at SIX
pieces, and reading it from the left would hand a full-set bonus to someone
wearing four. Three arrays are longer than the member list, whose leading
entries are simply unreachable; the same formula covers both.
"""
from ...archive import values as V

CRAFTING_PREFIX = 'records/items/crafting/'
LOOTSET_PREFIX = 'records/items/lootsets/'
FORMULA_CLASS = 'ItemArtifactFormula'

BASE_SLOT = 'base'
BASE_NAME, BASE_QTY = 'reagentBaseBaseName', 'reagentBaseQuantity'
MAX_SLOTS = 8

# Set fields that describe the set rather than being a per-tier bonus.
SET_META = frozenset({
    'setMembers', 'setName', 'setDescription', 'templateName',
    'FileDescription', 'itemLevel', 'Class',
})


def _extract_recipes(conn, db, item_ids) -> dict[str, int]:
    recipe_rows, reagent_rows = [], []
    tables = {row['path'] for row in conn.execute('SELECT path FROM loot_table')}
    alt_slots = 0

    for path, attrs in db.iter_records(CRAFTING_PREFIX):
        if V.first_str(attrs, 'Class') != FORMULA_CLASS:
            continue
        blueprint_id = item_ids.get(path)
        if blueprint_id is None:
            continue
        kept = V.non_default(attrs)

        forced = (V.first_str(kept, 'forcedRandomArtifactName') or '').lower()
        artifact = (V.first_str(kept, 'artifactName') or '').lower()
        # The forced name wins when present; otherwise artifactName is itself
        # the item. Only recorded as a table when it genuinely is one.
        output_item = item_ids.get(forced) or item_ids.get(artifact)
        recipe_id = len(recipe_rows) + 1
        recipe_rows.append((
            recipe_id, blueprint_id,
            output_item,
            artifact if artifact in tables else None,
            V.first(kept, 'artifactCreationCost'),
            V.first(kept, 'artifactCreateQuantity'),
        ))

        slots = [(BASE_SLOT, kept.get(BASE_NAME, []), V.first(kept, BASE_QTY))]
        for n in range(1, MAX_SLOTS + 1):
            names = kept.get(f'reagent{n}BaseName', [])
            if names:
                slots.append((str(n), names, V.first(kept, f'reagent{n}Quantity')))
        for slot, names, quantity in slots:
            if len(names) > 1:
                alt_slots += 1
            for alternative, name in enumerate(names):
                if not isinstance(name, str) or not name:
                    continue
                reagent_rows.append((recipe_id, slot, alternative,
                                     item_ids.get(name.lower()), name.lower(),
                                     quantity))

    conn.executemany(
        'INSERT INTO recipe (id, blueprint_id, output_item_id, output_table, '
        'cost, quantity) VALUES (?,?,?,?,?,?)', recipe_rows)
    conn.executemany(
        'INSERT OR IGNORE INTO recipe_reagent (recipe_id, slot, alternative, '
        'item_id, item_path, quantity) VALUES (?,?,?,?,?,?)', reagent_rows)
    return {'recipes': len(recipe_rows),
            'reagent rows': len(reagent_rows),
            'slots offering alternatives': alt_slots,
            'recipes with a concrete output': sum(1 for r in recipe_rows if r[2]),
            'recipes whose output is a table': sum(1 for r in recipe_rows if r[3]),
            'recipes with NO resolvable output':
                sum(1 for r in recipe_rows if not r[2] and not r[3])}


def _extract_sets(conn, db, item_ids, tags) -> dict[str, int]:
    set_rows, member_rows, bonus_rows = [], [], []
    short = long = 0

    for path, attrs in db.iter_records(LOOTSET_PREFIX):
        kept = V.non_default(attrs)
        members = [m.lower() for m in kept.get('setMembers', [])
                   if isinstance(m, str) and m]
        if not members:
            continue
        set_id = len(set_rows) + 1
        set_rows.append((
            set_id, path,
            V.clean_name(tags.get(V.first_str(kept, 'setName'))),
            tags.get(V.first_str(kept, 'setDescription') or ''),
            len(members)))
        for member in members:
            member_rows.append((set_id, item_ids.get(member), member))

        for field, values in kept.items():
            if field in SET_META or len(values) < 2:
                continue
            if len(values) < len(members):
                short += 1
            elif len(values) > len(members):
                long += 1
            # RIGHT-ALIGNED: the last entry is the full set, always.
            offset = len(members) - len(values)
            for index, value in enumerate(values):
                pieces = index + 1 + offset
                if pieces < 1:
                    continue            # unreachable leading entry
                if isinstance(value, str):
                    bonus_rows.append((set_id, pieces, field, None, value))
                elif value:
                    bonus_rows.append((set_id, pieces, field, float(value), None))

    conn.executemany(
        'INSERT INTO item_set (id, path, name, description, members) '
        'VALUES (?,?,?,?,?)', set_rows)
    conn.executemany(
        'INSERT OR IGNORE INTO set_member (set_id, item_id, item_path) '
        'VALUES (?,?,?)', member_rows)
    conn.executemany(
        'INSERT OR IGNORE INTO set_bonus (set_id, pieces, field, value, txt) '
        'VALUES (?,?,?,?,?)', bonus_rows)
    return {'item sets': len(set_rows),
            'set members': len(member_rows),
            'set bonus rows': len(bonus_rows),
            'arrays shorter than the set': short,
            'arrays longer than the set': long}


def extract(conn, db, tags: dict[str, str]) -> dict[str, int]:
    for table in ('recipe_reagent', 'recipe', 'set_bonus', 'set_member',
                  'item_set'):
        conn.execute(f'DELETE FROM {table}')
    item_ids = {row['path']: row['id']
                for row in conn.execute('SELECT id, path FROM item')}
    counts = _extract_recipes(conn, db, item_ids)
    counts.update(_extract_sets(conn, db, item_ids, tags))
    conn.commit()
    return counts
