"""Step 8c gate: spawn zones, and the farm ranking built on them.

This is the only table in the catalogue that is not derived from the game
files, so it is the only one that can be wrong in ways the archives cannot
contradict. Three things are checked:

  1. The parse either produced a full table or nothing. spawn.parse refuses
     rather than returning a short one, because a moved anchor, a changed
     minifier and a truncated download all yield SOME rows.
  2. Zone tags resolve to names through the LOCAL text archives. That is the
     cross-check that the two sides really do speak the same tag vocabulary --
     if grimtools' zone tags stopped matching the game's, the join would go
     quietly empty rather than fail.
  3. A failed fetch leaves the table empty and the build standing. Exercised
     directly, since the failure path is the one that will actually run on a
     machine with no network.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from allostrias import settings as S               # noqa: E402
from allostrias.archive import spawn               # noqa: E402
from allostrias.db import catalogue                # noqa: E402

GIRDLE = 'records/items/gearaccessories/waist/b201f_waist.dbr'
# Rarity order for the farm ranking. Rarer droppers are worth more per
# placement: one guaranteed boss beats a field of trash that shares a table.
RARITY_WEIGHT = {'SuperBoss': 16, 'Boss': 8, 'Hero': 4, 'Champion': 2,
                 'Common': 1, 'Quest': 1}

cfg = S.load()
conn = catalogue.connect(cfg.catalogue_db, create=False)
one = lambda sql, *a: conn.execute(sql, a).fetchone()[0]

meta = dict(conn.execute('SELECT key, value FROM spawn_meta'))
if 'error' in meta:
    sys.exit(f'FAIL: the spawn fetch failed and zones are empty: {meta["error"]}\n'
             'The build is meant to survive this, but the gate must not pass on it.')

rows = one('SELECT count(*) FROM monster_zone')
zones = one('SELECT count(DISTINCT zone_tag) FROM monster_zone')
monsters = one('SELECT count(DISTINCT monster_tag) FROM monster_zone')
print(f'{rows} spawn rows, {zones} zones, {monsters} monsters, '
      f'grimtools {meta.get("game_version")}')
assert rows > 25000, rows
assert 200 < zones < 500, zones

# -- zone tags must resolve against the LOCAL text archives ----------------
unnamed = one('SELECT count(*) FROM monster_zone WHERE zone_name IS NULL')
print(f'  zone tags with no local name: {unnamed}')
assert unnamed == 0, (
    f'{unnamed} zone tags grimtools uses do not exist in the game text -- the '
    'two sides no longer share a tag vocabulary and the join is unreliable')

# -- the monster tags must join to real holders ---------------------------
joined = one("""SELECT count(DISTINCT h.id) FROM holder h
                JOIN monster_zone z ON z.monster_tag = h.name_tag
                WHERE h.is_monster=1""")
print(f'  {joined} monster holders join to a zone by description tag')
assert joined > 500, joined

# -- a failed fetch must not raise ----------------------------------------
try:
    spawn.fetch('https://www.grimtools.com/definitely-not-a-real-path.js')
except spawn.SpawnError as exc:
    print(f'  bad URL raises SpawnError, not a crash: {str(exc)[:60]}...')
else:
    raise AssertionError('a bad URL did not raise SpawnError')

# -- the payoff -----------------------------------------------------------
print('\nWhere to farm a Gargoyle Girdle (rarity-weighted):')
print(f"  {'zone':34} {'score':>6}  droppers")
farm = conn.execute("""
    SELECT z.zone_name,
           sum(z.placements * CASE h.classification
                 WHEN 'SuperBoss' THEN 16 WHEN 'Boss' THEN 8
                 WHEN 'Hero' THEN 4 WHEN 'Champion' THEN 2 ELSE 1 END) score,
           group_concat(DISTINCT h.name) droppers
    FROM item_drop d
    JOIN item i      ON i.id = d.item_id
    JOIN holder h    ON h.id = d.holder_id
    JOIN monster_zone z ON z.monster_tag = h.name_tag
    WHERE i.path = ? AND h.is_monster = 1
    GROUP BY z.zone_name
    ORDER BY score DESC LIMIT 8""", (GIRDLE,)).fetchall()
for row in farm:
    names = row['droppers']
    if len(names) > 46:
        names = names[:43] + '...'
    print(f"  {row['zone_name'][:34]:34} {row['score']:6}  {names}")
assert farm, 'no farm locations for a Monster Infrequent with 12 known droppers'
assert all(r['zone_name'] for r in farm)
print(f'  ({len(farm)} of '
      f'{one("""SELECT count(DISTINCT z.zone_name) FROM item_drop d
              JOIN item i ON i.id=d.item_id JOIN holder h ON h.id=d.holder_id
              JOIN monster_zone z ON z.monster_tag=h.name_tag
              WHERE i.path=? AND h.is_monster=1""", GIRDLE)} zones shown)')

conn.close()
print('\nSTEP 8c PASS')
