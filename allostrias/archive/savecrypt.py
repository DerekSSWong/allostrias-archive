"""The self-keying XOR stream every Grim Dawn save file is wrapped in.

Both readers in this package sit on it -- `gst.py` for the account-wide side
files, `gdc.py` for a character -- and it is the same cipher, the same framing
convention and the same three int reads in both. It lives here so there is one
of it: the ecosystem this was ported from carries three copies, and the notes
below are the only thing that stops a copy being "improved" back into a wrong
one.

THE KEY ADVANCES OVER RAW BYTES, not decrypted ones. So the key stream can be
replayed across a region without knowing what it decrypts to, which is what
makes the checksum stored at the end of a block a usable proof that the region
was read correctly. It also means the file can only be read FORWARD, in order,
with the exact field layout: there is no seeking to an interesting offset.

⚠️ THE THREE INT READS ARE NOT INTERCHANGEABLE and the difference IS the
format. `int` decrypts and advances the key; `raw_int` decrypts without
advancing (block lengths, and one field in each .gst header); `plain_int`
neither decrypts nor advances (checksums, which are stored in clear). Reading a
block length as an `int` desynchronises every byte after it into plausible
garbage -- which is exactly what it looks like, so the symptom is a file that
"almost" parses.

A block's trailing checksum is therefore BOTH the integrity check and the only
way to resync after skipping: a skipped block leaves the key stale, and
assigning it that checksum is what puts the stream back in step. Skipping and
verifying are mutually exclusive -- a block you skipped can never be checked.
"""
import struct

# Every value in the stream is XORed against a key seeded from the first word.
SEED_MASK = 0x55555555
TABLE_MULTIPLIER = 39916801

# A string long enough to be a record path and no longer. Purely a sanity
# bound: a length past this can only come from a desynchronised key.
MAX_STRING = 4096


class SaveError(Exception):
    """A save file is not the shape this reader knows, or did not verify."""


class Reader:
    """A decrypting cursor over one save file."""

    def __init__(self, data: bytes):
        if len(data) < 8:
            raise SaveError('too small to be a save file')
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
            raise SaveError(f'read past end of file at byte {self.pos}')

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
        """Decrypt WITHOUT advancing. Block lengths, and one .gst header field."""
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
            raise SaveError(f'implausible string length {n} at byte {self.pos}')
        return ''.join(chr(self.byte()) for _ in range(n))

    def wstr(self) -> str:
        """A UTF-16 string. The character's name is the only one in either
        format, and it is why this is not just `str` with a doubled loop:
        reading it as bytes yields a name with a NUL after every letter."""
        n = self.int()
        if n > MAX_STRING:
            raise SaveError(f'implausible name length {n} at byte {self.pos}')
        return ''.join(chr(self.byte() | (self.byte() << 8)) for _ in range(n))

    def skip_block(self, content_start: int, length: int):
        """Jump past a block without decoding it, resyncing from its own stored
        checksum. The checksum cannot be VERIFIED here -- the key was never
        advanced over the skipped bytes, so there is nothing to compare it
        against. Skipping buys position at the cost of proof."""
        self.pos = content_start + length
        self.key = self.plain_int()
