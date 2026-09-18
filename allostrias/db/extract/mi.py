"""Which items are Monster Infrequents.

NO STRUCTURAL SIGNAL PROVES MI-NESS. The working rule is a record-level
heuristic plus one exclusion:

    itemClassification=Rare, on a piece of equipment, with a resolvable name,
    and no tier of that NAME reachable from a blueprint.

The craftable exclusion is the part that needs the rest of the catalogue: a
blueprint pointing at a record makes it a crafting output rather than a drop.
It is applied BY NAME, not by record -- each MI exists as 1-8 tier records
sharing a name tag, and splitting a name by tier was checked upstream and only
ever separates a duplicate-stats dev leftover from the blueprinted tier it
copies.

THE DEV POOLS ARE A CROSS-CHECK, NOT THE DEFINITION. The five
mt_monsterinfrequents_* master tables are the developers' own MI roster, and
they are a genuinely named authority rather than pool-shape guessing -- but
reachability from them reaches only 410 of the 421 real names upstream, since
seven are not monster drops at all and four the walk cannot see. Using them as
the rule would silently delete real items, so they are measured against
instead.
"""
from ...archive import values as V

DEV_POOL_MARKER = 'mt_monsterinfrequents'
MI_CLASSIFICATION = 'Rare'

# The gear folders an MI can live in. A WHITELIST, not "any equipment": the
# same itemClassification=Rare appears in records/items/faction/** on VENDOR
# gear (209 names) and in records/items/enemygear/ on monster-worn kit (7),
# and neither is a Monster Infrequent. That mislabelling is the known trap in
# this dataset -- green does not mean MI -- and folder is the only thing that
# separates them, since the records are otherwise identical in shape.
GEAR_FOLDERS = frozenset({
    'gearweapons', 'gearaccessories', 'gearhead', 'gearshoulders',
    'geartorso', 'gearhands', 'gearlegs', 'gearfeet', 'gearrelic',
})
FORMULA_CLASS = 'ItemArtifactFormula'
# The fields a blueprint names its output through. `artifactName` is often a
# LOOT TABLE rather than an item, so both need expanding through the graph.
FORMULA_OUTPUT_FIELDS = ('artifactName', 'forcedRandomArtifactName')


def extract(conn, db, _tags) -> dict[str, int]:
    conn.execute('UPDATE item SET is_mi = NULL')

    tables = {row['path'] for row in conn.execute('SELECT path FROM loot_table')}
    item_by_path = {row['path']: (row['id'], row['name'])
                    for row in conn.execute('SELECT id, path, name FROM item')}

    # Blueprint outputs, expanded through the loot-table graph.
    #
    # THE BLUEPRINTS COME FROM THE CATALOGUE, NOT FROM A SWEEP. `items` has
    # already recorded every record's Class, so asking the database which
    # records are blueprints costs a single indexed query -- against sweeping
    # all 26,001 records under records/items/ to find 927 of them, which is
    # 7.2 s to reach 0.03 s of data. Same pattern as extract/skills.py, which
    # opens only the skills something points at.
    #
    # The two are REQUIRED TO AGREE, and test_mi.py is where that is proven:
    # it does the full sweep and asserts the set matches this query exactly.
    # The check belongs in the gate, where being slow costs nothing and where
    # an `items` change that stopped recording a Class would be caught.
    craftable_paths = set()
    roots = set()
    for (path,) in conn.execute(
            'SELECT path FROM item WHERE class = ?', (FORMULA_CLASS,)).fetchall():
        attrs = V.non_default(db.read(path)) if path in db else {}
        for field in FORMULA_OUTPUT_FIELDS:
            target = V.first_str(attrs, field)
            if not target:
                continue
            target = target.lower()
            if target in tables:
                roots.add(target)
            else:
                craftable_paths.add(target)

    seen, stack = set(), list(roots)
    while stack:
        current = stack.pop()
        if current in seen:
            continue
        seen.add(current)
        attrs = V.non_default(db.read(current)) if current in db else {}
        for values in attrs.values():
            for value in values:
                if not isinstance(value, str) or not value.endswith('.dbr'):
                    continue
                ref = value.lower()
                if ref in tables:
                    stack.append(ref)
                else:
                    craftable_paths.add(ref)

    # Applied by NAME: one craftable tier disqualifies the whole name.
    craftable_names = {item_by_path[p][1] for p in craftable_paths
                       if p in item_by_path and item_by_path[p][1]}

    placeholders = ','.join('?' * len(GEAR_FOLDERS))
    candidates = conn.execute(
        "SELECT id, path, name FROM item "
        "WHERE classification=? AND name IS NOT NULL "
        f"AND folder IN ({placeholders})",
        (MI_CLASSIFICATION, *sorted(GEAR_FOLDERS))).fetchall()
    mi_ids = [(row['id'],) for row in candidates
              if row['name'] not in craftable_names]
    conn.executemany('UPDATE item SET is_mi=1 WHERE id=?', mi_ids)
    conn.execute('UPDATE item SET is_mi=0 WHERE is_mi IS NULL')
    conn.commit()

    mi_names = {row['name'] for row in candidates
                if row['name'] not in craftable_names}
    return {'MI records': len(mi_ids),
            'MI names': len(mi_names),
            'excluded as craftable': len(candidates) - len(mi_ids)}


def dev_pool_names(conn, db) -> set[str]:
    """The MI names the five dev pools reach. A cross-check only.

    SCOPED TO MI CANDIDATES. The pools name child tables that also carry
    ordinary bases, so an unscoped walk comes back with "Armor", "Badge" and
    "Basinet" -- generic gear, not a roster. Restricting the reached set to
    records that are themselves Rare-in-a-gear-folder asks the question worth
    asking: of the items this rule calls MIs, how many does the developers'
    own roster agree with?
    """
    tables = {row['path'] for row in conn.execute('SELECT path FROM loot_table')}
    placeholders = ','.join('?' * len(GEAR_FOLDERS))
    item_name = {row['path']: row['name'] for row in conn.execute(
        'SELECT path, name FROM item WHERE classification=? AND name IS NOT NULL '
        f'AND folder IN ({placeholders})',
        (MI_CLASSIFICATION, *sorted(GEAR_FOLDERS)))}
    roots = {p for p in tables if DEV_POOL_MARKER in p}
    seen, stack, names = set(), list(roots), set()
    while stack:
        current = stack.pop()
        if current in seen:
            continue
        seen.add(current)
        attrs = V.non_default(db.read(current)) if current in db else {}
        for values in attrs.values():
            for value in values:
                if not isinstance(value, str) or not value.endswith('.dbr'):
                    continue
                ref = value.lower()
                if ref in tables:
                    stack.append(ref)
                elif item_name.get(ref):
                    names.add(item_name[ref])
    return names
