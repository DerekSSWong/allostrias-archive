"""database.arz -> a stream of (record_path, attrs).

Format reverse-engineered from GDStash (org.gdstash.file.ARZDecompress /
ARZReader). Ported from gd-lib's arz_parse.py, with two changes that matter
here: the file is mmapped rather than read into memory, and records are yielded
one at a time instead of being unpacked to 83k files on disk. Nothing is
materialised that the caller has not asked for.

An .arz is: header, a record table (name + offset + sizes, one entry per .dbr),
an LZ4-compressed blob per record, and one shared string table that every key
and every string value indexes into. Decompression is per record and lazy, so
filtering by prefix genuinely skips the work rather than doing it and
discarding the result.
"""
import mmap
import os
import struct
from dataclasses import dataclass
from typing import Iterator

HEADER_FMT = '<HHIIIII'
HEADER_SIZE = 24          # records are stored at 24 + offset
SUPPORTED = (2, 3)        # (unknown, version) seen in every shipped .arz

# Attribute type tags, from the record payload.
T_INT, T_FLOAT, T_STRING, T_BOOL = 0, 1, 2, 3


class ArzError(Exception):
    """The .arz is not the shape this parser knows how to read."""


def lz4_block_decompress(data: bytes, uncompressed_size: int) -> bytes:
    """LZ4 block format. No stdlib equivalent and no pip here, so it stays
    hand-rolled.

    The match copy is byte-at-a-time ONLY when the match overlaps the output
    cursor (offset < match_len), which is how LZ4 encodes runs and genuinely
    needs the byte-wise semantics. Non-overlapping matches -- the large
    majority -- are one slice copy. That distinction is the difference between
    a full scan taking minutes and taking seconds.
    """
    out = bytearray()
    i = 0
    n = len(data)
    while i < n:
        token = data[i]
        i += 1
        lit_len = token >> 4
        if lit_len == 15:
            while True:
                b = data[i]
                i += 1
                lit_len += b
                if b != 255:
                    break
        out += data[i:i + lit_len]
        i += lit_len
        if len(out) >= uncompressed_size:
            break
        offset = data[i] | (data[i + 1] << 8)
        i += 2
        match_len = token & 0x0F
        if match_len == 15:
            while True:
                b = data[i]
                i += 1
                match_len += b
                if b != 255:
                    break
        match_len += 4
        start = len(out) - offset
        if offset >= match_len:
            out += out[start:start + match_len]
        else:
            for k in range(match_len):
                out.append(out[start + k])
    return bytes(out[:uncompressed_size])


@dataclass(frozen=True)
class RecordEntry:
    """One row of the record table: where a .dbr lives, not its contents."""
    path: str             # e.g. 'records/items/faction/...dbr'
    offset: int
    len_comp: int
    len_decomp: int


class Arz:
    """Open with a context manager; the mmap is released on exit.

        with Arz(settings.arz_path) as arz:
            for path, attrs in arz.iter_records('records/items/'):
                ...
    """

    def __init__(self, path: str):
        self.path = path
        self._file = open(path, 'rb')
        self._map = mmap.mmap(self._file.fileno(), 0, access=mmap.ACCESS_READ)
        try:
            self._parse_tables()
        except Exception:
            self.close()
            raise

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def close(self):
        if getattr(self, '_map', None) is not None:
            self._map.close()
            self._map = None
        if getattr(self, '_file', None) is not None:
            self._file.close()
            self._file = None

    # -- tables -----------------------------------------------------------

    def _parse_tables(self):
        d = self._map
        unknown, version, rec_start, rec_size, rec_num, str_start, str_size = \
            struct.unpack_from(HEADER_FMT, d, 0)
        if (unknown, version) != SUPPORTED:
            raise ArzError(
                f'{self.path}: unsupported .arz version {unknown}.{version} '
                f'(this parser knows {SUPPORTED[0]}.{SUPPORTED[1]}). '
                'A game update may have changed the format.'
            )
        self.strings = self._read_string_table(str_start)
        self.records = self._read_record_table(rec_start, rec_num)

    def _read_string_table(self, start: int) -> list[str]:
        """Every key and every string value is an index into this table."""
        d = self._map
        pos = start
        (num,) = struct.unpack_from('<I', d, pos)
        pos += 4
        strings = []
        for _ in range(num):
            (slen,) = struct.unpack_from('<I', d, pos)
            pos += 4
            strings.append(d[pos:pos + slen].decode('cp1252', errors='replace'))
            pos += slen
        return strings

    def _read_record_table(self, start: int, count: int) -> list[RecordEntry]:
        d = self._map
        pos = start
        records = []
        for _ in range(count):
            str_id, len_str = struct.unpack_from('<II', d, pos)
            pos += 8 + len_str          # the inline type string is unused here
            offset, len_comp, len_decomp = struct.unpack_from('<III', d, pos)
            pos += 12 + 8               # + two filetime ints
            records.append(RecordEntry(
                path=strings_get(self.strings, str_id, self.path),
                offset=offset, len_comp=len_comp, len_decomp=len_decomp))
        return records

    # -- records ----------------------------------------------------------

    def read_attrs(self, entry: RecordEntry) -> dict[str, list]:
        """Decompress one record into {key: [values]}.

        Values stay as a list even when there is one, because the game uses
        both shapes for the same key across records and collapsing singletons
        would make the caller guess which it got.
        """
        base = HEADER_SIZE + entry.offset
        comp = self._map[base:base + entry.len_comp]
        blob = lz4_block_decompress(comp, entry.len_decomp)
        attrs: dict[str, list] = {}
        off = 0
        n = len(blob)
        while off < n:
            var_type, count = struct.unpack_from('<HH', blob, off)
            (str_idx,) = struct.unpack_from('<I', blob, off + 4)
            off += 8
            key = self.strings[str_idx]
            vals = []
            for _ in range(count):
                if var_type == T_INT:
                    (v,) = struct.unpack_from('<i', blob, off)
                elif var_type == T_FLOAT:
                    (v,) = struct.unpack_from('<f', blob, off)
                elif var_type == T_STRING:
                    (idx,) = struct.unpack_from('<I', blob, off)
                    v = self.strings[idx]
                elif var_type == T_BOOL:
                    (raw,) = struct.unpack_from('<i', blob, off)
                    v = bool(raw)
                else:
                    raise ArzError(
                        f'unknown attribute type {var_type} in {entry.path}')
                vals.append(v)
                off += 4
            attrs.setdefault(key, []).extend(vals)
        return attrs

    def iter_records(self, prefix: str = '') -> Iterator[tuple[str, dict]]:
        """Yield (path, attrs) for records under `prefix`.

        Paths in the .arz use backslashes; `prefix` is matched against a
        forward-slash, lower-cased form so callers write 'records/items/'
        regardless of platform.
        """
        prefix = prefix.lower()
        for entry in self.records:
            path = normalise(entry.path)
            if prefix and not path.startswith(prefix):
                continue
            yield path, self.read_attrs(entry)


def strings_get(strings: list[str], idx: int, arz_path: str) -> str:
    if idx >= len(strings):
        raise ArzError(f'{arz_path}: string index {idx} outside table')
    return strings[idx]


def normalise(path: str) -> str:
    """Record paths as the rest of the program spells them."""
    return path.replace('\\', '/').lower()


def record_count(path: str) -> int:
    """Rows in the record table, without decompressing anything."""
    with Arz(path) as arz:
        return len(arz.records)


class Database:
    """The four .arz archives read as ONE record set, with override semantics.

    Grim Dawn does not ship one database. It ships a base plus one archive per
    expansion, and an expansion restates any record it changes -- 11,097 of
    them, at time of writing. The last archive that mentions a path wins.

    This is the only class extractors should use. Reading a single Arz gives a
    catalogue in which thousands of records are silently the pre-expansion
    version: not absent, which would be noticed, but stale, which is not.

        with Database(settings.arz_paths) as db:
            for path, attrs in db.iter_records('records/items/'):
                ...
    """

    def __init__(self, paths: list[str]):
        if not paths:
            raise ArzError('no .arz archives given')
        self.archives = [Arz(p) for p in paths]
        # path -> (archive, entry). Built in load order so later assignment
        # overwrites earlier: the override rule, expressed as dict semantics.
        self._index: dict[str, tuple[Arz, RecordEntry]] = {}
        self.override_count = 0
        for archive in self.archives:
            for entry in archive.records:
                key = normalise(entry.path)
                if key in self._index:
                    self.override_count += 1
                self._index[key] = (archive, entry)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def close(self):
        for archive in self.archives:
            archive.close()

    def __len__(self) -> int:
        return len(self._index)

    def __contains__(self, path: str) -> bool:
        return normalise(path) in self._index

    def paths(self, prefix: str = '') -> list[str]:
        prefix = prefix.lower()
        return sorted(p for p in self._index if p.startswith(prefix))

    def read(self, path: str) -> dict[str, list]:
        """Attributes of one record by path. Raises if it is not in any
        archive -- a missing record is a broken reference, not an empty one."""
        key = normalise(path)
        found = self._index.get(key)
        if found is None:
            raise ArzError(f'no record {key} in any archive')
        archive, entry = found
        return archive.read_attrs(entry)

    def iter_records(self, prefix: str = '') -> Iterator[tuple[str, dict]]:
        """Yield (path, attrs) for records under `prefix`, winning version only."""
        prefix = prefix.lower()
        for key in sorted(self._index):
            if prefix and not key.startswith(prefix):
                continue
            archive, entry = self._index[key]
            yield key, archive.read_attrs(entry)
