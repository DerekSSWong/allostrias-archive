"""Gate: the .gst reader, and the stash database it fills.

THE POINT OF THIS GATE IS THAT THE FORMAT VERIFIES ITSELF, and that the reader
actually leans on that rather than decorating it. Every block in a .gst file
declares its own byte length and ends with a checksum that must equal the
cipher's running key, so a layout that is one field wrong cannot produce
plausible items -- it lands off the end, or lands on it with the wrong key.
The sweep below is the proof: flip any single bit in the file and the read must
refuse.

There is exactly ONE hole in that, and it is a property of the format rather
than of this reader. Each file's header carries a field read with `raw_int` --
decrypted with the key but not advancing it -- so its four bytes never enter
the checksum. The game cannot detect corruption there either. The sweep pins
the hole to those four bytes: if a change ever widened it, this fails.

What this gate CANNOT prove is stated rather than glossed: no item in this save
carries an augment, so the augment string and the two ints behind it are held
on the word of the layout alone. The checksum makes that safe to ship -- a
wrong guess yields a refusal, not a wrong answer -- but it is not the same as
having seen one.
"""
import os
import shutil
import sqlite3
import sys
import tempfile
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from allostrias import settings as S               # noqa: E402
from allostrias.archive import gst                 # noqa: E402
from allostrias.db import stash                    # noqa: E402

cfg = S.load()

# -- 1. every stash file present parses and verifies ------------------------
# Derived from the directory, not from a list of the four extensions that
# happen to exist: a save written by a future expansion era must be read here
# rather than quietly skipped.
files = gst.save_files(cfg.saves)
assert files, f'no .gst-family files found in {cfg.saves}'
parsed = {}
for path in files:
    name = os.path.basename(path)
    if name.startswith('reagents'):
        data = gst.read_reagents(path)
        parsed[name] = data
        print(f'  {name:14} {len(data["items"]):4} materials  v{data["version"]}')
    else:
        data = gst.read_transfer(path)
        parsed[name] = data
        items = sum(len(p['items']) for p in data['pages'])
        print(f'  {name:14} {len(data["pages"]):4} pages, {items} items  '
              f'v{data["version"]}, expansion bits {data["expansion"]}')

# -- 2. an empty stash is a RESULT, not a failure --------------------------
# The mode files of an era this save never played are 61 bytes holding one page
# of nothing. A reader that raised on "no items" -- the obvious shape for a
# reader that hunts for record paths instead of walking blocks -- would report
# a format problem where there is none.
transfers = {n: d for n, d in parsed.items() if 'pages' in d}
empty = {n: d for n, d in transfers.items()
         if sum(len(p['items']) for p in d['pages']) == 0}
for name, data in empty.items():
    assert data['pages'], f'{name} parsed as having no pages at all'
print(f'  {len(empty)} empty stash file(s), each still reporting its pages')

# -- 3. single-bit corruption must be refused ------------------------------
# Every byte, not a sample. The two exceptions are computed from the framing --
# seed(4) + version(4) + block id(4) + block length(4) puts content byte 4 at
# file offset 20 -- so this asserts WHERE the hole is, not merely how big.
HEADER = 4 + 4 + 4 + 4
UNVERIFIED = set(range(HEADER + 4, HEADER + 8))
for name, reader in (('transfer.gst', gst.read_transfer),
                     ('reagents.gst', gst.read_reagents)):
    source = os.path.join(cfg.saves, name)
    if not os.path.isfile(source):
        continue
    data = bytearray(open(source, 'rb').read())
    with tempfile.TemporaryDirectory() as workdir:
        target = os.path.join(workdir, name)
        survived = set()
        for offset in range(len(data)):
            data[offset] ^= 0x01
            with open(target, 'wb') as handle:
                handle.write(bytes(data))
            try:
                reader(target)
                survived.add(offset)
            except gst.SaveError:
                pass
            data[offset] ^= 0x01
    assert survived == UNVERIFIED, (
        f'{name}: corruption went undetected at {sorted(survived)}, expected '
        f'only the non-advancing header field at {sorted(UNVERIFIED)}')
    print(f'  {name:14} {len(data)} single-bit corruptions, all refused except '
          f'the 4 bytes the format itself does not cover')

# -- 4. build the database, and check what only a wrong TAIL would break ----
counts = stash.refresh(cfg)
print(f'\n  built: {counts}')
conn = sqlite3.connect(cfg.stash_db)
conn.row_factory = sqlite3.Row

# The row counts must equal what the parser independently reported. A build
# that silently dropped a page would otherwise look like a small stash.
assert counts['items'] == sum(len(p['items']) for d in transfers.values()
                              for p in d['pages'])
assert counts['items'] == conn.execute(
    'SELECT count(*) FROM stash_item').fetchone()[0]
assert counts['materials'] == conn.execute(
    'SELECT count(*) FROM reagent').fetchone()[0]

# THE GRID IS THE TAIL'S OWN TEST. gd-lib's first version of this layout put
# `stack` three ints early; every block still consumed itself to the byte --
# the totals are identical -- and every item came back with stack 0 at grid
# (0, 0). So: the coordinates must be integral, inside their page, and NOT all
# the same, and no cell may be occupied twice.
bad = conn.execute(
    'SELECT count(*) FROM stash_item i JOIN stash_page p ON p.id = i.page_id '
    'WHERE i.x < 0 OR i.y < 0 OR i.x >= p.width OR i.y >= p.height').fetchone()[0]
assert bad == 0, f'{bad} item(s) sit outside their own page'
distinct = conn.execute(
    "SELECT count(DISTINCT x || ',' || y) FROM stash_item").fetchone()[0]
assert distinct > 1, 'every item is at the same grid position -- the tail is ' \
                     'misaligned and the block length cannot see it'
doubled = conn.execute(
    'SELECT count(*) FROM (SELECT page_id, x, y FROM stash_item '
    'GROUP BY page_id, x, y HAVING count(*) > 1)').fetchone()[0]
assert doubled == 0, f'{doubled} grid cell(s) hold two items'
assert conn.execute('SELECT min(stack) FROM stash_item').fetchone()[0] >= 1, \
    'an item with stack 0 -- the signature of `stack` read at the wrong index'
print(f'  grid: {distinct} distinct positions, all inside their page, '
      f'none doubled')

# An absent affix is NULL and never ''. Two spellings of one fact would make
# every query test for both, and one of them would eventually be forgotten.
blanks = conn.execute(
    "SELECT count(*) FROM stash_item WHERE '' IN (prefix_path, suffix_path, "
    "modifier_path, transmute_path, component_path, relic_bonus_path, "
    "augment_path)").fetchone()[0]
assert blanks == 0, f'{blanks} item(s) store an empty string where NULL is meant'

# A material at zero is KEPT. The game holds the row once the material has been
# seen, and dropping it would turn "none left" into "never had one".
zeroes = conn.execute('SELECT count(*) FROM reagent WHERE count = 0').fetchone()[0]
print(f'  {zeroes} material(s) held at zero, and still recorded')
conn.close()

# -- 4b. a fractional grid coordinate is refused ---------------------------
# The file stores x and y as float32 and the database stores cells. int() would
# round a fractional coordinate away and leave a database that reads as normal,
# so the conversion raises -- and this proves it does, rather than trusting
# that no such value will ever arrive.
try:
    stash._cell(2.5, 'x', 'records/items/gearhead/a.dbr')
    raise AssertionError('a fractional grid coordinate was accepted')
except ValueError as exc:
    print(f'  fractional coordinate refused: {exc}')

# -- 5. the rebuild is idempotent ------------------------------------------
again = stash.refresh(cfg)
assert again == counts, f'a second build differs: {counts} -> {again}'
print('  rebuilding twice gives the same database')

# -- 6. a save caught mid-write must not damage the last good build --------
# The stash rebuilds on every launch from files the game may be rewriting at
# that moment. Parsing happens before the database is opened, so a refusal has
# to leave the previous contents exactly as they were -- not empty, and not
# half-filled with whatever parsed before the bad file.
with tempfile.TemporaryDirectory() as workdir:
    saves = os.path.join(workdir, 'save')
    os.makedirs(saves)
    for path in files:
        shutil.copy2(path, saves)
    sandbox = SimpleNamespace(saves=saves,
                              stash_db=os.path.join(workdir, 'stash.sqlite'))
    good = stash.refresh(sandbox)
    before = open(sandbox.stash_db, 'rb').read()

    # Aimed at a byte the sweep above PROVED is covered, so a surviving read
    # would be a real regression rather than a test that missed.
    victim = os.path.join(saves, 'transfer.gst')
    raw = bytearray(open(victim, 'rb').read())
    offset = len(raw) - 8
    assert offset not in UNVERIFIED
    raw[offset] ^= 0x01
    with open(victim, 'wb') as handle:
        handle.write(bytes(raw))

    try:
        stash.refresh(sandbox)
        raise AssertionError('a corrupt transfer.gst was accepted')
    except gst.SaveError as exc:
        print(f'  corrupt save refused: {str(exc)[:60]}...')
    assert open(sandbox.stash_db, 'rb').read() == before, \
        'a failed refresh modified the database it could not rebuild'
    print(f'  previous build intact: {good}')

print('\nSTASH PASS')
