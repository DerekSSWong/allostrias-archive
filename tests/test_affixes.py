"""Step 7a gate: affix stat lines and their roll bands.

The oracle is gd-lib's affix_lines.csv -- 23,396 rows whose lo/hi were solved
and verified against grimdb and GrimTools. It is used as a TEST FIXTURE only;
this repo regenerates every line from the .arz, so a porting error in
roll_band or in the extractor shows up as a diff against known-good numbers
rather than as plausible output.

The CSV is a narrower set than the archives (uniques and dead tiers were
removed from it), so records it does not mention are not failures. Records it
DOES mention must agree exactly.
"""
import collections
import csv
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from _oracle import sibling                         # noqa: E402
from allostrias import settings as S               # noqa: E402
from allostrias.archive.rolls import roll_band     # noqa: E402
from allostrias.db import catalogue                # noqa: E402

# The oracle is gd-lib's checkout beside this one, found relative to the repo.
# It must never be written down here: a hardcoded path would both break on any
# other machine and put this machine's layout in a public repo.
ORACLE_RELPATH = os.path.join('.gdlib', 'affix_data', 'affix_lines.csv')
PREFIX = 'records/items/lootaffixes/'

cfg = S.load()
oracle_path = sibling(ORACLE_RELPATH)
conn = catalogue.connect(cfg.catalogue_db, create=False)
one = lambda sql, *a: conn.execute(sql, a).fetchone()[0]

# -- 1. the roll rule itself ----------------------------------------------
for value, jitter, want in ((8, 20, (7, 9)), (2, 28, (1, 3)), (95, 5, (91, 99)),
                            (10, 28, (8, 12)), (4, 22, (3, 5)), (7, 0, (7, 7))):
    got = roll_band(value, jitter)
    assert got == want, f'roll_band({value},{jitter}) = {got}, want {want}'
print('roll_band: 6 verified values reproduce, including both small-value cases')

# -- 2. counts ------------------------------------------------------------
# The Prefix/Suffix split is checked against the ORACLE's own split over the
# records they share, not against numbers written into this file. A constant
# invented here would agree with whatever the extractor did.
total = one('SELECT count(*) FROM affix')
stats = one('SELECT count(*) FROM affix_stat')
kinds = dict(conn.execute('SELECT kind, count(*) FROM affix GROUP BY kind'))
print(f'\naffixes {total}  {kinds}  stat rows {stats}')
assert total > 4898, f'{total} is fewer than the oracle has; records were lost'
assert set(kinds) == {'Prefix', 'Suffix', 'Crafting'}, kinds

# -- 3. a name is not an identity -----------------------------------------
named = one("SELECT count(*) FROM affix WHERE name='Impervious'")
distinct_sets = one("""
    SELECT count(*) FROM (
      SELECT a.id FROM affix a WHERE a.name='Impervious' GROUP BY a.id)""")
print(f"\n'Impervious' resolves to {named} records")
assert named > 1, 'the ambiguity this schema exists for is missing'
shared = one("""SELECT count(*) FROM (
    SELECT name FROM affix WHERE name IS NOT NULL
    GROUP BY name HAVING count(*) > 1)""")
print(f'  {shared} affix names are shared by more than one record')
assert shared > 100, shared

# -- 4. duplicates are KEPT ------------------------------------------------
# Losing these would change drop weights invisibly; see the schema note.
for path in ('records/items/lootaffixes/prefix/b_class001_b.dbr',
             'records/items/lootaffixes/prefix/b_class001_c.dbr'):
    assert one('SELECT count(*) FROM affix WHERE path=?', path) == 1, \
        f'{path} was deduplicated away'
print('  byte-identical _b/_c siblings both present, as intended')

# -- 5. diff every numeric line against the oracle -------------------------
if not os.path.isfile(oracle_path):
    # SKIPS, and says so at the top of its voice. This used to exit FAIL,
    # which made gd-lib a requirement of allostrias's own test suite on every
    # machine -- and allostrias has to stand alone. The distinction that
    # mattered is kept: this is not a pass, it is an UNPROVEN, and the word is
    # in the output either way.
    print(f'SKIPPED -- no oracle at {oracle_path}, so the bands are UNPROVEN '
          f'in this tree. Exits 0 on purpose: gd-lib is an oracle this gate '
          f'borrows, never something allostrias needs.')
    sys.exit(0)

# Keyed by bucket: a pet line and a player line can share a field name, and a
# single dict let one overwrite the other.
oracle = collections.defaultdict(dict)
oracle_pet = collections.defaultdict(dict)
oracle_records = set()
for row in csv.DictReader(open(oracle_path, encoding='utf-8')):
    oracle_records.add(PREFIX + row['file'])
    if row['value'] in ('', None) or row['lo'] == '':
        continue                      # skill/text lines carry no band
    (oracle_pet if row['bucket'] == 'pet' else oracle)[PREFIX + row['file']][row['field']] = (
        float(row['value']), float(row['lo']), float(row['hi']))

mine = collections.defaultdict(dict)
for row in conn.execute(
        'SELECT a.path, s.field, s.value, s.lo, s.hi FROM affix a '
        'JOIN affix_stat s ON s.affix_id=a.id WHERE s.value IS NOT NULL'):
    mine[row['path']][row['field']] = (row['value'], row['lo'], row['hi'])

# EVERY record the oracle knows must exist here. Checked at record level, not
# via the numeric-line dict above -- 30 records have only skill/text lines and
# would look absent if presence were inferred from having a band.
stored = {row['path'] for row in conn.execute('SELECT path FROM affix')}
lost = sorted(oracle_records - stored)
assert not lost, f'{len(lost)} oracle records missing from the table: {lost[:3]}'
print(f'\nall {len(oracle_records)} oracle records present '
      f'({len(stored) - len(oracle_records)} extra: uniques and dead tiers)')

shared_records = set(oracle) & set(mine)

# Kind assignment comes from the folder and nothing else, so prove it against
# the oracle's independent labelling of the same records.
oracle_kinds, my_kinds = collections.Counter(), collections.Counter()
for row in csv.DictReader(open(oracle_path, encoding='utf-8')):
    oracle_kinds[PREFIX + row['file']] = row['kind']
for row in conn.execute('SELECT path, kind FROM affix'):
    my_kinds[row['path']] = row['kind']
disagree = [p for p in shared_records if oracle_kinds[p] != my_kinds[p]]
assert not disagree, f'{len(disagree)} records filed as the wrong kind: {disagree[:3]}'
print(f'\nkind agrees with the oracle on all {len(shared_records)} shared records')
compared = value_bad = band_bad = 0
examples = []
for path in shared_records:
    for field, (value, lo, hi) in oracle[path].items():
        got = mine[path].get(field)
        if got is None:
            continue                      # oracle derives rows we store raw
        compared += 1
        if abs(got[0] - value) > 1e-6:
            value_bad += 1
            if len(examples) < 3:
                examples.append(f'  value {path} [{field}]: {got[0]} vs {value}')
        elif abs(got[1] - lo) > 1e-6 or abs(got[2] - hi) > 1e-6:
            band_bad += 1
            if len(examples) < 3:
                examples.append(
                    f'  band {path} [{field}]: {got[1]}-{got[2]} vs {lo}-{hi}')

print(f'\nvs oracle: {len(shared_records)} records in both, {compared} numeric '
      f'lines compared')
for line in examples:
    print(line)
assert compared >= 15000, f'only {compared} lines compared; too few to mean anything'
assert value_bad == 0, f'{value_bad} stored values disagree'
assert band_bad == 0, f'{band_bad} roll bands disagree'
print('  every value and every band identical')

# -- 5b. pet stats: the record the affix names, banded by the AFFIX's jitter --
mine_pet = collections.defaultdict(dict)
for row in conn.execute(
        'SELECT a.path, s.field, s.value, s.lo, s.hi FROM affix a '
        'JOIN affix_pet_stat s ON s.affix_id=a.id WHERE s.value IS NOT NULL'):
    mine_pet[row['path']][row['field']] = (row['value'], row['lo'], row['hi'])
pet_bad = []
pet_compared = 0
for path, lines in oracle_pet.items():
    for field, want in lines.items():
        pet_compared += 1
        got = mine_pet.get(path, {}).get(field)
        if got is None or any(abs(a - b) > 1e-6 for a, b in zip(got, want)):
            pet_bad.append(f'  {path} [{field}]: {got} vs {want}')
# Both directions: every pet line the oracle has, and no pet line it lacks on a
# record it knows.
extra = [f'  {p} [{f}]' for p in mine_pet if p in oracle_records
         for f in mine_pet[p] if f not in oracle_pet.get(p, {})]
print(f'\npet lines vs oracle: {pet_compared} compared, {len(pet_bad)} wrong, '
      f'{len(extra)} extra')
for line in (pet_bad + extra)[:5]:
    print(line)
assert pet_compared >= 400, f'only {pet_compared} pet lines compared'
assert not pet_bad and not extra, 'pet lines disagree with the oracle'
named = one("SELECT count(DISTINCT affix_id) FROM affix_stat WHERE field='petBonusName'")
carried = one('SELECT count(DISTINCT affix_id) FROM affix_pet_stat')
assert named == carried, f'{named} affixes name a pet bonus, {carried} carry its stats'
print(f'  all {named} affixes naming a pet bonus carry its stats')

# -- 6. the worked example -------------------------------------------------
print('\nImpervious tiers (Pierce + partner resist):')
for row in conn.execute("""
        SELECT a.path, a.level_req, a.jitter,
               group_concat(s.field || ' ' || CAST(s.lo AS INT) || '-'
                            || CAST(s.hi AS INT), ', ') lines
        FROM affix a JOIN affix_stat s ON s.affix_id=a.id
        WHERE a.name='Impervious' AND a.path LIKE '%ad009b%'
        GROUP BY a.id ORDER BY a.level_req"""):
    print(f"  {os.path.basename(row['path']):34} lvl {row['level_req'] or '-':>3} "
          f"jit {row['jitter']:>4.0f}  {row['lines']}")

conn.close()
print('\nSTEP 7a PASS')
