"""`formulas.<mode>`: the crafting blueprints the account has unlocked.

ACCOUNT-WIDE, not per character, one file per mode beside the stash files
(gst.MODE_RE: the last letter is t for softcore, h for hardcore). Unlike every
other file in the save directory it is NOT ENCRYPTED -- no cipher, no checksum,
just length-prefixed strings -- which is why gst.py cannot read it:

    str "begin_block" + u32 block id
    str "formulasVersion" + u32 version        (2 and 3 seen)
    str "numEntries" + u32 n
    str "expansionStatus" + u8                  (version 3 only)
    n x [ str "itemName" + str <blueprint path>, str "formulaRead" + u32 ]
    str "end_block" + u32 0xDEADC0DE

⚠️ `formulaRead` IS NOT "UNLOCKED". Every entry in the file is unlocked; the flag
is the unread marker -- the "new" pip in the crafting panel. There is no list of
locked blueprints: absence is the only signal.

The older-era files are what the game wrote before an expansion; on the one
account read (2026-09-29) each is a strict subset of the newest (1, 9, 94 of
404 entries), with expansion bits 0/1/3/7 as the transfer files have.

Ported from gd-lib's formulas.py, which knew version 3 only: the version-2 file
has no expansionStatus, and reading one as version 3 fails on its first entry.
Every field is checked as it is read and the sentinel is required, so a file of
another shape raises rather than returning a short list -- nothing downstream can
tell a short list from a small collection.
"""
import struct

from .savecrypt import SaveError

SENTINEL = 0xDEADC0DE
VERSIONS = (2, 3)


def read(path: str) -> dict:
    """{'version', 'expansion' (None before version 3), 'entries': [(path, unread)]}."""
    with open(path, 'rb') as handle:
        data = handle.read()
    pos = 0

    def u32():
        nonlocal pos
        if pos + 4 > len(data):
            raise SaveError(f'{path}: ran off the end at byte {pos}')
        v = struct.unpack_from('<I', data, pos)[0]
        pos += 4
        return v

    def text():
        nonlocal pos
        n = u32()
        if n > 4096 or pos + n > len(data):
            raise SaveError(f'{path}: implausible string length {n} at byte {pos}')
        v = data[pos:pos + n].decode('utf-8')
        pos += n
        return v

    def expect(want):
        got = text()
        if got != want:
            raise SaveError(f'{path}: expected {want!r} at byte {pos}, found {got!r}')

    expect('begin_block')
    u32()                                         # block id
    expect('formulasVersion')
    version = u32()
    if version not in VERSIONS:
        raise SaveError(f'{path}: formulas version {version}; known: {VERSIONS}')
    expect('numEntries')
    n = u32()
    expansion = None
    if version >= 3:
        expect('expansionStatus')
        if pos >= len(data):
            raise SaveError(f'{path}: ran off the end at byte {pos}')
        expansion = data[pos]
        pos += 1
    entries = []
    for _ in range(n):
        expect('itemName')
        record = text()
        expect('formulaRead')
        entries.append((record, u32()))
    expect('end_block')
    if u32() != SENTINEL:
        raise SaveError(f'{path}: the closing sentinel is missing')
    if pos != len(data):
        raise SaveError(f'{path}: {len(data) - pos} bytes left over after the block')
    return {'version': version, 'expansion': expansion, 'entries': entries}
