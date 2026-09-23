"""Gate: the player.gdc reader, and the character tables it fills.

THE FORMAT VERIFIES ITSELF, and the four semantic checks are what the format
CANNOT do. A block that lands on its exact declared length with a matching
checksum was almost certainly read correctly -- but a checksum cannot say which
int inside it is the difficulty, or that `devotionGroup` means devotion. Every
check below that is not the corruption sweep exists because a verified layout
does not verify a NAME:

  * bound devotion, counted in block 8, equals block 2's totalDevotion --
    two blocks, two layouts, agreeing;
  * `devotion_group` is non-zero on exactly the devotion records, both
    directions, no exceptions;
  * the attributes land on 50 + 8n and the base pools reproduce from
    playerlevels.dbr's own increments -- READ FROM THE ARCHIVE here, never
    written into this file, because a gate that hardcodes the numbers it
    checks agrees with whatever the extractor did.

Corruption is swept over the DECODED blocks only. Eleven of the fifteen blocks
in a save are skipped, and skipping resyncs the key from the block's own stored
checksum without ever comparing it -- so corruption there is undetectable by
construction, in this reader and in the game. Claiming otherwise would be a
gate that passes on a promise nothing keeps.
"""
import os
import shutil
import sqlite3
import sys
import tempfile
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from allostrias import settings as S                    # noqa: E402
from allostrias.archive import arz, gdc                 # noqa: E402
from allostrias.archive.savecrypt import SaveError      # noqa: E402
from allostrias.db import character                     # noqa: E402

cfg = S.load()

# -- 1. every character save parses and verifies ---------------------------
characters = gdc.character_dirs(cfg.saves)
assert characters, f'no character saves found in {cfg.saves}/main'
saves = {}
for dir_name, path in characters:
    save = gdc.read_save(path)
    saves[dir_name] = save
    worn = [i for i in save['inventory']['equipment'] if not i['empty']]
    print(f"  {dir_name:12} level {save['header']['level']:<4} "
          f"{len(save['skills']['skills']):3} skills, {len(worn):2} armour "
          f"slots filled, block-8 tail {save['skills']['tail_bytes']:3} bytes")

# The block-8 tail is variable-width and carries record paths, not ints. A
# reader that assumed ints survived every frozen fixture in the project this
# was ported from, because all of them happened to have an empty tail. Say out
# loud whether this set exercises it.
exercised = [d for d, s in saves.items() if s['skills']['tail_bytes'] > 16]
assert exercised, ('no save here has a non-trivial block-8 tail, so nothing '
                   'proves it is consumed correctly -- see gdc._read_skills')
print(f"  block-8 tail exercised by {', '.join(exercised)}")

# -- 2. corruption inside a decoded block is always caught -----------------
# Sampled rather than exhaustive: a full sweep of six 25 KB saves is ~150,000
# reads. The step is prime so it cannot fall into step with a field width.
victim_name, victim_path = characters[0]
data = bytearray(open(victim_path, 'rb').read())
decoded = [b for b in saves[victim_name]['blocks']
           if b['id'] in gdc.REQUIRED_BLOCKS]
assert len(decoded) == len(gdc.REQUIRED_BLOCKS)

# ⚠️ BLOCK 3 IS ONLY PARTLY COVERED, and the sweep must not claim otherwise.
# The carried bags sit inside it and are SKIPPED, which resyncs the key from
# each bag's own stored checksum without comparing it -- the bytes never enter
# the key, so neither this reader nor the game can see a change there. The
# reader states where its verified region begins; sweeping from the block start
# instead reports "corruption undetected" for bag bytes, which is true and is a
# property of the format, not a bug in the reader.
covered = {}
for block in decoded:
    first = block['offset']
    if block['id'] == 3:
        first = saves[victim_name]['inventory']['verified_from']
    covered[block['id']] = (first, block['offset'] + block['length'])
skipped_bag_bytes = covered[3][0] - decoded[[b['id'] for b in decoded].index(3)]['offset']
print(f'\n  block 3: {skipped_bag_bytes} bytes of skipped bags are outside '
      f'the checked region, by construction')
with tempfile.TemporaryDirectory() as workdir:
    target = os.path.join(workdir, 'player.gdc')
    survived, tried = [], 0
    for block_id, (first, last) in covered.items():
        for offset in range(first, last, 37):
            data[offset] ^= 0x01
            with open(target, 'wb') as handle:
                handle.write(bytes(data))
            tried += 1
            try:
                gdc.read_save(target)
                survived.append((block_id, offset))
            except SaveError:
                pass
            data[offset] ^= 0x01
assert not survived, (f'corruption went undetected in decoded blocks at '
                      f'{survived[:5]} -- a wrong read can reach the database')
print(f'\n  {tried} single-bit corruptions across blocks '
      f'{[b["id"] for b in decoded]}, all refused')

# -- 2b. an unknown difficulty byte raises rather than defaulting ----------
# The low nibble is the tier and three of these characters store 16. A
# `.get(raw, 0)` here would answer "Normal" for an unknown byte without saying
# so, and be wrong by 25 points on nine resistances.
for raw in (0, 1, 2, 16, 17, 18):
    gdc.difficulty_tier(raw)
try:
    gdc.difficulty_tier(3)
    raise AssertionError('an unknown difficulty tier was accepted')
except SaveError as exc:
    print(f'  unknown difficulty refused: {str(exc)[:58]}...')

# -- 3. build the tables ---------------------------------------------------
counts = character.refresh(cfg)
print(f'\n  built: {counts}')
assert counts['unreadable'] == 0, 'a live save did not read'
assert counts['characters'] == len(characters)

conn = sqlite3.connect(cfg.profile_db)
conn.row_factory = sqlite3.Row
one = lambda sql, *a: conn.execute(sql, a).fetchone()[0]
assert one('SELECT count(*) FROM character') == len(characters)
assert one('SELECT count(*) FROM character_skill') == counts['skills']

# -- 4. what a checksum cannot say: bound devotion, counted twice ----------
# Block 8 lists the devotion records and block 2 states a total. They are
# decoded under two different layouts, so agreement is evidence about the
# meaning of both, not just about the arithmetic.
for row in conn.execute('SELECT dir_name, devotion_total FROM character'):
    bound = one('SELECT count(*) FROM character_skill WHERE dir_name = ? '
                'AND devotion_group != 0 AND level > 0', row['dir_name'])
    assert bound == row['devotion_total'], (
        f"{row['dir_name']}: {bound} devotion skills bound but block 2 says "
        f"{row['devotion_total']}")
print(f"  devotion: block 8's bound count equals block 2's total on all "
      f"{len(characters)} characters")

# -- 4b. devotion_group partitions the devotion records exactly ------------
# BOTH DIRECTIONS. A check in one direction passes for a field that is simply
# non-zero everywhere.
stray = one("SELECT count(*) FROM character_skill WHERE devotion_group != 0 "
            "AND skill_path NOT LIKE 'records/skills/devotion/%'")
missed = one("SELECT count(*) FROM character_skill WHERE devotion_group = 0 "
             "AND skill_path LIKE 'records/skills/devotion/%'")
assert stray == 0 and missed == 0, (
    f'devotion_group is not a clean partition: {stray} non-devotion records '
    f'carry it, {missed} devotion records do not')
print('  devotion_group is non-zero on exactly the devotion records, '
      'both directions')

# -- 5. the attributes are the BASE allocation, and arithmetic proves it ---
# Derived from the game's own record, not from numbers typed here: a gate that
# hardcodes 8/20/8/12/16 cannot notice the day the game changes them, and
# would agree with a reader that had drifted.
with arz.Database(cfg.arz_paths) as db:
    levels = db.read('records/creatures/pc/playerlevels.dbr')
    # The STARTING pools, read off the player creature record rather than
    # typed here. The arithmetic below would happily solve for any constant
    # that made it balance, so taking this from the same place the game does
    # is what stops the check agreeing with itself.
    pc = db.read('records/creatures/pc/malepc01.dbr')
grow = {k: levels[k][0] for k in
        ('strengthIncrement', 'dexterityIncrement', 'intelligenceIncrement',
         'lifeIncrement', 'lifeIncrementDexterity', 'lifeIncrementIntelligence',
         'manaIncrement', 'maxDevotionPoints')}
start_health, start_energy = pc['characterLife'][0], pc['characterMana'][0]
for row in conn.execute('SELECT * FROM character'):
    points = {}
    for stat, field in (('physique', 'strengthIncrement'),
                        ('cunning', 'dexterityIncrement'),
                        ('spirit', 'intelligenceIncrement')):
        spent = (row[stat] - 50.0) / grow[field]
        assert spent >= 0 and spent == int(spent), (
            f"{row['dir_name']}: {stat} {row[stat]} is not 50 + "
            f"{grow[field]}n -- the field is not the base allocation")
        points[stat] = int(spent)
    health = (start_health + points['physique'] * grow['lifeIncrement']
              + points['cunning'] * grow['lifeIncrementDexterity']
              + points['spirit'] * grow['lifeIncrementIntelligence'])
    energy = start_energy + points['spirit'] * grow['manaIncrement']
    assert health == row['health_base'], (
        f"{row['dir_name']}: health {row['health_base']} but the attributes "
        f"bought {health}")
    assert energy == row['energy_base'], (
        f"{row['dir_name']}: energy {row['energy_base']} but the attributes "
        f"bought {energy}")
    assert row['devotion_total'] <= grow['maxDevotionPoints']
    assert 0 <= row['difficulty_tier'] < len(gdc.DIFFICULTIES)
print(f'  attributes: every character lands on 50 + '
      f"{grow['strengthIncrement']:g}n, and its base health and energy "
      f'reproduce from playerlevels.dbr on top of the creature record\'s '
      f'{start_health:g}/{start_energy:g}')

# -- 6. an empty slot carries no residue -----------------------------------
# The game writes an unfilled slot's struct without clearing it, so the affix
# strings left in it are the PREVIOUS slot's. Two of the six characters here
# have exactly that, one of them an augment it does not own.
residue = one("""SELECT count(*) FROM character_item WHERE base_path IS NULL
                 AND (prefix_path IS NOT NULL OR suffix_path IS NOT NULL
                      OR modifier_path IS NOT NULL OR augment_path IS NOT NULL
                      OR component_path IS NOT NULL OR seed IS NOT NULL)""")
assert residue == 0, f'{residue} empty slot(s) kept the previous slot\'s residue'
empty = one('SELECT count(*) FROM character_item WHERE base_path IS NULL')
blanks = one("""SELECT count(*) FROM character_item WHERE '' IN
                (coalesce(base_path,'x'), coalesce(prefix_path,'x'),
                 coalesce(suffix_path,'x'), coalesce(augment_path,'x'))""")
assert blanks == 0, 'an empty string stored where NULL is meant'
# Every slot is recorded, filled or not: 12 armour + 2 sets of 2.
for row in conn.execute('SELECT dir_name, count(*) n FROM character_item '
                        'GROUP BY dir_name'):
    assert row['n'] == len(gdc.SLOTS) + 4, f"{row['dir_name']} has {row['n']} slots"
print(f'  {empty} empty slot(s) recorded, none carrying residue; every '
      f'character has {len(gdc.SLOTS) + 4} slots')

# The inactive weapon set is equipped in the file and worn by nobody.
worn = one('SELECT count(*) FROM character_worn')
filled = one('SELECT count(*) FROM character_item WHERE base_path IS NOT NULL')
stowed = one("""SELECT count(*) FROM character_item i JOIN character c
                ON c.dir_name = i.dir_name WHERE i.base_path IS NOT NULL
                AND i.weapon_set IS NOT NULL
                AND i.weapon_set != c.active_weapon_set""")
assert worn == filled - stowed, 'character_worn does not exclude the stowed set'
print(f'  {worn} items worn, {stowed} stowed in an inactive weapon set')
# ⚠️ IF NOTHING IS STOWED, THE RULE ABOVE PASSED WITHOUT BEING TESTED. None of
# these six characters uses a second weapon set, so the view's whole reason to
# exist is unexercised by live data and is proved on a constructed row instead,
# in the sandbox below. Say so here rather than letting the count read as
# evidence.
if stowed == 0:
    print('  (no live character stows a weapon set -- the exclusion is '
          'proved on a constructed row in step 9)')

# -- 7. every record path the characters store resolves in the catalogue ---
# This is what the two catalogue widenings are FOR, and it is checked from the
# character side: the skill tree had 262 of these 433 missing before, and the
# crafting affixes 5 of 5.
conn.execute('ATTACH ? AS cat', (cfg.catalogue_db,))
for column, table, source, extra in (
        ('skill_path', 'skill', 'character_skill', 'AND q.level > 0'),
        ('base_path', 'item', 'character_worn', ''),
        ('prefix_path', 'affix', 'character_worn', ''),
        ('suffix_path', 'affix', 'character_worn', ''),
        ('modifier_path', 'affix', 'character_worn', ''),
        ('component_path', 'item', 'character_worn', ''),
        ('augment_path', 'item', 'character_worn', ''),
        ('relic_bonus_path', 'bonus', 'character_worn', '')):
    total, unresolved = conn.execute(
        f'SELECT count(*), count(*) - count(t.path) '
        f'FROM {source} q LEFT JOIN cat.{table} t ON t.path = q.{column} '
        f'WHERE q.{column} IS NOT NULL {extra}').fetchone()
    assert not unresolved, (f'{unresolved} of {total} {column} values do not '
                            f'resolve in cat.{table}')
    print(f'  {column:18} -> {table:6} {total:4} rows, all resolve')

# The crafting modifiers are the half of that the affix table did not have.
crafting = one("SELECT count(*) FROM cat.affix WHERE kind = 'Crafting'")
assert crafting > 0, 'the Crafting kind is missing from the catalogue'
worn_crafting = one("SELECT count(*) FROM character_worn w JOIN cat.affix a "
                    "ON a.path = w.modifier_path WHERE a.kind = 'Crafting'")
print(f'  {crafting} crafting affixes in the catalogue, {worn_crafting} of '
      f'them worn')
conn.close()

# -- 8. the rebuild is idempotent -----------------------------------------
again = character.refresh(cfg)
assert again == counts, f'a second build differs: {counts} -> {again}'
print('\n  rebuilding twice gives the same tables')

# -- 9. one bad save, and the durable half of profile.sqlite --------------
# The mirror lives inside the one database in cache/ that is never dropped, so
# two things have to hold at once: a character whose save will not parse is
# recorded as unreadable rather than vanishing, the others still build, and
# whatever else the profile holds is untouched by either.
with tempfile.TemporaryDirectory() as workdir:
    sandbox_saves = os.path.join(workdir, 'save')
    shutil.copytree(os.path.join(cfg.saves, 'main'),
                    os.path.join(sandbox_saves, 'main'))
    sandbox = SimpleNamespace(saves=sandbox_saves,
                              profile_db=os.path.join(workdir, 'profile.sqlite'))

    own = sqlite3.connect(sandbox.profile_db)
    own.execute('CREATE TABLE user_note (text TEXT)')
    own.execute("INSERT INTO user_note VALUES ('not derived from anything')")
    own.commit()
    own.close()

    good = character.refresh(sandbox)
    assert good['unreadable'] == 0

    # Aimed inside a DECODED block, so a surviving read would be a regression
    # rather than a test that missed. The last block's tail is skipped and
    # would not be caught -- by construction, not by omission.
    victim_dir = characters[0][0]
    victim = os.path.join(sandbox_saves, 'main', victim_dir, 'player.gdc')
    raw = bytearray(open(victim, 'rb').read())
    raw[decoded[1]['offset'] + 4] ^= 0x01
    with open(victim, 'wb') as handle:
        handle.write(bytes(raw))

    after = character.refresh(sandbox)
    assert after['unreadable'] == 1, after
    assert after['characters'] == len(characters) - 1, after

    conn = sqlite3.connect(sandbox.profile_db)
    conn.row_factory = sqlite3.Row
    failed = conn.execute('SELECT * FROM character_read_error').fetchall()
    assert len(failed) == 1 and failed[0]['dir_name'] == victim_dir
    assert conn.execute('SELECT count(*) FROM character WHERE dir_name = ?',
                        (victim_dir,)).fetchone()[0] == 0, \
        'an unreadable character was also stored as a character'
    assert conn.execute('SELECT count(*) FROM character_skill WHERE dir_name = ?',
                        (victim_dir,)).fetchone()[0] == 0
    # THE STOWED SET, on a row built for the purpose. No live character has a
    # second weapon set filled, so without this the view's exclusion is a rule
    # nothing ever runs.
    survivor = conn.execute('SELECT dir_name, active_weapon_set FROM character '
                            'LIMIT 1').fetchone()
    stowed_set = 1 - survivor['active_weapon_set']
    conn.execute('UPDATE character_item SET base_path = ?, seed = 1 '
                 'WHERE dir_name = ? AND slot = ? AND weapon_set = ?',
                 ('records/items/gearweapons/test_stowed.dbr',
                  survivor['dir_name'], 'mainhand', stowed_set))
    conn.execute('UPDATE character_item SET base_path = ?, seed = 2 '
                 'WHERE dir_name = ? AND slot = ? AND weapon_set = ?',
                 ('records/items/gearweapons/test_active.dbr',
                  survivor['dir_name'], 'mainhand', survivor['active_weapon_set']))
    seen = {r['base_path'] for r in conn.execute(
        'SELECT base_path FROM character_worn WHERE dir_name = ? '
        'AND weapon_set IS NOT NULL', (survivor['dir_name'],))}
    assert 'records/items/gearweapons/test_active.dbr' in seen, seen
    assert 'records/items/gearweapons/test_stowed.dbr' not in seen, (
        'character_worn includes a weapon from the INACTIVE set -- its stats '
        'reach nothing in the game and everything in a query')
    conn.rollback()
    print(f'  character_worn: the active set\'s weapon is worn, the stowed '
          f"set's is not (constructed on {survivor['dir_name']})")

    kept = conn.execute('SELECT text FROM user_note').fetchone()['text']
    assert kept == 'not derived from anything', 'the refresh ate the profile'
    conn.close()
    print(f'  a corrupt save lands in character_read_error '
          f'({str(failed[0]["error"])[:44]}...), the other '
          f'{after["characters"]} characters still build, and the profile\'s '
          f'own table is untouched')

print('\nCHARACTERS PASS')
