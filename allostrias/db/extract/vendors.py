"""Faction vendors, and the stock they reliably carry.

The chain has four links and each one is stated by the game rather than
inferred:

    NPC record
      .factions      -> faction record -> myFaction -> faction.id
      .description   -> the vendor's name
      .marketFileName-> a factionmarket.tpl record
                          .<tier>NormalTable -> a stock table
                                                  .marketStaticItems -> items

STANDING COMES FROM THE FIELD NAME, not the filename. The market record
declares friendlyNormalTable / respectedNormalTable / honoredNormalTable /
reveredNormalTable, so the tier is structural. The stock tables happen to be
named coven_revered_01.dbr as well, but reading the tier out of a filename
would be guessing at something the record already says.

STATIC STOCK ONLY. `marketStaticItems` is the fixed list. The randomised
tables a vendor also carries describe what MIGHT appear, which is a different
claim -- recording those as "sold by" would have nearly every vendor selling
nearly everything.
"""
import re

from ...archive import values as V

CREATURE_PREFIX = 'records/creatures/'
MARKET_FIELD = 'marketFileName'
FACTION_FIELD = 'factions'
NAME_FIELD = 'description'
STATIC_FIELD = 'marketStaticItems'

# <tier><variant>Table on a factionmarket record. The variant ('Normal') is
# captured but unused -- only Normal ships today, and an Elite/Ultimate
# variant appearing later should be visible rather than silently folded in.
TIER_FIELD = re.compile(r'^(friendly|respected|honored|revered)(\w*)Table$')
STANDING = {'friendly': 'Friendly', 'respected': 'Respected',
            'honored': 'Honored', 'revered': 'Revered'}


def extract(conn, db, tags: dict[str, str]) -> dict[str, int]:
    conn.execute('DELETE FROM vendor_stock')
    conn.execute('DELETE FROM vendor')

    item_ids = {row['path']: row['id']
                for row in conn.execute('SELECT id, path FROM item')}
    faction_of_record = {row['path']: row['id']
                         for row in conn.execute('SELECT path, id FROM faction')}

    stock_cache: dict[str, list[str]] = {}

    def static_items(path: str) -> list[str]:
        if path not in stock_cache:
            found = []
            if path in db:
                for field, values in V.non_default(db.read(path)).items():
                    if field.startswith(STATIC_FIELD):
                        found += [v.lower() for v in values
                                  if isinstance(v, str) and v]
            stock_cache[path] = found
        return stock_cache[path]

    vendor_rows, stock_rows = [], []
    variants, unresolved_faction, unresolved_item = set(), 0, 0
    for path, attrs in db.iter_records(CREATURE_PREFIX):
        market = V.first_str(attrs, MARKET_FIELD)
        if not market:
            continue
        market = market.lower()
        if market not in db:
            continue
        market_attrs = V.non_default(db.read(market))
        tiers = {f: v for f, v in market_attrs.items() if TIER_FIELD.match(f)}
        if not tiers:
            continue            # a general merchant, not a faction vendor

        faction_record = V.first_str(attrs, FACTION_FIELD)
        faction_id = faction_of_record.get(
            faction_record.lower()) if faction_record else None
        if faction_id is None:
            unresolved_faction += 1

        vendor_id = len(vendor_rows) + 1
        name_tag = V.first_str(attrs, NAME_FIELD)
        vendor_rows.append((vendor_id, path,
                            V.clean_name(tags.get(name_tag)) if name_tag else None,
                            faction_id))

        for field, values in tiers.items():
            tier, variant = TIER_FIELD.match(field).groups()
            variants.add(variant)
            for table in values:
                if not isinstance(table, str) or not table:
                    continue
                for item_path in static_items(table.lower()):
                    item_id = item_ids.get(item_path)
                    if item_id is None:
                        unresolved_item += 1
                        continue
                    stock_rows.append((vendor_id, item_id, STANDING[tier]))

    conn.executemany(
        'INSERT INTO vendor (id, path, name, faction_id) VALUES (?,?,?,?)',
        vendor_rows)
    conn.executemany(
        'INSERT OR IGNORE INTO vendor_stock (vendor_id, item_id, standing) '
        'VALUES (?,?,?)', stock_rows)
    conn.commit()
    return {'vendors': len(vendor_rows),
            'vendor-stock rows': len(stock_rows),
            'distinct items sold': len({r[1] for r in stock_rows}),
            'vendors with no faction': unresolved_faction,
            'stock entries not in item': unresolved_item,
            'tier table variants seen': ','.join(sorted(variants))}
