"""Step 8a gate: the drop graph.

The central risk is LevelTable. It holds no items, so it reads like machinery;
omitting it raises no error and even INCREASES the distinct-item count, which
is why it has to be measured rather than reasoned about. This gate rebuilds
the graph both ways and compares.

It deliberately does NOT gate on the monster-name count. Upstream reports that
number collapsing without LevelTable; measured here it is identical either
way, because upstream counts names for MI holders while this counts all named
holders. A gate copied from that figure would have passed with the class
missing -- which is the exact failure it was supposed to catch.
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from allostrias import settings as S               # noqa: E402
from allostrias.archive import arz as A            # noqa: E402
from allostrias.archive import values as V         # noqa: E402
from allostrias.db import catalogue                # noqa: E402
from allostrias.db.extract import drops as D       # noqa: E402

GIRDLE = 'records/items/gearaccessories/waist/b201f_waist.dbr'

cfg = S.load()
conn = catalogue.connect(cfg.catalogue_db, create=False)
one = lambda sql, *a: conn.execute(sql, a).fetchone()[0]

# -- 1. all three table classes are present -------------------------------
classes = dict(conn.execute(
    'SELECT class, count(*) FROM loot_table GROUP BY class'))
print(f'loot tables by class: {classes}')
assert set(classes) == D.TABLE_CLASSES, classes
assert classes['LevelTable'] > 1000, classes

# -- 2. holders are not only creatures ------------------------------------
kinds = dict(conn.execute('SELECT kind, count(*) FROM holder GROUP BY kind'))
print(f'\nholders by kind: {kinds}')
assert kinds['creatures'] > 2000, kinds
# Boss chests and Shattered Realm records hold their own tables; filtering to
# creatures loses 53 items upstream.
for kind in ('items', 'endlessdungeon', 'sandbox'):
    assert kinds.get(kind, 0) > 0, f'no {kind} holders -- the walk was scoped too tightly'

# records/sandbox/ is INCLUDED here and EXCLUDED from affix eligibility. Same
# folder, two roles, opposite correct answers. Assert both so neither gets
# "fixed" to match the other.
sandbox_monsters = one(
    "SELECT count(*) FROM holder WHERE kind='sandbox' AND is_monster=1 "
    "AND name IS NOT NULL")
print(f'  sandbox holders that are NAMED monsters: {sandbox_monsters} '
      '(live bosses; eligibility still excludes sandbox tables)')
assert sandbox_monsters > 0, 'sandbox was excluded here, but it ships live bosses'

# -- 3. the worked example -------------------------------------------------
names = [r[0] for r in conn.execute("""
    SELECT DISTINCT h.name FROM item_drop d
    JOIN item i ON i.id=d.item_id JOIN holder h ON h.id=d.holder_id
    WHERE i.path=? AND h.is_monster=1 AND h.name IS NOT NULL
    ORDER BY h.name""", (GIRDLE,))]
total = one('SELECT count(*) FROM item_drop d JOIN item i ON i.id=d.item_id '
            'WHERE i.path=?', GIRDLE)
print(f'\nGargoyle Girdle lvl 94: {total} holders, {len(names)} named monsters')
for name in names:
    print(f'  {name}')
assert len(names) == 12, names
assert all('argoyle' in n or '~' in n for n in names), names

# -- 4. LevelTable, measured both ways ------------------------------------
print('\nrebuilding the graph to measure the LevelTable trap...')
t0 = time.time()
with A.Database(cfg.arz_paths) as db:
    graph = {}
    for path, attrs in db.iter_records():
        kept = V.non_default(attrs)
        graph[path] = (V.first_str(kept, 'Class') or '', D._references(kept))
print(f'  graph {len(graph)} records in {time.time() - t0:.0f}s')


def holders_of(table_classes, target):
    tables = {p for p, (c, _) in graph.items() if c in table_classes}
    memo, found = {}, set()

    def expand(roots):
        seen, stack, out = set(), list(roots), set()
        while stack:
            current = stack.pop()
            if current in seen:
                continue
            seen.add(current)
            for ref in graph.get(current, ('', ()))[1]:
                if ref in tables:
                    stack.append(ref)
                elif ref.startswith('records/items/') and ref in graph:
                    out.add(ref)
        return out

    for path, (_cls, refs) in graph.items():
        if path in tables:
            continue
        roots = frozenset(refs & tables)
        if not roots:
            continue
        if roots not in memo:
            memo[roots] = expand(roots)
        if target in memo[roots]:
            found.add(path)
    return found


with_lt = holders_of(D.TABLE_CLASSES, GIRDLE)
without_lt = holders_of(D.TABLE_CLASSES - {'LevelTable'}, GIRDLE)
print(f'  with LevelTable    {len(with_lt):4} holders')
print(f'  WITHOUT LevelTable {len(without_lt):4} holders  '
      f'({len(with_lt) - len(without_lt)} lost)')
assert len(with_lt) == 148, len(with_lt)
assert len(without_lt) == 14, len(without_lt)
assert len(with_lt) > len(without_lt) * 5, 'LevelTable is not being traversed'
print('  LevelTable is load-bearing, and its absence would not have errored')

# -- the independent walk must agree with WHAT THE BUILD WROTE -------------
# Until the shared pass existed this gate re-derived 148 holders and compared
# them to the literal 148 -- proving its own walk, never the catalogue's. The
# two are only the same thing while the build reads every record, which is now
# a property of extract/shared_pass.py rather than of drops.py.
#
# So the derived set is compared to the stored one. A pass that narrowed its
# prefix, dropped a consumer, or skipped a record shrinks the stored side and
# fails here; the literal above would not have noticed.
stored = {row[0] for row in conn.execute(
    'SELECT h.path FROM item_drop d JOIN holder h ON h.id = d.holder_id '
    'JOIN item i ON i.id = d.item_id WHERE i.path = ?', (GIRDLE,))}
assert stored == with_lt, (
    f'the catalogue stores {len(stored)} holders for this item but an '
    f'independent walk of the archives finds {len(with_lt)}: '
    f'missing {sorted(with_lt - stored)[:3]}, extra {sorted(stored - with_lt)[:3]}')
print(f'  and the catalogue stores exactly those {len(stored)} -- the build '
      f'read every record it should have')


# -- 5. dangling references are not reported as items ---------------------
orphans = one('SELECT count(*) FROM item_drop d '
              'LEFT JOIN item i ON i.id=d.item_id WHERE i.id IS NULL')
assert orphans == 0, f'{orphans} drop rows point at no item'
print(f'\n{one("SELECT count(*) FROM item_drop")} item-drop pairs, no orphans')

conn.close()
print('\nSTEP 8a PASS')
