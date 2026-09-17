"""The encrypted .gst side files: the shared stash, and the crafting materials.

Five files sit beside `player.gdc` and hold ACCOUNT-WIDE state rather than any
one character's -- transfer (the shared stash), reagents (crafting materials),
transmutes (illusionist unlocks), potions (unlocked potion formulas) and
formulas (blueprints). This module reads the first two. They share a cipher, a
framing and a sub-block convention, so the pieces below are split by what they
are rather than by which file uses them.

`formulas.gst` is the odd one out and is NOT readable here: it is not encrypted
at all, just a tagged plaintext stream. A reader that assumed the family shared
a format would decrypt it into noise.

THE FRAMING IS SELF-VERIFYING, and that is the reason to walk blocks rather
than hunt for `records/...dbr` in the decrypted bytes. Every block and every
sub-block declares its own byte length and ends with a checksum that must equal
the cipher's running key. A layout that is one field wrong lands off the end,
or lands on the end with a key that does not match, and is refused here. The
alternative -- anchoring on record paths and reading forward -- cannot tell a
correct layout from a wrong one that happens to produce plausible strings.

⚠️ THE THREE INT READS ARE NOT INTERCHANGEABLE and the difference IS the
format. `int` decrypts and advances the key; `raw_int` decrypts without
advancing (block lengths, and one field in each file header); `plain_int`
neither decrypts nor advances (checksums). Reading a block length as an `int`
desynchronises every byte after it into plausible garbage -- which is exactly
what it looks like, so the symptom is a file that "almost" parses.

The cipher and the item field order are ported from gd-lib, which measured
them; the notes that say WHICH facts were measured rather than guessed are
carried over with them, because they are what stops the rules being improved
back into wrong ones.
"""
import os
import re
import struct

# Every value in the stream is XORed against a key seeded from the first word.
SEED_MASK = 0x55555555
TABLE_MULTIPLIER = 39916801

# Block ids. One per file -- the id is how the game says which file it opened,
# so a mismatch means we were handed the wrong file, not a corrupt one.
BLOCK_TRANSFER = 18
BLOCK_REAGENTS = 20

# A save file stem plus an extension of the shape <era>s<t|h>: the middle 's'
# is constant, the leading letter tracks which expansion era wrote the file
# (b, c, d, g have all been seen), and the last is t for softcore or h for
# hardcore. Deriving the set from the shape rather than listing the four
# extensions that exist today means a future era is read rather than dropped.
#
# What the leading letter MEANS is not interpreted anywhere here. The files are
# reported under their own extension and the caller may make of it what it
# knows; inventing a mapping to expansion names would be a guess presented as a
# fact.
MODE_RE = re.compile(r'^[a-z]s[th]$')

# A string long enough to be a record path and no longer. Purely a sanity
# bound: a length past this can only come from a desynchronised key.
MAX_STRING = 4096


class GstError(Exception):
    """The file is not the shape this reader knows, or did not verify."""


class Reader:
    """The self-keying XOR stream. Ported from gd-lib's savefile.Reader.

    The key advances by XORing a table entry chosen by the RAW (still
    encrypted) byte, so the key stream can be replayed over a region without
    knowing what it decrypts to -- which is what makes the checksum at the end
    of a block a usable proof that the region was read correctly.
    """

    def __init__(self, data: bytes):
        if len(data) < 8:
            raise GstError('too small to be a save file')
        self.b, self.len, self.pos = data, len(data), 0
        seed = (self._u32(0) ^ SEED_MASK) & 0xFFFFFFFF
        self.key, self.pos = seed, 4
        self.tab, k = [0] * 256, seed
        for i in range(256):
            k = ((k >> 1) | ((k & 1) << 31)) & 0xFFFFFFFF
            k = (k * TABLE_MULTIPLIER) & 0xFFFFFFFF
            self.tab[i] = k

    def _u32(self, offset: int) -> int:
        return struct.unpack_from('<I', self.b, offset)[0]

    def _need(self, n: int):
        if self.pos + n > self.len:
            raise GstError(f'read past end of file at byte {self.pos}')

    def _advance(self, n: int):
        for i in range(n):
            self.key = (self.key ^ self.tab[self.b[self.pos + i]]) & 0xFFFFFFFF
        self.pos += n

    def byte(self) -> int:
        self._need(1)
        val = self.b[self.pos] ^ (self.key & 0xFF)
        self._advance(1)
        return val

    def int(self) -> int:
        """Decrypt and advance. The ordinary read."""
        self._need(4)
        val = (self._u32(self.pos) ^ self.key) & 0xFFFFFFFF
        self._advance(4)
        return val

    def raw_int(self) -> int:
        """Decrypt WITHOUT advancing. Block lengths, and one header field."""
        self._need(4)
        val = (self._u32(self.pos) ^ self.key) & 0xFFFFFFFF
        self.pos += 4
        return val

    def plain_int(self) -> int:
        """Neither decrypt nor advance. Checksums, which are stored in clear."""
        self._need(4)
        val = self._u32(self.pos)
        self.pos += 4
        return val

    def float(self) -> float:
        return struct.unpack('<f', struct.pack('<I', self.int()))[0]

    def str(self) -> str:
        n = self.int()
        if n > MAX_STRING:
            raise GstError(f'implausible string length {n} at byte {self.pos}')
        return ''.join(chr(self.byte()) for _ in range(n))


def open_file(path: str, expect_block: int) -> tuple[Reader, int, int]:
    """(reader, file version, end of block) for a single-block .gst file.

    The framing is checked by ARITHMETIC before anything is read out of it:
    seed(4) + version(4) + id(4) + length(4) + content + checksum(4) must
    account for the file exactly. A file whose framing does not add up is
    refused here rather than decoded into plausible contents further down.
    """
    with open(path, 'rb') as handle:
        data = handle.read()
    reader = Reader(data)
    version = reader.int()
    block_id = reader.int()
    length = reader.raw_int()               # the length itself does not advance
    if block_id != expect_block:
        raise GstError(f'{os.path.basename(path)} is block {block_id}, not '
                       f'{expect_block} -- wrong file for this reader')
    if reader.pos + length + 4 != len(data):
        raise GstError(
            f'{os.path.basename(path)}: framing does not add up: '
            f'{reader.pos} + {length} + 4 != {len(data)}')
    return reader, version, reader.pos + length


def close_file(reader: Reader, end: int, what: str):
    """Require the walk to have landed exactly on the block end, then check the
    block's own checksum. Both halves matter: the position proves no field was
    skipped, the checksum proves none was misread."""
    _end_block(reader, end, what)


def _open_sub_block(reader: Reader) -> tuple[int, int]:
    """(id, end offset) of a nested block. Same shape as the file's own."""
    block_id = reader.int()
    length = reader.raw_int()
    return block_id, reader.pos + length


def _end_block(reader: Reader, end: int, what: str):
    if reader.pos != end:
        raise GstError(f'{what} did not consume its block: at {reader.pos}, '
                       f'expected {end}')
    checksum = reader.plain_int()
    # The game stores the running key here and re-seeds from it. Verifying
    # equality is therefore both the integrity check and the re-sync: if they
    # match there is nothing to assign, and if they do not, nothing after this
    # point could be trusted anyway.
    if checksum != reader.key:
        raise GstError(f'{what} checksum {checksum:#010x} does not match the '
                       f'key {reader.key:#010x} -- the read desynchronised')


def _read_item(reader: Reader) -> dict:
    """One stash item, tail included.

    ⚠️ THE FIELD POSITIONS ARE MEASURED, NOT SEARCHED, and the difference
    matters: the block length and checksum fix the tail's SIZE and say nothing
    about what sits where inside it. gd-lib's first version put `stack` three
    ints too early and every block still verified to the byte -- the totals are
    identical -- while reporting stack 0 and grid (0, 0) for everything.

    Read as fourteen slots after the seed that is: the component pair and its
    seed (0-2), the augment and its two ints (3-5), three unknown ints (6-8),
    the stack at 9, two more unknowns (10-11), and the grid pair as float32 at
    12-13 -- which land on clean 0..9 by 0..4, a stash tab. The stack is pinned
    against a count read off the game's own UI, because an index that holds 1
    for every non-stacking item verifies just as well as the right one.

    The three unknown ints are recorded as unknown rather than named. One
    item in the stash this was read against carries a component, so that
    field's position is exercised rather than assumed; NO item carries an
    augment, so the augment string and the two ints behind it are held on the
    word of the layout alone until a save with one turns up. The block
    checksum is what makes that safe to ship: a wrong guess there cannot
    produce a plausible item, only a refusal.
    """
    item = {
        'base': reader.str(),
        'prefix': reader.str(),
        'suffix': reader.str(),
        'modifier': reader.str(),
        'transmute': reader.str(),
        'seed': reader.int(),
        'component': reader.str(),
        'relic_bonus': reader.str(),
    }
    reader.int()                                  # relic completion seed
    item['augment'] = reader.str()
    reader.int(), reader.int()                    # unknown, augment seed
    reader.int(), reader.int(), reader.int()      # unknown (tail 6-8)
    item['stack'] = reader.int()                  # tail 9
    reader.int(), reader.int()                    # unknown (tail 10-11)
    item['x'], item['y'] = reader.float(), reader.float()
    return item


def read_transfer(path: str) -> dict:
    """The shared stash: every page, and every item on it.

    An EMPTY stash is a normal result, not an error. The .bst/.cst/.dst files
    of a save that has only ever used the current era are 61 bytes holding one
    page of nothing, and a reader that treated "no items" as a failed parse
    would report a format problem where there is none.
    """
    reader, file_version, end = open_file(path, BLOCK_TRANSFER)
    version = reader.int()
    reader.raw_int()                     # unknown; decrypted, does not advance
    mod = reader.str()
    expansion = reader.byte()
    pages = []
    for index in range(reader.int()):
        _block_id, page_end = _open_sub_block(reader)
        width, height = reader.int(), reader.int()
        items = [_read_item(reader) for _ in range(reader.int())]
        # Pages gained trailing fields in a later format revision. They are
        # skipped by the page's own declared length rather than by a count
        # keyed off `version`, so a revision that adds another one is read
        # correctly instead of failing on a number this file does not know.
        trailing = page_end - reader.pos
        if trailing < 0 or trailing % 4:
            raise GstError(f'page {index}: {trailing} bytes of trailing data '
                           f'is not a whole number of fields')
        for _ in range(trailing // 4):
            reader.int()
        _end_block(reader, page_end, f'page {index}')
        pages.append({'index': index, 'width': width, 'height': height,
                      'items': items})
    close_file(reader, end, os.path.basename(path))
    return {'file_version': file_version, 'version': version, 'mod': mod,
            'expansion': expansion, 'pages': pages}


def read_reagents(path: str) -> dict:
    """Crafting materials and components: one record path and a stack count.

    The count is the field GD Stash's own reader calls `getStackCount`, which
    is what settles it -- the position alone could not, for the same reason the
    stash item's could not.
    """
    reader, file_version, end = open_file(path, BLOCK_REAGENTS)
    version = reader.int()
    reader.raw_int()                     # unknown; decrypted, does not advance
    mod = reader.str()
    items = []
    for index in range(reader.int()):
        _block_id, item_end = _open_sub_block(reader)
        items.append({'item': reader.str(), 'count': reader.int()})
        _end_block(reader, item_end, f'material {index}')
    close_file(reader, end, os.path.basename(path))
    return {'file_version': file_version, 'version': version, 'mod': mod,
            'items': items}


def save_files(saves_dir: str) -> list[str]:
    """Every shared-stash and crafting-material file in a save directory.

    Found by stem and extension SHAPE rather than by a list of the four
    extensions that exist today, so a save written by a future expansion era
    is read rather than silently skipped. Backups the game or a tool leaves
    behind (`transfer.gst.bak`) do not match the shape and are not read.
    """
    found = []
    for stem in ('transfer', 'reagents'):
        for name in sorted(os.listdir(saves_dir)):
            root, ext = os.path.splitext(name)
            if root == stem and MODE_RE.match(ext.lstrip('.')):
                found.append(os.path.join(saves_dir, name))
    return found


def mode_of(path: str) -> str:
    """The file's extension, which is its mode. See MODE_RE for the shape."""
    mode = os.path.splitext(path)[1].lstrip('.')
    if not MODE_RE.match(mode):
        raise GstError(f'{os.path.basename(path)} is not a .gst-family file')
    return mode
