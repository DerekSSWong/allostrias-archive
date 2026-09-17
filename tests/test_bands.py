"""Step 7c gate: base-item roll bands.

Item bases jitter at a flat 20% (BASE_JITTER) rather than carrying their own
jitter like affixes do, and `attributeScalePercent` then scales the subset of
fields that take it. The three things this checks are the three ways the
result can be wrong while still looking right:

  1. A field that draws nothing must come back FIXED, not banded. Armour
     (defensiveProtection) is the headline case -- it is on almost every
     armour piece and a +/-20% band on it would be believable and wrong.
  2. A field nobody has modelled must come back UNMODELED with NO band. Both
     alternatives are lies: a band claims it rolls, a fixed point claims it
     does not.
  3. ONLY EQUIPMENT ROLLS AT ALL. Components, augments and relics are read at
     their stored values -- verified against grimdb, where Mark of the
     Myrmidon shows a flat +120 Health and this code once reported 96-144.
     Their rows carry 'unrolled', which is distinct from 'fixed': fixed is a
     field that draws nothing on a record that does roll.
  4. Scaling applies to flat damage and damage modifiers ONLY. Resistances
     and retaliation modifiers are flagged scales=False in the draw order, so
     a resistance that moved when attributeScalePercent was applied would be
     a silent inflation of every armour piece in the catalogue.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from allostrias import settings as S               # noqa: E402
from allostrias.archive import rolls as R          # noqa: E402
from allostrias.db import catalogue                # noqa: E402

cfg = S.load()
conn = catalogue.connect(cfg.catalogue_db, create=False)
one = lambda sql, *a: conn.execute(sql, a).fetchone()[0]

# -- 1. the band function, against the game's own arithmetic ---------------
# spread = max(1, int(v*pct/100)); lo/hi = v -/+ spread; then trunc-scale if
# the field takes the scale.
for field, value, pct, scale_pct, cls, want in (
        ('defensiveProtection', 108, 20, 40, 'ArmorProtective_Waist', (108, 108, 'fixed')),
        ('defensiveChaos', 30, 20, 40, 'ArmorProtective_Waist', (24, 36, 'rolled')),
        ('defensivePetrify', 35, 20, 40, 'ArmorProtective_Waist', (28, 42, 'rolled')),
        ('retaliationTotalDamageModifier', 50, 20, 40, 'ArmorProtective_Waist', (40, 60, 'rolled')),
        ('offensiveFireModifier', 20, 20, 40, 'ArmorProtective_Waist', (22, 33, 'rolled')),
        ('offensivePhysicalMin', 12, 20, 0, 'WeaponMelee_Axe', (12, 12, 'fixed')),
        ('offensivePhysicalMin', 12, 20, 0, 'ArmorJewelry_Ring', (10, 14, 'rolled')),
        ('notAFieldAnyoneModelled', 10, 20, 40, '', (None, None, 'unmodeled')),
):
    got = R.band(field, value, pct, scale_pct, cls)
    assert got == want, f'band({field}, {value}, class={cls}) = {got}, want {want}'
print(f'{len(R.ROLLED)} fields modelled; 8 band cases exact, '
      'including the Class-gated weapon-damage split')

# -- 2. the three statuses are all populated -------------------------------
status = dict(conn.execute(
    'SELECT roll, count(*) FROM item_stat WHERE roll IS NOT NULL GROUP BY roll'))
print(f'\nitem_stat rows by roll status: {status}')
assert set(status) == {'rolled', 'fixed', 'unmodeled', 'unrolled'}, status
for name in ('rolled', 'fixed', 'unmodeled', 'unrolled'):
    assert status[name] > 0, f'no {name} rows at all'

# Every 'unrolled' row must be on a non-equipment item, and no equipment row
# may be 'unrolled'. This is the invariant the grimdb mismatch came from.
leaked = one("SELECT count(*) FROM item_stat s JOIN item i ON i.id=s.item_id "
             "WHERE s.roll='unrolled' AND i.is_equipment=1")
banded = one("SELECT count(*) FROM item_stat s JOIN item i ON i.id=s.item_id "
             "WHERE s.roll='rolled' AND i.is_equipment=0")
print(f'  equipment marked unrolled: {leaked}, non-equipment given a band: {banded}')
assert leaked == 0, 'an equipment base was treated as not rolling'
assert banded == 0, 'a component/augment/relic was given a roll band'

# The case that exposed it, checked by value.
for field, want in (('characterLife', 120), ('characterDefensiveAbility', 25),
                    ('characterDefensiveBlockRecoveryReduction', 15),
                    ('retaliationPhysicalMin', 180)):
    row = conn.execute(
        "SELECT num, lo, hi, roll FROM item_stat s JOIN item i ON i.id=s.item_id "
        "WHERE i.path='records/items/materia/compb_markofthemyrmidon.dbr' "
        'AND s.field=?', (field,)).fetchone()
    assert row['num'] == want and row['lo'] == row['hi'] == want, \
        f'Mark of the Myrmidon {field}: {dict(row)}, grimdb says a flat {want}'
print('  Mark of the Myrmidon matches grimdb on all four stats, flat')

# The other half: RELICS DO ROLL, and so do the pet bonuses they carry. Both
# numbers below are read off grimdb, and both were wrong at some point -- once
# by banding what does not roll, then by un-banding what does.
for field, want in (('defensiveLife', (23, 33)),
                    ('defensiveElementalResistance', (15, 21)),
                    ('retaliationFearMin', (1, 3))):
    row = conn.execute(
        "SELECT lo, hi, roll FROM item_stat s JOIN item i ON i.id=s.item_id "
        "WHERE i.path='records/items/gearrelic/d103_relic.dbr' AND s.field=?",
        (field,)).fetchone()
    assert (row['lo'], row['hi']) == want and row['roll'] == 'rolled', \
        f'Dirge of Arkovia {field}: {dict(row)}, grimdb says {want[0]}-{want[1]}'
for field, want in (('offensiveTotalDamageModifier', (40, 60)),
                    ('offensiveLifeModifier', (80, 120)),
                    ('characterTotalSpeedModifier', (12, 18))):
    row = conn.execute(
        "SELECT s.lo, s.hi FROM item i JOIN item_bonus ib ON ib.item_id=i.id "
        "JOIN bonus b ON b.id=ib.bonus_id JOIN bonus_stat s ON s.bonus_id=b.id "
        "WHERE i.path='records/items/gearrelic/d103_relic.dbr' "
        "AND b.kind='pet' AND s.field=?", (field,)).fetchone()
    assert (row['lo'], row['hi']) == want, \
        f'Dirge pet bonus {field}: {dict(row)}, grimdb says {want[0]}-{want[1]}'
print('  Dirge of Arkovia matches grimdb on 3 stats and 3 pet bonuses, banded')

# A SKILL LEVEL NEVER ROLLS, anywhere. '+1 to Drain Essence' banded to 0-2 --
# a bonus that might give nothing -- because bonuses.py was banding every
# numeric field whenever the record declared a jitter, instead of asking the
# field model. Asserted across both tables so neither can regress alone.
for table, key in (('item_stat', 'num'), ('bonus_stat', 'value')):
    banded = one(f"SELECT count(*) FROM {table} WHERE field LIKE '%SkillLevel%' "
                 'AND lo IS NOT NULL AND lo != hi')
    assert banded == 0, f'{banded} skill-level rows in {table} carry a band'
print('  no skill-level field carries a band, in either table')

# -- 3. no band may exist without a status, and vice versa -----------------
banded_no_status = one(
    "SELECT count(*) FROM item_stat WHERE lo IS NOT NULL AND roll IS NULL")
unmodeled_with_band = one(
    "SELECT count(*) FROM item_stat WHERE roll='unmodeled' AND lo IS NOT NULL")
fixed_not_point = one(
    "SELECT count(*) FROM item_stat WHERE roll='fixed' AND (lo != num OR hi != num)")
text_banded = one(
    "SELECT count(*) FROM item_stat WHERE txt IS NOT NULL AND lo IS NOT NULL")
print(f'  banded without status {banded_no_status}, unmodeled with a band '
      f'{unmodeled_with_band}, fixed not a point {fixed_not_point}, '
      f'text banded {text_banded}')
assert banded_no_status == 0
assert unmodeled_with_band == 0, 'a band was invented for an unmodelled field'
assert fixed_not_point == 0, 'a fixed field was given a range'
assert text_banded == 0, 'a text value was given a numeric band'

# -- 3b. the unmodelled set is PINNED, not merely small ---------------------
# Almost all unmodelled rows are cosmetics and bookkeeping (maxTransparency,
# physicsMass, itemLevel) and correctly carry no band. Only a couple of dozen
# rows across the whole catalogue are actual STATS this module cannot place.
# The set shrank from 15 fields to 11 when non-equipment stopped rolling: four
# of them occur only on components and relics, which are now 'unrolled'
# rather than unknown.
# They are pinned BY NAME: a count would let a game update add a new rollable
# stat and have it silently join the no-band pile, which is the one outcome
# that looks identical to working.
UNMODELLED_STATS = {
    'defensiveBonusProtection',
    'defensiveElementalResistanceChance',
    'defensivePhysicalChance',
    'defensiveProtectionChance',
    'offensiveFreezeMax',
    'offensiveFumbleDurationMin',
    'offensiveFumbleMin',
    'offensivePercentCurrentLifeMin',
    'retaliationFearMin',
    'retaliationSlowManaLeachDurationMin',
    'retaliationSlowManaLeachMin',
}
found = {row[0] for row in conn.execute(
    "SELECT DISTINCT field FROM item_stat WHERE roll='unmodeled' AND ("
    "field LIKE 'offensive%' OR field LIKE 'defensive%' OR "
    "field LIKE 'retaliation%' OR field LIKE 'character%' OR "
    "field LIKE 'skill%' OR field LIKE 'conversion%')")}
rows = one("SELECT count(*) FROM item_stat WHERE roll='unmodeled' AND ("
           "field LIKE 'offensive%' OR field LIKE 'defensive%' OR "
           "field LIKE 'retaliation%' OR field LIKE 'character%' OR "
           "field LIKE 'skill%' OR field LIKE 'conversion%')")
print(f'\nunmodelled STAT fields: {len(found)} distinct over {rows} rows '
      f'(of {status["unmodeled"]} unmodelled rows overall)')
assert found == UNMODELLED_STATS, (
    f'new unmodelled stat fields: {sorted(found - UNMODELLED_STATS)}; '
    f'no longer unmodelled: {sorted(UNMODELLED_STATS - found)}')
print('  exactly the pinned set -- no stat quietly joined the no-band pile')

# -- 4. armour never rolls -------------------------------------------------
# 'unrolled' is fine here too: two relics carry armour, and on a record that
# never rolls the field is unrolled rather than fixed. What must never appear
# is 'rolled'.
armour = dict(conn.execute(
    "SELECT roll, count(*) FROM item_stat WHERE field='defensiveProtection' "
    "GROUP BY roll"))
print(f"\ndefensiveProtection (armour) statuses: {armour}")
assert set(armour) <= {'fixed', 'unrolled'}, armour
assert armour.get('fixed', 0) > 1000, armour

# -- 5. resistances must NOT take attributeScalePercent --------------------
# If they did, every scaled armour piece would report inflated resists. Check
# a real one rather than trusting the flag.
row = conn.execute("""
    SELECT s.num, s.lo, s.hi FROM item i JOIN item_stat s ON s.item_id=i.id
    WHERE i.path='records/items/gearaccessories/waist/b201f_waist.dbr'
      AND s.field='defensiveChaos'""").fetchone()
assert (row['lo'], row['hi']) == (24, 36), dict(row)
print(f"  Gargoyle Girdle Chaos Resist: stored {row['num']:.0f}, "
      f"band {row['lo']:.0f}-{row['hi']:.0f} (scale 40% correctly NOT applied)")

# -- 6. what the benchmark item now reports --------------------------------
print('\nGargoyle Girdle, level 94 -- stats with ranges:')
for r in conn.execute("""
        SELECT s.field, s.num, s.lo, s.hi, s.roll
        FROM item i JOIN item_stat s ON s.item_id=i.id
        WHERE i.path='records/items/gearaccessories/waist/b201f_waist.dbr'
          AND s.roll IN ('rolled','fixed')
          AND (s.field LIKE 'defensive%' OR s.field LIKE 'retaliation%'
               OR s.field LIKE 'conversion%')
        ORDER BY s.roll DESC, s.field"""):
    span = (f"{r['lo']:.0f}-{r['hi']:.0f}" if r['roll'] == 'rolled'
            else f"{r['num']:.0f} exact")
    print(f"  {r['field']:34} {r['num']:6.0f}   {span:12} [{r['roll']}]")

unmodelled = conn.execute("""
    SELECT s.field FROM item i JOIN item_stat s ON s.item_id=i.id
    WHERE i.path='records/items/gearaccessories/waist/b201f_waist.dbr'
      AND s.roll='unmodeled'""").fetchall()
print(f"  ({len(unmodelled)} fields on this item are unmodelled, no band claimed)")

conn.close()
print('\nSTEP 7c PASS')
