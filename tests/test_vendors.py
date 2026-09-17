"""Step 9c gate: faction vendors and static stock.

Checked against a real grimdb entry: Coven Bloodied Ash is listed as sold by
Falonestra (Coven's Refuge) and Lunasta (Kurnhold), Coven of Ugdenbog,
Revered. All four facts -- vendor names, faction, standing, and the item
being stocked at all -- have to come out of the chain independently.

The standing check matters most. itemClassification would have called this
item Honored (it is Epic, and Epic is the third of four classifications); the
game sells it at Revered. Reading the tier from the market record's field
name is what makes the two agree.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from allostrias import settings as S               # noqa: E402
from allostrias.db import catalogue                # noqa: E402

cfg = S.load()
conn = catalogue.connect(cfg.catalogue_db, create=False)
one = lambda sql, *a: conn.execute(sql, a).fetchone()[0]

vendors = one('SELECT count(*) FROM vendor')
stock = one('SELECT count(*) FROM vendor_stock')
items = one('SELECT count(DISTINCT item_id) FROM vendor_stock')
print(f'{vendors} faction vendors, {stock} stock rows, {items} distinct items')
assert vendors > 20, vendors

# Every vendor must resolve to a faction: an unfactioned faction-vendor is a
# broken chain, not a general merchant (those have no tier tables at all).
assert one('SELECT count(*) FROM vendor WHERE faction_id IS NULL') == 0
assert one('SELECT count(*) FROM vendor WHERE name IS NULL') == 0, \
    'a vendor has no name'

print('\nstanding tiers:')
for row in conn.execute('SELECT standing, count(*) n FROM vendor_stock '
                        'GROUP BY standing ORDER BY n DESC'):
    print(f"  {row['standing']:12} {row['n']:5}")
assert {r[0] for r in conn.execute('SELECT DISTINCT standing FROM vendor_stock')} \
    == {'Friendly', 'Respected', 'Honored', 'Revered'}

# -- the grimdb case -------------------------------------------------------
rows = conn.execute("""
    SELECT v.name, f.name faction, k.standing
    FROM vendor_stock k
    JOIN item i   ON i.id = k.item_id
    JOIN vendor v ON v.id = k.vendor_id
    LEFT JOIN faction f ON f.id = v.faction_id
    WHERE i.name = 'Coven Bloodied Ash'
    ORDER BY v.name""").fetchall()
print('\nCoven Bloodied Ash is sold by:')
for row in rows:
    print(f"  {row['name']:16} {row['faction']:22} {row['standing']}")
assert {r['name'] for r in rows} == {'Falonestra', 'Lunasta'}, [dict(r) for r in rows]
assert {r['faction'] for r in rows} == {'Coven of Ugdenbog'}, [dict(r) for r in rows]
assert {r['standing'] for r in rows} == {'Revered'}, [dict(r) for r in rows]
print('  matches grimdb: both vendors, Coven of Ugdenbog, Revered')

# itemClassification would have said Honored. Pin the disagreement so nobody
# "simplifies" standing back onto the classification column.
classification = one("SELECT classification FROM item WHERE name='Coven Bloodied Ash'")
assert classification == 'Epic', classification
print(f'  (its itemClassification is {classification!r} -- which is NOT the '
      'standing, and is why the tier is read from the market record)')

# -- vendors per faction ---------------------------------------------------
print('\nvendors per faction:')
for row in conn.execute("""
        SELECT f.name, count(DISTINCT v.id) vendors, count(k.item_id) rows
        FROM vendor v LEFT JOIN faction f ON f.id = v.faction_id
        LEFT JOIN vendor_stock k ON k.vendor_id = v.id
        GROUP BY f.name ORDER BY rows DESC"""):
    print(f"  {str(row['name']):24} {row['vendors']:2} vendors, {row['rows']:5} stock rows")

conn.close()
print('\nSTEP 9c PASS')
