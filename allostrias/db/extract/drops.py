"""Who drops what: the loot-table graph, walked from each holder to its items.

An item names nobody. A loot table names items and other tables. A creature,
chest or quest step names a table. So the drop relationship is reachability
over three kinds of record, and this module is the one place that walks it.

THREE THINGS HERE ARE EASY TO GET WRONG AND NONE OF THEM FAILS LOUDLY:

  * LevelTable IS a loot table. It holds no items -- it picks a child table by
    character level -- so it reads like machinery. Leaving it out does not
    error and does not even reduce reachability: an unrecognised table becomes
    a holder, so the distinct-item count goes UP by 1,029. What it destroys is
    the connection between an item and the things that drop it: item-drop
    pairs collapse from 5.1M to 323k, and the Gargoyle Girdle goes from 148
    holders to 14.

    MEASURED HERE, not inherited. Upstream reports monster names falling
    348 -> 307 without it; in this walk the named-monster total is 1,832 EITHER
    WAY, because upstream counted names for MI holders specifically while this
    counts every named holder. The name count is therefore NOT the signature
    to gate on, and a gate copied from that number would have passed while the
    table class was missing.
  * A HOLDER IS NOT JUST A CREATURE. Boss chests, Shattered Realm records and
    a handful of live bosses under records/sandbox/ hold their own tables.
    Filtering to /creatures/ loses 53 items, 43 of them named in the community
    MI reference list.
  * records/sandbox/ IS INCLUDED HERE, and is EXCLUDED from affix eligibility
    two modules over. Same folder, two roles, two opposite correct answers:
    the sandbox drop TABLES grant affix eligibility the shipped game never
    gives, while the sandbox CREATURES are real bosses that really drop. Both
    are asserted, so neither can be "fixed" to match the other.

WHAT THIS IS NOT: a definition of what counts as a Monster Infrequent.
Reachability reaches 410 of the 421 real MI names -- 7 are not monster drops
at all and 4 the walk cannot see -- so using it as the membership rule would
silently delete real items. This answers "where does it come from", nothing else.
"""
from ...archive import values as V

# The three classes that are loot tables. LevelTable is the one that looks
# like it is not; see the module docstring.
TABLE_CLASSES = frozenset({
    'LootItemTable_DynWeight', 'LootMasterTable', 'LevelTable'})
ITEM_PREFIX = 'records/items/'
MONSTER_CLASS = 'Monster'


def _references(attrs) -> set[str]:
    """Every record path this record mentions, from any field.

    Deliberately not keyed by field name: a table points at its children
    through a dozen differently-numbered fields and any path it mentions is an
    edge. Reading arrays natively means every entry is seen -- the upstream
    walk needed an unanchored regex because its text dump joined multi-value
    fields and lost all but the first.
    """
    found = set()
    for values in attrs.values():
        for value in values:
            if isinstance(value, str) and value.endswith('.dbr'):
                found.add(value.lower())
    return found


class Collector:
    """drops' half of the shared tree pass.

    THE WALK ITSELF IS NOT HERE. drops and eligibility both need every record
    in the tree, and reading it twice cost 16 s of a 72 s build, so one loop in
    extract/shared_pass.py feeds both. What stays in this module is everything
    that is ABOUT drops -- which classes are tables, what counts as an edge,
    and the expansion that turns a holder's root set into the items it yields.

    `offer` is called once per record with its NON-DEFAULT attributes and keeps
    only the class and the outbound .dbr references. That is not an
    optimisation to taste: holding the full attribute set tree-wide is 5.6 GB,
    measured, and nothing below needs any other field.
    """

    def __init__(self, conn, db, tags: dict[str, str]):
        self.conn, self.tags = conn, tags
        self.graph: dict[str, tuple[str, set[str]]] = {}
        self.monster: dict[str, tuple] = {}

    def offer(self, path: str, kept: dict):
        record_class = V.first_str(kept, 'Class') or ''
        self.graph[path] = (record_class, _references(kept))
        if record_class == MONSTER_CLASS:
            # Collected in the one pass that already holds the record. A
            # holder is named by many items and each of their tiers, so
            # re-opening it per lookup is pure repeat work for no new data.
            self.monster[path] = (
                V.first_str(kept, 'description'),
                V.first_str(kept, 'monsterClassification'),
                V.first(kept, 'minLevel'),
                V.first(kept, 'maxLevel'),
                V.first(kept, 'experiencePoints'),
            )

    def finish(self) -> dict[str, int]:
        conn, tags = self.conn, self.tags
        graph, monster = self.graph, self.monster

        conn.execute('DELETE FROM item_drop')
        conn.execute('DELETE FROM holder')
        conn.execute('DELETE FROM loot_table')

        item_ids = {row['path']: row['id']
                    for row in conn.execute('SELECT id, path FROM item')}

        tables = {p for p, (cls, _) in graph.items() if cls in TABLE_CLASSES}

        def expand(roots: frozenset[str]) -> set[str]:
            """Every item record reachable from these tables, following nesting.

            A reference may DANGLE -- a table names a record that is not in this
            install -- so a target counts only once the graph confirms it exists.
            Without that check a missing table is reported as if it were an item.

            LEVEL BRACKETS ARE NOT APPLIED. A LevelTable's children are all
            followed, so every tier of an item family resolves to the same holder
            set: the lvl 20 and lvl 94 Gargoyle Girdles both come back as the same
            12 gargoyles. That is the right answer to "which monsters drop this",
            and it is NOT an answer to "which tier will this monster give me" --
            that depends on the bracket in the LevelTable's `levels` field, which
            nothing here reads.
            """
            seen, stack, found = set(), list(roots), set()
            while stack:
                current = stack.pop()
                if current in seen:
                    continue
                seen.add(current)
                for ref in graph.get(current, ('', ()))[1]:
                    if ref in tables:
                        stack.append(ref)
                    elif ref.startswith(ITEM_PREFIX) and ref in graph:
                        found.add(ref)
            return found

        # One expansion per distinct ROOT SET, not per holder: thousands of
        # holders share a few hundred sets, and re-walking per holder is the
        # difference between seconds and minutes.
        memo: dict[frozenset[str], set[str]] = {}
        table_rows, holder_rows, drop_rows = [], [], []
        for table_id, path in enumerate(sorted(tables), start=1):
            table_rows.append((table_id, path, graph[path][0]))

        holder_id = 0
        for path in sorted(graph):
            record_class, refs = graph[path]
            if path in tables:
                continue
            roots = frozenset(refs & tables)
            if not roots:
                continue
            holder_id += 1
            tag, classification, min_lvl, max_lvl, xp = monster.get(
                path, (None, None, None, None, None))
            holder_rows.append((
                holder_id, path, record_class, path.split('/')[1],
                1 if record_class == MONSTER_CLASS else 0,
                tag, V.clean_name(tags.get(tag)) if tag else None,
                classification, min_lvl, max_lvl, xp))
            if roots not in memo:
                memo[roots] = expand(roots)
            for item_path in memo[roots]:
                item_id = item_ids.get(item_path)
                if item_id is not None:
                    drop_rows.append((item_id, holder_id))

        conn.executemany(
            'INSERT INTO loot_table (id, path, class) VALUES (?,?,?)', table_rows)
        conn.executemany(
            'INSERT INTO holder (id, path, class, kind, is_monster, name_tag, '
            'name, classification, min_level, max_level, experience) '
            'VALUES (?,?,?,?,?,?,?,?,?,?,?)', holder_rows)
        conn.executemany(
            'INSERT OR IGNORE INTO item_drop (item_id, holder_id) VALUES (?,?)',
            drop_rows)
        conn.commit()
        monsters = sum(1 for r in holder_rows if r[4])
        named = len({r[6] for r in holder_rows if r[4] and r[6]})
        unnamed = sum(1 for r in holder_rows if r[4] and r[5] and not r[6])
        return {'loot tables': len(table_rows),
                'holders': len(holder_rows),
                'holders that are monsters': monsters,
                'distinct monster names': named,
                'root sets expanded': len(memo),
                'monsters with a tag but no name': unnamed,
                'item-drop pairs': len(drop_rows)}
