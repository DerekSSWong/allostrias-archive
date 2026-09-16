"""Spawn zones, from grimtools' published bundle.

The only extractor that reaches the network, and the only one whose output
cannot be re-derived from the game files. Both facts shape it:

  * IT NEVER FAILS THE BUILD. A download that times out, a moved URL, a
    changed bundle format -- all leave monster_zone empty and record why in
    spawn_meta. Everything else in the catalogue still builds. Zones missing
    is a visible, recoverable state; zones invented would not be.
  * IT NEVER PARTIALLY SUCCEEDS. spawn.parse refuses rather than returning a
    short table, because every failure mode there yields SOME rows. If it
    raises, nothing is written at all.
"""
from ...archive import spawn


def extract(conn, _db, tags: dict[str, str]) -> dict[str, int | str]:
    conn.execute('DELETE FROM monster_zone')
    conn.execute('DELETE FROM spawn_meta')

    try:
        rows, meta = spawn.parse(spawn.fetch())
    except spawn.SpawnError as exc:
        # Recorded, not raised. The build continues without zones.
        conn.execute(
            'INSERT INTO spawn_meta (key, value) VALUES (?, ?)',
            ('error', str(exc)))
        conn.commit()
        return {'zones': 0, 'spawn rows': 0, 'fetch': f'FAILED: {exc}'}

    conn.executemany(
        'INSERT OR REPLACE INTO monster_zone '
        '(monster_tag, zone_tag, zone_name, placements) VALUES (?,?,?,?)',
        [(monster_tag, zone_tag, tags.get(zone_tag), placements)
         for monster_tag, zone_tag, placements in rows])
    conn.executemany(
        'INSERT INTO spawn_meta (key, value) VALUES (?, ?)',
        [(key, str(value)) for key, value in sorted(meta.items())])
    conn.commit()

    unnamed = sum(1 for _m, zone_tag, _n in rows if not tags.get(zone_tag))
    return {'spawn rows': len(rows),
            'zones': meta['zones'],
            'monsters placed': meta['monsters'],
            'zone tags with no name': unnamed,
            'grimtools version': meta['game_version']}
