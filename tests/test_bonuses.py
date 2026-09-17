"""Step 9a gate: what an item grants by reference.

Three fields point at records holding the actual effect, and until they are
followed the item looks emptier than it is. What this checks:

  1. ONLY RELICS GET COMPLETION BONUSES. 83 components carry bonusTableName
     pointing at neatly slot-matched pools, and the game ignores every one --
     the field is inherited from Titan Quest, where charms did have them.
     That shape was once read here as proof of a mechanic; it is not, and a
     curated dead field is exactly what a structural proxy looks like when it
     is wrong.
  1b. A completion POOL is a choice, not a sum. Dirge of Arkovia's ten members
     are ten mutually exclusive outcomes; losing pool_path would read as one
     relic granting all ten at once.
  2. Pool members ROLL. They are LootRandomizer records with their own jitter,
     so 8% Fire Resist at jitter 50 is 4-12 and not a flat 8.
  3. Every unresolved skill name has a DEMONSTRATED cause. Skill_Modifier
     records carry no skillDisplayName by design -- they are described on the
     skill they modify -- so a 0% resolution rate there is correct and a
     fallback would invent a second skill with the same name. The gate derives
     that rather than tolerating the count.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from allostrias import settings as S               # noqa: E402
from allostrias.archive import arz as A            # noqa: E402
from allostrias.archive import values as V         # noqa: E402
from allostrias.db import catalogue                # noqa: E402

cfg = S.load()
conn = catalogue.connect(cfg.catalogue_db, create=False)
one = lambda sql, *a: conn.execute(sql, a).fetchone()[0]

kinds = dict(conn.execute('SELECT kind, count(*) FROM bonus GROUP BY kind'))
print(f'bonus records: {kinds}')
assert set(kinds) == {'completion', 'pet'}, kinds

# No class but ItemArtifact may hold a completion bonus, however many of them
# declare a pool. Checked in both directions so neither half can rot.
wrong = conn.execute(
    "SELECT i.class, count(*) n FROM item_bonus ib JOIN item i ON i.id=ib.item_id "
    "WHERE ib.relation='completion' AND i.class != 'ItemArtifact' "
    'GROUP BY i.class').fetchall()
relic_pools = one("SELECT count(DISTINCT ib.item_id) FROM item_bonus ib "
                  "JOIN item i ON i.id=ib.item_id "
                  "WHERE ib.relation='completion' AND i.class='ItemArtifact'")
declaring = one("SELECT count(DISTINCT i.id) FROM item i "
                'JOIN item_stat s ON s.item_id=i.id '
                "WHERE s.field='bonusTableName' AND i.class='ItemRelic'")
print(f'\nrelics with a completion pool: {relic_pools}')
print(f'components DECLARING a dead bonusTableName: {declaring} (all ignored)')
assert not wrong, f'non-relics given a completion bonus: {[dict(r) for r in wrong]}'
assert relic_pools > 50, relic_pools
assert declaring > 50, 'the dead-field case vanished; the check means nothing now'

# -- 1. the pool is a choice ----------------------------------------------
pools = one('SELECT count(DISTINCT pool_path) FROM item_bonus '
            "WHERE relation='completion'")
sizes = conn.execute("""
    SELECT pool_path, count(*) n FROM item_bonus WHERE relation='completion'
    GROUP BY item_id, pool_path ORDER BY n DESC LIMIT 1""").fetchone()
print(f'\n{pools} completion pools; largest gives one of {sizes["n"]} outcomes')
assert pools > 10, pools
assert sizes['n'] > 1, 'a pool with one member -- pool grouping was lost'
no_pool = one("SELECT count(*) FROM item_bonus WHERE relation='completion' "
              'AND pool_path IS NULL')
assert no_pool == 0, f'{no_pool} completion bonuses lost their pool'

# -- 2. pool members roll, pet bonuses do not -----------------------------
# A pet bonus carries no jitter of its own: it rolls when the item holding it
# rolls. Dirge of Arkovia's pet bonus IS banded because its parent is a relic;
# one hanging off a component is not. Checked as that rule, not as a blanket.
rolled = one("SELECT count(*) FROM bonus_stat s JOIN bonus b ON b.id=s.bonus_id "
             "WHERE b.kind='completion' AND s.lo != s.hi")
pet_banded = one("SELECT count(*) FROM bonus_stat s JOIN bonus b ON b.id=s.bonus_id "
                 "WHERE b.kind='pet' AND s.lo != s.hi")
pet_on_still = one(
    'SELECT count(*) FROM bonus_stat s '
    'JOIN bonus b ON b.id = s.bonus_id '
    'JOIN item_bonus x ON x.bonus_id = b.id '
    'JOIN item i ON i.id = x.item_id '
    "WHERE b.kind='pet' AND s.lo != s.hi AND i.is_equipment = 0 "
    "AND i.class != 'ItemArtifact'")
print(f'  completion stats with a real band: {rolled}')
print(f'  pet stats banded: {pet_banded}; of those, on a non-rolling item: '
      f'{pet_on_still}')
# Small on purpose. Most relic completion bonuses are "+1 to two skills",
# and a skill level never rolls -- so only the stat-valued members band at
# all. The old threshold of 100 was calibrated when 83 components were
# wrongly contributing pools.
assert rolled > 0, 'no completion bonus bands at all'
assert pet_banded > 0, 'no pet bonus rolls -- Dirge of Arkovia shows they do'
assert pet_on_still == 0, 'a pet bonus rolled on an item that does not roll'

# -- 3. unresolved skill names must have a derived cause ------------------
print('\nitem_skill by relation:')
for row in conn.execute("""SELECT relation, count(*) n, sum(skill_name IS NOT NULL) named
                           FROM item_skill GROUP BY relation ORDER BY n DESC"""):
    print(f'  {row["relation"]:10} {row["n"]:6} links, {row["named"]:6} named '
          f'({100 * row["named"] // row["n"]}%)')

unresolved = [r[0] for r in conn.execute(
    'SELECT DISTINCT skill_path FROM item_skill WHERE skill_name IS NULL')]
with A.Database(cfg.arz_paths) as db:
    has_tag = [p for p in unresolved
               if p in db and V.first_str(V.non_default(db.read(p)),
                                          'skillDisplayName')]
print(f'\n{len(unresolved)} distinct skill records resolved to no name')
print(f'  of those, {len(has_tag)} DO declare a skillDisplayName  <- must be 0')
assert not has_tag, (
    f'{len(has_tag)} skills have a display tag that did not resolve: '
    f'{has_tag[:3]} -- the lookup is wrong, not the data')
assert one("SELECT count(*) FROM item_skill WHERE relation='mastery' "
           'AND skill_name IS NULL') == 0, 'a mastery lost its name'

# -- 4. the worked examples ------------------------------------------------
print("\nAether Soul -- its own stats, then its completion pool:")
for row in conn.execute("""
        SELECT s.field, s.num FROM item i JOIN item_stat s ON s.item_id=i.id
        WHERE i.name='Aether Soul' AND s.roll='rolled' ORDER BY s.field"""):
    print(f"   own       {row['field']:32} {row['num']:.0f}")
for row in conn.execute("""
        SELECT b.path, s.field, s.lo, s.hi FROM item i
        JOIN item_bonus ib ON ib.item_id=i.id
        JOIN bonus b       ON b.id=ib.bonus_id
        JOIN bonus_stat s  ON s.bonus_id=b.id
        WHERE i.name='Aether Soul' ORDER BY s.field LIMIT 5"""):
    print(f"   one of    {row['field']:32} {row['lo']:.0f}-{row['hi']:.0f}")

print("\nGargoyle Girdle lvl 94 -- its skills, now named:")
for row in conn.execute("""
        SELECT k.relation, k.skill_name, k.level FROM item i
        JOIN item_skill k ON k.item_id=i.id
        WHERE i.name='Gargoyle Girdle' AND i.level_req=94"""):
    print(f"   {row['relation']:9} +{row['level']} {row['skill_name']}")

conn.close()
print('\nSTEP 9a PASS')
