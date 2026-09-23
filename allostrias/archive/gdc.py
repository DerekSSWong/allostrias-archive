"""`player.gdc`: one character, read for everything that decides its stats.

The character sheet is NOT in the file. Offensive/Defensive Ability, armour,
every resistance, damage and attack speed are computed at runtime from what is
here, so this reads the INPUTS and nothing pretends to be a total:

    block 1  character info   difficulty -- which is a resistance penalty
    block 2  attributes       the BASE allocation, and the base pools
    block 3  inventory        the equipped items, with their seeds
    block 8  skills           mastery bars, skills and devotion together

Eleven further blocks (stash, respawns, teleports, markers, unlock tokens, lore
notes, play stats, one-time events, shrines, and two unidentified) are skipped.
None of them holds a stat: shrines say which devotion points were EARNED, and
block 2 already says how many are bound.

WHAT VERIFIES THIS. Every block declares its byte length and ends with a
checksum equal to the cipher's running key, so a block that lands exactly on
its length AND matches its checksum was almost certainly read correctly (a
false pass is ~2^-32). That pair is also what makes the item-layout search
below safe -- see `find_layout`. Carried bags are skipped rather than decoded:
nothing in a bag affects the character, and a bagged item has a different tail
from an equipped one, so reading them would mean solving a second layout to
reach the first.

Ported from gd-lens's parser.js, which measured these layouts against real
saves; the notes saying WHICH facts were measured rather than guessed come with
them, because they are what stops a rule being improved back into a wrong one.
"""
import os

from .savecrypt import Reader, SaveError

MAGIC = 0x58434447                      # "GDCX"

# The twelve armour/jewellery slots, in the order the block stores them. There
# is no slot field in the file -- position IS the slot.
SLOTS = ('head', 'amulet', 'chest', 'legs', 'feet', 'hands', 'ring1', 'ring2',
         'waist', 'shoulders', 'medal', 'relic')

# Two weapon sets of two, after the armour. Which one is live is a byte read
# just before them; the other is equipped in the file and worn by nobody.
WEAPON_SLOTS = ('mainhand', 'offhand')

# The blocks this reader decodes. A character whose save is missing one of
# these has not been read, and is not reported as one with no skills.
REQUIRED_BLOCKS = (1, 2, 3, 8)

# Difficulty tiers, which are also the resistance penalty tiers.
DIFFICULTIES = ('Normal', 'Elite', 'Ultimate')

# The five record paths on an item, and the three attachments behind them.
ITEM_PATHS = ('base', 'prefix', 'suffix', 'modifier', 'transmute',
              'component', 'relic_bonus', 'augment')


def difficulty_tier(raw: int) -> int:
    """0/1/2 from block 1's difficulty byte, which carries more than the tier.

    ⚠️ THE BYTE IS NOT THE TIER. Three of the six characters this was built
    against read 16 while being on Normal, and the obvious `DIFFICULTY[raw]`
    answers nothing for them -- or worse, a `.get(raw, 0)` answers "Normal"
    without saying it guessed. The low nibble is the tier; what the 0x10 bit
    means is still unknown and is masked off rather than explained.

    Raises on anything that does not mask to a known tier: a wrong tier moves
    nine resistances by 25 points, silently.
    """
    tier = raw & 0x0F
    if tier >= len(DIFFICULTIES):
        raise SaveError(f'unknown difficulty byte {raw} (tier {tier}); the '
                        f'resistance penalty cannot be guessed')
    return tier


def read_header(reader: Reader) -> dict:
    if reader.int() != MAGIC:
        raise SaveError('not a Grim Dawn character file (bad magic)')
    header = {
        'header_version': reader.int(), 'name': reader.wstr(),
        'male': reader.byte() == 1, 'class_tag': reader.str(),
        'level': reader.int(), 'hardcore': reader.byte() == 1,
        'expansion': reader.byte(),
    }
    # The header's checksum is REPORTED, not enforced. It covers only the
    # fields above, and every block after it is verified in its own right; a
    # reader that refused here would reject a file whose data all verifies.
    header['header_checksum_ok'] = (reader.plain_int() == reader.key)
    header['data_version'] = reader.int()
    header['uid'] = ''.join(f'{reader.byte():02x}' for _ in range(16))
    return header


def _read_item(reader: Reader, layout: dict) -> dict:
    """One equipped item: five record paths, the seed, and three attachments.

    THE SEED IS NOT BOOKKEEPING. Every rollable stat on the base and on both
    affixes is jittered from it, so it is the difference between the record's
    unrolled midpoint and what the character is actually wearing.

    `modifier` (a crafting affix) and `relic_bonus` (a relic's completion
    bonus) are REAL STAT SOURCES. Discarding them as bookkeeping is a mistake
    gd-lens made and paid for on a character whose relic carried both.
    """
    item = {
        'base': reader.str(), 'prefix': reader.str(), 'suffix': reader.str(),
        'modifier': reader.str(), 'transmute': reader.str(),
        'seed': reader.int(), 'component': reader.str(),
        'relic_bonus': reader.str(),
    }
    reader.int()                                  # relic completion seed
    item['augment'] = reader.str()
    reader.int(), reader.int()                    # unknown, augment seed
    if layout['ascended']:
        reader.str()
    for _ in range(layout['tail_ints']):
        reader.int()
    if layout['tail_byte']:
        reader.byte()
    # ⚠️ AN EMPTY SLOT STILL CARRIES AFFIX STRINGS, and they are the PREVIOUS
    # filled slot's: the game writes the struct without clearing it, so an
    # empty relic repeats the medal's prefix, suffix and augment. Two of the
    # six characters this was built against have exactly that -- one of them
    # would gain a rune's augment it does not own.
    #
    # Blanked HERE rather than left to the caller, which is a deliberate
    # departure from parser.js. The residue really is in the file, and the
    # sentence above is where that fact is kept; but it is a stale write, not
    # information, and every caller wants it gone. Leaving it in is how it
    # reaches a stat total.
    if not item['base']:
        return {key: '' for key in ITEM_PATHS} | {'seed': 0, 'empty': True}
    item['empty'] = False
    return item


def _read_inventory(reader: Reader, start: int, length: int, layout: dict) -> dict:
    # `verified_from` is where this block's CHECKED region begins. The carried
    # bags sit between the block header and the equipment, and skipping one
    # resyncs the key from the bag's own stored checksum without ever comparing
    # it -- so those bytes never enter the key and corruption in them is
    # invisible here, and to the game. Everything from the equipment onward is
    # covered by block 3's own checksum. Reported rather than glossed: a gate
    # that swept the whole block would be claiming a proof the format does not
    # give (see tests/test_characters.py).
    out = {'equipment': [], 'weapon_sets': [], 'active_weapon_set': 0,
           'bag_count': 0, 'verified_from': start}
    reader.int()                                  # block version
    if reader.byte() == 1:
        bag_count = reader.int()
        reader.int(), reader.int()                # focused bag, selected bag
        if not 0 <= bag_count <= 64:
            raise SaveError(f'implausible bag count {bag_count}')
        out['bag_count'] = bag_count
        # Skipped, not decoded. Each bag resyncs the key from its own stored
        # checksum, and block 3's checksum still covers the equipment below.
        for _ in range(bag_count):
            reader.int()                          # nested block id
            nested_length = reader.raw_int()
            nested_start = reader.pos
            if nested_start + nested_length > reader.len:
                raise SaveError('bag overruns the file')
            reader.skip_block(nested_start, nested_length)
        out['verified_from'] = reader.pos
        out['active_weapon_set'] = reader.byte()
        for slot in SLOTS:
            out['equipment'].append(dict(_read_item(reader, layout), slot=slot))
        for _ in range(2):
            reader.byte()                         # per-set flag
            out['weapon_sets'].append(
                [dict(_read_item(reader, layout), slot=slot)
                 for slot in WEAPON_SLOTS])
    _end_block(reader, start, length, 'inventory block')
    return out


def _read_info(reader: Reader, start: int, length: int) -> dict:
    out = {'version': reader.int()}
    out['in_main_quest'] = reader.byte()
    out['has_been_in_game'] = reader.byte()
    # ⚠️ The second byte is what is UNLOCKED, not what has been cleared --
    # completing a difficulty unlocks the next, and a merit unlocks one
    # outright. It cannot be read as an achievement, and nothing here does.
    out['last_difficulty'] = reader.byte()
    out['greatest_difficulty_unlocked'] = reader.byte()
    out['money'] = reader.int()
    out['greatest_survival_wave'] = reader.byte()
    reader.int(), reader.int()
    out['texture'] = reader.str()
    for _ in range(reader.int()):
        reader.byte()                             # loot filter, one byte each
    _end_block(reader, start, length, 'character-info block')
    return out


def _read_bio(reader: Reader, start: int, length: int) -> dict:
    """Block 2. ATTRIBUTES HERE ARE THE BASE ALLOCATION, not the sheet.

    The in-game sheet shows the total after equipment, devotion and passives,
    so the two disagree by design -- 506/114/50 stored against 1036/370/387
    displayed on the character that settled it. Health and energy are likewise
    the base pools: 250 plus the growth bought with spent attribute points.
    """
    out = {
        'version': reader.int(), 'level': reader.int(),
        'experience': reader.int(), 'attribute_points': reader.int(),
        'skill_points': reader.int(), 'devotion_points': reader.int(),
        'total_devotion': reader.int(), 'physique': reader.float(),
        'cunning': reader.float(), 'spirit': reader.float(),
        'health': reader.float(), 'energy': reader.float(),
    }
    _end_block(reader, start, length, 'attributes block')
    return out


def _read_skills(reader: Reader, start: int, length: int) -> dict:
    """Block 8: every skill the character knows -- mastery bars, class skills
    and devotion, in one list.

    Per entry: a record path, then a FIXED 20-BYTE RUN, then two usually-empty
    strings. The checksum proves how many bytes that run consumes but cannot
    tell an int from four bytes; the split below was chosen by decoding every
    entry under each int/byte composition of 20 and keeping the only one whose
    byte fields are all 0/1.

    `devotion_group` is non-zero on exactly the devotion records and nothing
    else -- a clean partition with no exceptions across six characters. Its
    MAGNITUDE is not the number of points bound: count those with `level`.
    """
    end = start + length
    out = {'version': reader.int(), 'skills': []}
    count = reader.int()
    if not 0 <= count <= 8192:
        raise SaveError(f'implausible skill count {count}')
    for _ in range(count):
        skill = {'name': reader.str(), 'level': reader.int()}
        reader.byte(), reader.byte()
        skill['devotion_group'] = reader.int()
        skill['devotion_experience'] = reader.int()
        reader.int(), reader.byte(), reader.byte()
        skill['auto_cast_skill'] = reader.str()
        reader.str()                              # auto-cast controller
        out['skills'].append(skill)
    out['masteries_allowed'] = reader.int()
    # A TAIL THIS READER CONSUMES WITHOUT INTERPRETING, and deliberately.
    #
    # ⚠️ IT IS NOT ALL INTS. It carries length-prefixed record paths, so
    # reading it as a loop of int()s overshoots on any save that has one and
    # takes every skill, mastery bar and devotion node down with it. And its
    # shape VARIES: an entry sourced from an item carries eight bytes one
    # sourced from a skill does not, so a fixed entry width fails too.
    #
    # Consuming it byte by byte keeps the stream in step and lets the block's
    # own checksum say whether that was right. Nothing downstream reads these
    # records -- they are a hotbar or auto-cast binding. `tail_bytes` is
    # reported so a gate can tell a save that EXERCISES this tail from one that
    # happens to have none, which is exactly why a wrong reading survived.
    out['tail_bytes'] = end - reader.pos
    while reader.pos < end:
        reader.byte()
    _end_block(reader, start, length, 'skills block')
    return out


def _end_block(reader: Reader, start: int, length: int, what: str):
    """Both halves of the proof: the position says no field was skipped, the
    checksum says none was misread."""
    if reader.pos != start + length:
        raise SaveError(f'{what} did not consume its block: at {reader.pos}, '
                        f'expected {start + length}')
    checksum = reader.plain_int()
    if checksum != reader.key:
        raise SaveError(f'{what} checksum {checksum:#010x} does not match the '
                        f'key {reader.key:#010x} -- the read desynchronised')


def _walk(data: bytes, want: dict) -> dict:
    """Walk every block, decoding the ones in `want` and skipping the rest.

    A decoder that fails leaves the key desynchronised, so the key is captured
    before each block and restored on failure -- rewinding the position alone
    would leave every later block decoding into plausible garbage with no
    error at all.
    """
    reader = Reader(data)
    # `blocks` carries each block's offset and length as well as its id: a gate
    # that wants to prove corruption inside a DECODED block is always caught
    # needs to know where those blocks are, and eleven of the fifteen here are
    # skipped and therefore uncheckable by construction.
    out = {'header': read_header(reader), 'blocks': [], 'decoded': {}}
    while reader.pos < reader.len:
        block_id = reader.int()
        length = reader.raw_int()
        start = reader.pos
        if length < 0 or start + length > reader.len:
            raise SaveError(f'block {block_id} overruns the file')
        out['blocks'].append({'id': block_id, 'offset': start,
                              'length': length})
        decoder = want.get(block_id)
        if decoder is not None:
            key_at_start = reader.key
            try:
                out['decoded'][block_id] = decoder(reader, start, length)
                continue
            except SaveError:
                reader.pos, reader.key = start, key_at_start
                raise
        reader.pos = start
        reader.skip_block(start, length)
    return out


# ascended=False FIRST, and the order matters: an empty `ascended` affix string
# is byte-indistinguishable from the int it displaces, so on a save with no
# ascended items two candidates genuinely tie. Real ambiguity, recorded rather
# than hidden -- the narrower layout is preferred because it is the one every
# save read so far actually uses.
_CANDIDATES = tuple(
    {'ascended': ascended, 'tail_ints': tail_ints, 'tail_byte': tail_byte}
    for ascended in (False, True)
    for tail_ints in range(13)
    for tail_byte in (True, False)
)


def find_layout(data: bytes) -> dict:
    """The item tail this file uses, DISCOVERED rather than assumed.

    Item records gained fields across game versions, so the tail differs by
    save. Candidates are tried against block 3 and the first whose inventory
    lands on its exact declared length AND matches its checksum wins -- which
    is why searching is safe here and would not be in a format without that
    pair to check against.
    """
    for layout in _CANDIDATES:
        try:
            _walk(data, {3: lambda r, s, ln: _read_inventory(r, s, ln, layout)})
            return layout
        except SaveError:
            continue
    raise SaveError('the inventory block did not verify under any known item '
                    'layout; the save looks damaged, or comes from a game '
                    'version this reader does not know')


def read_save(path: str) -> dict:
    """Everything block 1, 2, 3 and 8 say about one character.

    Raises rather than returning a partial character. A save whose skills block
    does not verify is not a character with no skills, and the difference has
    to survive all the way to the caller.
    """
    with open(path, 'rb') as handle:
        data = handle.read()
    layout = find_layout(data)
    out = _walk(data, {
        1: _read_info,
        2: _read_bio,
        3: lambda r, s, ln: _read_inventory(r, s, ln, layout),
        8: _read_skills,
    })
    present = {block['id'] for block in out['blocks']}
    missing = [b for b in REQUIRED_BLOCKS if b not in present]
    if missing:
        raise SaveError(f'save has no block {missing} -- nothing here can say '
                        f'what this character is')
    decoded = out['decoded']
    return {'layout': layout, 'header': out['header'], 'blocks': out['blocks'],
            'info': decoded[1], 'bio': decoded[2], 'inventory': decoded[3],
            'skills': decoded[8]}


def character_dirs(saves_dir: str) -> list[tuple[str, str]]:
    """[(directory name, player.gdc path)] for every character in a save root.

    The leading underscore the game puts on every character directory is left
    ON: it is what the directory is called, and stripping it would invent a
    name the filesystem does not have.
    """
    main = os.path.join(saves_dir, 'main')
    if not os.path.isdir(main):
        raise SaveError(f'no main/ directory in {saves_dir}')
    found = []
    for name in sorted(os.listdir(main)):
        save = os.path.join(main, name, 'player.gdc')
        if os.path.isfile(save):
            found.append((name, save))
    return found
