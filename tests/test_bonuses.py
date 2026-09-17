"""Step 9a gate: what an item grants by reference.

Three fields point at records holding the actual effect, and until they are
followed the item looks emptier than it is. What this checks:

  1. A completion POOL is a choice, not a sum. Aether Soul's nine members are
     nine mutually exclusive outcomes; losing pool_path would read as a
     component granting all nine at once.
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
rolled = one("SELECT count(*) FROM bonus_stat s JOIN bonus b ON b.id=s.bonus_id "
             "WHERE b.kind='completion' AND s.lo != s.hi")
pet_banded = one("SELECT count(*) FROM bonus_stat s JOIN bonus b ON b.id=s.bonus_id "
                 "WHERE b.kind='pet' AND s.lo != s.hi")
pet_jitter = one("SELECT count(*) FROM bonus WHERE kind='pet' AND jitter IS NOT NULL")
print(f'  completion stats with a real band: {rolled}')
print(f'  pet stats with a band: {pet_banded}, pet records with jitter: {pet_jitter}')
assert rolled > 100, rolled
assert pet_banded == 0, 'a pet bonus was given a roll band'
assert pet_jitter == 0, 'a pet bonus was given a jitter value'

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
