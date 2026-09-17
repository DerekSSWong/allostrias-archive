"""Gate: Item Assistant's collection, and the half of the stash it holds.

WHAT THIS IS REALLY GUARDING is a boundary. Everything in stash.sqlite came out
of a file this project decodes byte by byte and verifies against its own
checksum. Everything here came out of another program's database, and there is
no checksum -- so the checks are about whether IAGD still means what it meant,
and whether we carried it across without inventing anything.

Three of them are worth stating plainly because they are decisions, not
measurements:

  * IAGD's `Rarity` and `Name` are NOT stored, and this asserts their absence.
    `Rarity` is a colour name one tier below the catalogue's word for the same
    item; `Name` is a rendered display string. Both look authoritative and are
    not. The skew is reported live underneath, as the evidence for the rule.
  * Orphans are dropped on the way in, so the count here must be lower than
    the source's by exactly the number of rows pointing at nothing.
  * An unconfigured `iagd` produces NO database, not an empty one. An empty
    database answers "you hold nothing" to a question that was never asked.
"""
import os
import sqlite3
import sys
import tempfile
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from allostrias import settings as S               # noqa: E402
from allostrias.db import iagd                     # noqa: E402

cfg = S.load()

# -- 0. unconfigured is a first-class case ---------------------------------
with tempfile.TemporaryDirectory() as workdir:
    blank = SimpleNamespace(iagd=None,
                            stash_iagd_db=os.path.join(workdir, 'x.sqlite'))
    assert iagd.refresh(blank) is None, 'refresh claimed to build without a path'
    assert not os.path.exists(blank.stash_iagd_db), \
        'an unconfigured iagd produced a database -- an empty collection and ' \
        'an unasked question are not the same fact'
print('  iagd unconfigured -> no database at all')

if not cfg.iagd:
    print('\nSKIPPED: iagd is not configured in settings.ini, so nothing below '
          'can run. This is not a pass.')
    raise SystemExit(0)

# -- 1. the reader, against the live database ------------------------------
data = iagd.read_collection(cfg.iagd)
print(f'  read {len(data["items"])} items, {len(data["records"])} records, '
      f'{data["orphan_records"]} orphan record(s) dropped')

src = sqlite3.connect('file:' + cfg.iagd + '?mode=ro', uri=True)
raw_items = src.execute('SELECT count(*) FROM PlayerItem').fetchone()[0]
raw_records = src.execute('SELECT count(*) FROM PlayerItemRecord').fetchone()[0]
assert len(data['items']) == raw_items, 'items were lost between source and reader'
assert len(data['records']) + data['orphan_records'] == raw_records, \
    'the record count does not account for what was dropped'

# -- 2. build, and check the carry-across ----------------------------------
counts = iagd.refresh(cfg)
assert counts['items'] == len(data['items'])
conn = sqlite3.connect(cfg.stash_iagd_db)
conn.row_factory = sqlite3.Row
one = lambda q, *a: conn.execute(q, a).fetchone()[0]

assert one('SELECT count(*) FROM iagd_item') == raw_items
assert one('SELECT count(*) FROM iagd_item_record') == raw_records - data['orphan_records']
assert one('SELECT count(*) FROM iagd_item_record r LEFT JOIN iagd_item i '
           'ON i.id = r.item_id WHERE i.id IS NULL') == 0, \
    'an orphan record survived the import'

# '' is IAGD's spelling of "nothing here"; NULL is ours, and only ours.
blanks = one("SELECT count(*) FROM iagd_item WHERE '' IN (prefix_path, "
             "suffix_path, modifier_path, transmute_path, component_path, "
             "relic_bonus_path, augment_path, ascendant_path, ascendant_2h_path)")
assert blanks == 0, f'{blanks} row(s) store an empty string where NULL is meant'

# -- 3. the two columns we refuse to carry ---------------------------------
columns = {r['name'] for r in conn.execute('PRAGMA table_info(iagd_item)')}
for forbidden in ('rarity', 'name', 'iagd_rarity', 'iagd_name'):
    assert forbidden not in columns, \
        f'iagd_item grew a {forbidden!r} column -- IAGD\'s own vocabulary is ' \
        f'not the catalogue\'s and must not be stored as though it were'
print(f'  {len(columns)} columns, and neither name nor rarity among them')

# The evidence for that rule, measured live rather than remembered. If IAGD
# ever changes vocabulary this stops printing a clean one-tier skew, which is
# the signal to look again.
conn.execute("ATTACH ? AS cat", ('file:' + cfg.catalogue_db + '?mode=ro',))
conn.execute("ATTACH ? AS ia", ('file:' + cfg.iagd + '?mode=ro',))
print('  IAGD rarity vs catalogue classification, as it stands:')
for row in conn.execute("""
        SELECT p.Rarity, b.classification, count(*) n
        FROM ia.PlayerItem p LEFT JOIN cat.item b ON b.path = p.baserecord
        GROUP BY 1, 2 ORDER BY n DESC"""):
    print(f'    IAGD {row[0]!r:10} -> catalogue {row[1]!r:12} {row[2]:5}')

# -- 4. the same vocabulary as the catalogue -------------------------------
# Structural, not coincidental: IAGD reads the same game archives, so every
# record it names must be one the catalogue knows. Scoped to the main campaign,
# since a mod's records are in no archive this project reads.
unknown = one("""SELECT count(*) FROM iagd_item i
                 LEFT JOIN cat.item b ON b.path = i.base_path
                 WHERE b.path IS NULL AND i.mod = ''""")
assert unknown == 0, f'{unknown} base record(s) are in IAGD but not the catalogue'
print(f'  all {counts["items"]} base records resolve in the catalogue')

# -- 5. how the two halves of the collection sit ---------------------------
# Reported, NOT asserted. IAGD moves items in both directions, so an item
# briefly present in both files is possible rather than impossible, and a hard
# assertion here would fail on a legitimate state. What IS asserted is that the
# two can be compared at all -- one path vocabulary, one join.
conn.execute("ATTACH ? AS st", ('file:' + cfg.stash_db + '?mode=ro',))
both = one('SELECT count(*) FROM iagd_item i JOIN st.stash_item s '
           'ON s.base_path = i.base_path AND s.seed = i.seed')
both_base = one('SELECT count(DISTINCT i.base_path) FROM iagd_item i '
                'JOIN st.stash_item s ON s.base_path = i.base_path')
stash_unknown = one("""SELECT count(*) FROM st.stash_item s
                       LEFT JOIN cat.item b ON b.path = s.base_path
                       WHERE b.path IS NULL""")
assert stash_unknown == 0, 'the two stashes do not share a path vocabulary'
total = one('SELECT count(*) FROM iagd_item') + one('SELECT count(*) FROM st.stash_item')
print(f'  in both halves: {both} item(s) by (base, seed), {both_base} by base '
      f'alone; {total} items held in total')

# -- 6. duplicates: an observation, asserted where it is safe to -----------
# (base_path, seed) identifies an item. Unique across every row here, and
# checked rather than enforced -- see the schema for why a UNIQUE index would
# be the wrong place to find that out.
dupes = one('SELECT count(*) FROM (SELECT base_path, seed FROM iagd_item '
            'GROUP BY base_path, seed HAVING count(*) > 1)')
assert dupes == 0, f'{dupes} (base, seed) pair(s) appear twice -- worth a look ' \
                   f'before assuming it is a bug'
print('  (base, seed) unique across the collection')

# -- 8. IAGD's rendered names as an ORACLE for the catalogue's display_name -
# This is the only independent check this project has on how the game composes
# a name. IAGD renders its own, from the same archives, by its own code -- so
# agreement is evidence rather than a tautology, which is exactly what a rule
# derived from one reading of the data cannot supply for itself.
#
# ⚠️ THE ORACLE IS PARTIAL AND THE SPLIT IS THE POINT. This collection holds
# only Epic and Legendary items, so it exercises two of the fifty style
# families. The other forty-eight -- Elite, Obsolete, Infantry, Leather and the
# rest -- are ASSUMED to render the same way and are checked by nothing. Do not
# read a pass here as "display_name is verified".
agree = disagree = 0
unverified = set()
examples = []
for row in conn.execute("""
        SELECT p.Name AS rendered, b.display_name AS ours, b.style_tag,
               i.component_path
        FROM iagd_item i
        JOIN ia.PlayerItem p ON p.Id = i.id
        JOIN cat.item b ON b.path = i.base_path"""):
    # IAGD decorates a name that carries a component -- "Mark of the Forbidden
    # [Wardstone]" -- which is its display choice, not part of the item's name.
    # Those rows say nothing about the composition rule, so they are excluded
    # rather than counted as disagreements.
    if row['component_path']:
        continue
    if row['style_tag'] is None or row['style_tag'] in (
            'tagStyleUniqueTier3', 'tagStyleUniqueTier2'):
        if row['rendered'] == row['ours']:
            agree += 1
        else:
            disagree += 1
            if len(examples) < 3:
                examples.append((row['rendered'], row['ours']))
    else:
        unverified.add(row['style_tag'])

assert disagree == 0, (
    f'{disagree} of {agree + disagree} rendered names disagree with '
    f'display_name, e.g. {examples} -- the composition rule is wrong, or IAGD '
    f'changed how it renders')
assert agree > 500, f'only {agree} names checked; the oracle has gone quiet'
print(f'  display_name matches IAGD on {agree}/{agree} items across the two '
      f'Unique tiers')

# Per "a warning is not a gate": the families this cannot reach are NAMED, and
# the moment the collection grows one the count moves, which is the signal to
# extend the check rather than to widen the exemption.
families = one("SELECT count(DISTINCT style_tag) FROM cat.item "
               "WHERE style_tag IS NOT NULL")
print(f'  {families - 2} of {families} style families are exercised by NOTHING '
      f'here' + (f'; this collection reaches none of them {sorted(unverified)}'
                 if unverified else '; none appears in this collection'))

# -- 7. idempotent, and safe against a mid-write IAGD ----------------------
again = iagd.refresh(cfg)
assert again == counts, f'a second build differs: {counts} -> {again}'
conn.close()

with tempfile.TemporaryDirectory() as workdir:
    box = SimpleNamespace(iagd=os.path.join(workdir, 'userdata.db'),
                          stash_iagd_db=os.path.join(workdir, 'out.sqlite'))
    # A real IAGD database, copied small: schema plus two rows.
    dst = sqlite3.connect(box.iagd)
    dst.execute('CREATE TABLE PlayerItem (%s)' %
                ', '.join(f'"{c}"' for c in iagd.ITEM_COLUMNS))
    dst.execute('CREATE TABLE PlayerItemRecord (PlayerItemId, Record)')
    for row in src.execute('SELECT %s FROM PlayerItem LIMIT 2' %
                           ', '.join(f'"{c}"' for c in iagd.ITEM_COLUMNS)):
        dst.execute('INSERT INTO PlayerItem VALUES (%s)' %
                    ', '.join('?' * len(iagd.ITEM_COLUMNS)), tuple(row))
    dst.commit(); dst.close()
    good = iagd.refresh(box)
    assert good['items'] == 2, good
    before = open(box.stash_iagd_db, 'rb').read()

    # Now IAGD "upgrades" and the column this reader needs is gone.
    dst = sqlite3.connect(box.iagd)
    dst.execute('ALTER TABLE PlayerItem DROP COLUMN AscendantAffixNameRecord')
    dst.commit(); dst.close()
    try:
        iagd.refresh(box)
        raise AssertionError('a PlayerItem missing a required column was accepted')
    except iagd.IagdError as exc:
        print(f'  changed IAGD schema refused: {str(exc)[:66]}...')
    assert open(box.stash_iagd_db, 'rb').read() == before, \
        'a failed refresh modified the database it could not rebuild'
src.close()
print('  rebuilding twice gives the same database; a failure leaves it intact')

print('\nIAGD PASS')
