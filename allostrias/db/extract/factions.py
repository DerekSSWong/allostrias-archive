"""records/controllers/factions/** -> the `faction` table.

Small, and the only tricky part is that the identity lives in three places
that do not agree:

  * `myFaction` on the record is the ID, and it is what an item's
    `factionSource` points at.
  * `tagFaction<id>` in the text archives is the display name.
  * the FILENAME is neither, and disagrees with both for two factions:
    factiongdx3_dread.dbr is User19, whose tag reads 'Traps', while
    factiongdx3_traps.dbr is User20, whose tag reads 'The Dread'. The names
    are swapped relative to the files. The tag wins -- it is what the game
    renders -- and the filename is kept only as provenance.
"""
from ...archive import values as V

FACTION_PREFIX = 'records/controllers/factions/'
NAME_TAG = 'tagFaction{}'


def extract(conn, db, tags: dict[str, str]) -> dict[str, int]:
    conn.execute('DELETE FROM faction')

    rows, unnamed = [], 0
    for path, attrs in db.iter_records(FACTION_PREFIX):
        faction_id = V.first_str(attrs, 'myFaction')
        if not faction_id:
            continue
        name = V.clean_name(tags.get(NAME_TAG.format(faction_id)))
        if not name:
            unnamed += 1
        rows.append((faction_id, name, path))

    conn.executemany(
        'INSERT OR REPLACE INTO faction (id, name, path) VALUES (?,?,?)', rows)
    conn.commit()
    linked = conn.execute(
        'SELECT count(DISTINCT s.txt) FROM item_stat s JOIN faction f '
        "ON f.id = s.txt WHERE s.field='factionSource'").fetchone()[0]
    return {'factions': len(rows),
            'without a display name': unnamed,
            'factions that items reference': linked}
