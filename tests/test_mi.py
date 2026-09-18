"""Step 8b' gate: Monster Infrequent membership.

No structural signal proves MI-ness, so the rule is a heuristic and the gate
has to check it against something other than itself. Two independent things
are checked:

  1. THE TRAP. itemClassification=Rare appears on 209 names of faction VENDOR
     gear and 7 of monster-worn enemygear. Green does not mean MI. Folder is
     the only thing separating them, and flagging those would put 216 names
     that no monster drops into a farming list.
  2. CONTAINMENT, not equality. The five mt_monsterinfrequents_* master tables
     are the developers' own roster. Every name they reach must be flagged an
     MI here -- if the devs call it one and this rule does not, the rule is
     wrong. The converse is NOT asserted: the pools are reached through loot
     tables and miss items that are not monster-dropped or that the walk
     cannot see, so names this rule adds are recorded rather than treated as
     errors.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from allostrias import settings as S               # noqa: E402
from allostrias.archive import arz as A            # noqa: E402
from allostrias.db import catalogue                # noqa: E402
from allostrias.db.extract import mi               # noqa: E402

cfg = S.load()
conn = catalogue.connect(cfg.catalogue_db, create=False)
one = lambda sql, *a: conn.execute(sql, a).fetchone()[0]

records = one('SELECT count(*) FROM item WHERE is_mi=1')
names = one('SELECT count(DISTINCT name) FROM item WHERE is_mi=1')
print(f'{records} MI records across {names} names')
assert 350 < names < 500, names

print('\nby folder:')
for row in conn.execute('SELECT folder, count(*) n, count(DISTINCT name) d '
                        'FROM item WHERE is_mi=1 GROUP BY folder ORDER BY n DESC'):
    print(f'  {row["folder"]:18} {row["n"]:5} records {row["d"]:4} names')

# -- 1. the trap ----------------------------------------------------------
for folder in ('faction', 'enemygear'):
    leaked = one('SELECT count(*) FROM item WHERE is_mi=1 AND folder=?', folder)
    assert leaked == 0, f'{leaked} {folder} items flagged as MI -- green is not MI'
rare_faction = one("SELECT count(*) FROM item "
                   "WHERE classification='Rare' AND folder='faction'")
print(f'\n{rare_faction} faction items are classified Rare and none is flagged MI')
assert rare_faction > 0, 'the trap needs to exist for its absence to mean anything'

# -- 2. the developers' roster must be contained --------------------------
mine = {row[0] for row in conn.execute(
    'SELECT DISTINCT name FROM item WHERE is_mi=1')}
with A.Database(cfg.arz_paths) as db:
    dev = mi.dev_pool_names(conn, db)
missing = sorted(dev - mine)
extra = sorted(mine - dev)
print(f'\ndev pools reach {len(dev)} MI names; this rule flags {len(mine)}')
print(f'  agreed                       {len(mine & dev)}')
print(f'  dev roster not flagged here  {len(missing)}   <- must be 0')
print(f'  flagged here, pools miss     {len(extra)}   <- recorded, not an error')
for name in extra[:5]:
    print(f'     {name}')
assert not missing, (
    f'{len(missing)} names the developers call MIs are not flagged: '
    f'{missing[:5]}')

# -- 3. the worked example -------------------------------------------------
girdle = conn.execute(
    "SELECT name, is_mi, classification, folder FROM item "
    "WHERE path='records/items/gearaccessories/waist/b201f_waist.dbr'").fetchone()
print(f"\n{girdle['name']}: is_mi={girdle['is_mi']} "
      f"({girdle['classification']}, {girdle['folder']})")
assert girdle['is_mi'] == 1, dict(girdle)

# -- the shortcut mi takes must equal the sweep it replaced ----------------
# extract/mi.py asks the catalogue which records are blueprints instead of
# sweeping all 26,001 under records/items/ to find them. That is only safe if
# the two agree EXACTLY, so this does the sweep -- 7 s, once, in a gate, where
# slow costs nothing -- and requires the sets to be identical.
#
# ⚠️ THIS IS NOT A RESTATEMENT OF WHAT mi DOES. It derives the blueprint set
# from the archives independently; a change in `items` that stopped recording
# a Class would break the query and be caught here, which is the whole reason
# the check cannot live in extract/mi.py itself.
from allostrias.archive import values as _V         # noqa: E402

queried = {row[0] for row in conn.execute(
    'SELECT path FROM item WHERE class = ?', (mi.FORMULA_CLASS,))}
with A.Database(cfg.arz_paths) as _db:
    swept = {path for path, attrs in _db.iter_records('records/items/')
             if _V.first_str(attrs, 'Class') == mi.FORMULA_CLASS}
assert queried == swept, (
    f'the blueprint set mi reads from the catalogue ({len(queried)}) does not '
    f'match the archives ({len(swept)}): missing {sorted(swept - queried)[:3]}, '
    f'extra {sorted(queried - swept)[:3]}')
assert swept, 'the sweep found no blueprints at all -- the check is vacuous'
print(f'  blueprint roster: {len(queried)} from the catalogue == {len(swept)} '
      f'swept from records/items/')

conn.close()
print('\nSTEP 8b-prime PASS')
