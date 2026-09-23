"""Text_EN.arc -> {tag: english string}.

Every item, skill, faction and affix in the game is stored as a tag; the
display name lives here. Ported from gd-lib's arc_parse.py, which in turn was
read out of GDStash (org.gdstash.file.ARCDecompress).

The archives stack the same way the databases do -- base, then one per
expansion, later wins -- so `load_tags` takes the ordered list from settings
rather than a single path.

An .arc is a part table, a NUL-separated name table, and a TOC entry per file.
The awkward part is that names and TOC entries are not 1:1: directory entries
occupy TOC slots with no content, so the two lists have to be walked together.
That walk is `_map_names_to_tocs`, and it is a port, not a design -- it
reproduces GDStash's determineToCIndexes because the format gives no better
handle on it.
"""
import mmap
import os
import struct
from typing import Iterator

from .arz import lz4_block_decompress

HEADER_FMT = '<iiiiIII'
SUPPORTED_VERSION = 3
TOC_ENTRY_SIZE = 44          # 5 ints + filetime (8) + 4 ints
STORED = 1                   # toc type: not compressed

# Controller-prompt overrides. These files redefine ~193 tags that also exist
# in tags_items.txt, with the gamepad wording ('[Press Y to Infuse]') instead
# of the mouse wording ('[Right-Click to Infuse]'). Same tag, different text,
# so whichever file is read last wins -- which made the catalogue's wording
# depend on archive iteration order. The catalogue is a desktop tool, so the
# console variants are excluded rather than arbitrated.
CONSOLE_MARKER = 'console'


class ArcError(Exception):
    """The .arc is not the shape this parser knows how to read."""


class Arc:
    def __init__(self, path: str):
        self.path = path
        self._file = open(path, 'rb')
        self._map = mmap.mmap(self._file.fileno(), 0, access=mmap.ACCESS_READ)
        try:
            self._parse()
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

    def _parse(self):
        d = self._map
        (_magic, version, num_files, num_parts,
         size_parts, size_strings, offset_parts) = struct.unpack_from(HEADER_FMT, d, 0)
        if version != SUPPORTED_VERSION:
            raise ArcError(
                f'{self.path}: unsupported .arc version {version} '
                f'(this parser knows {SUPPORTED_VERSION}). '
                'A game update may have changed the format.')
        self.num_files = num_files

        pos = offset_parts
        self.parts = []
        for _ in range(num_parts):
            self.parts.append(struct.unpack_from('<iii', d, pos))   # off, comp, decomp
            pos += 12

        pos = offset_parts + size_parts
        self.names = []
        for _ in range(num_files):
            end = d.find(b'\x00', pos)
            self.names.append(d[pos:end].decode('cp1252', errors='replace'))
            pos = end + 1

        pos = offset_parts + size_parts + size_strings
        self.tocs = []
        for _ in range(num_files):
            typ, off, len_comp, len_decomp, _hash = struct.unpack_from('<iiiii', d, pos)
            num_parts_, index = struct.unpack_from('<ii', d, pos + 28)
            self.tocs.append(dict(type=typ, offset=off, len_comp=len_comp,
                                  len_decomp=len_decomp, num_parts=num_parts_,
                                  index=index))
            pos += TOC_ENTRY_SIZE

        self._toc_for_name = self._map_names_to_tocs()

    def _map_names_to_tocs(self) -> list[int]:
        """GDStash's determineToCIndexes, ported as-is.

        Most archives interleave empty TOC entries (directories) with real
        ones, so name i is not TOC i. A few archives do not, and the only
        signal distinguishing them is whether the trailing unused entries look
        like filenames. There is no cleaner rule available from the format.
        """
        names, tocs = self.names, self.tocs
        num_unused = sum(1 for t in tocs if t['num_parts'] == 0)
        one_to_one = False
        for i in range(num_unused):
            name = names[len(names) - i - 1]
            slash, dot = name.rfind('/'), name.rfind('.')
            if dot == -1 or slash > dot:
                continue
            if all(c.isalnum() or c in '_-/\\' for c in name):
                one_to_one = True
                break
        if one_to_one:
            return list(range(self.num_files))

        mapping = [-1] * self.num_files
        toc_i, name_i = -1, -1
        while toc_i < len(tocs) - 1 and name_i < self.num_files - 1:
            toc_i += 1
            toc = tocs[toc_i]
            if toc['len_decomp'] == 0 and toc['num_parts'] == 0:
                continue
            name_i += 1
            mapping[name_i] = toc_i
        return mapping

    def read_file(self, index: int) -> bytes | None:
        toc_index = self._toc_for_name[index]
        if toc_index == -1:
            return None
        toc = self.tocs[toc_index]
        if toc['type'] == STORED and toc['len_comp'] == toc['len_decomp']:
            return self._map[toc['offset']:toc['offset'] + toc['len_decomp']]
        out = bytearray()
        for j in range(toc['num_parts']):
            off, len_comp, len_decomp = self.parts[toc['index'] + j]
            chunk = self._map[off:off + len_comp]
            out += chunk if len_comp == len_decomp else \
                lz4_block_decompress(chunk, len_decomp)
        return bytes(out)

    def iter_text_files(self, skip_console: bool = True) -> Iterator[tuple[str, str]]:
        """Yield (name, decoded contents) for every .txt in the archive.

        Console tag files are skipped by default; see CONSOLE_MARKER.
        """
        for i, name in enumerate(self.names):
            lowered = name.lower()
            if not lowered.endswith('.txt'):
                continue
            if skip_console and CONSOLE_MARKER in os.path.basename(lowered):
                continue
            data = self.read_file(i)
            if data is not None:
                yield name, data.decode('cp1252', errors='replace')


def parse_tag_lines(text: str) -> Iterator[tuple[str, str]]:
    """`tag=text` lines, skipping blanks and comments.

    The leading BOM is stripped explicitly: these files are cp1252-decoded, so
    a UTF-8 BOM arrives as three visible characters glued to the first tag and
    would otherwise create one silently unreachable name per file.
    """
    for line in text.lstrip('﻿ï»¿').splitlines():
        line = line.strip().lstrip('﻿')
        if not line or line.startswith('#') or '=' not in line:
            continue
        tag, _, value = line.partition('=')
        yield tag.strip(), value.strip()


# The tag FAMILIES, which gd-lib's item_stats was written against and which the
# port keeps. A granted skill's `skillDisplayName` resolves through skills, not
# items or ui, and looking in the wrong family returns nothing rather than an
# error -- that miss once cost 54 of 486 items all of their effects.
#
# Measured 2026-09-23: the four families are effectively DISJOINT (one tag in
# both ui and skills, with identical text), so a single merged map would behave
# the same. They are kept separate anyway, because merging would make this
# renderer resolve tags the original could not, and a port that is more
# forgiving than its oracle cannot be held to it.
TAG_FAMILIES = {
    'items': 'items', 'ui': 'ui', 'skills': 'skills', 'creatures': 'creatures',
}


def _family_of(basename: str) -> str | None:
    """`tagsgdx2_items.txt` -> 'items'. None for anything unfamilied."""
    stem = basename.lower()
    if not stem.startswith('tags') or not stem.endswith('.txt'):
        return None
    stem = stem[:-len('.txt')]
    _, _, rest = stem.partition('_')
    return TAG_FAMILIES.get(rest)


def load_tag_families(paths: list[str]) -> dict[str, dict[str, str]]:
    """{family: {tag: text}} over the archives in load order, later winning.

    Console files are excluded by iter_text_files, same as load_tags.
    """
    out: dict[str, dict[str, str]] = {f: {} for f in set(TAG_FAMILIES.values())}
    for path in paths:
        with Arc(path) as archive:
            for name, text in archive.iter_text_files():
                family = _family_of(os.path.basename(name))
                if family is None:
                    continue
                for tag, value in parse_tag_lines(text):
                    out[family][tag] = value
    return out


def load_tags(paths: list[str]) -> dict[str, str]:
    """Merge every text archive into one flat {tag: string}, in load order.

    Flat rather than per-category because a tag is globally unique and every
    caller looks names up by tag alone; keeping the category would mean every
    lookup guessing which file a tag lives in.
    """
    if not paths:
        raise ArcError('no text archives given')
    tags: dict[str, str] = {}
    for path in paths:
        with Arc(path) as arc:
            for _name, text in arc.iter_text_files():
                tags.update(parse_tag_lines(text))
    return tags


def tag_sources(paths: list[str]) -> dict[str, str]:
    """{tag: archive it finally came from}. Used by the gate to show which
    expansion won a tag; not needed at build time."""
    sources: dict[str, str] = {}
    for path in paths:
        with Arc(path) as arc:
            for _name, text in arc.iter_text_files():
                for tag, _value in parse_tag_lines(text):
                    sources[tag] = os.path.basename(os.path.dirname(
                        os.path.dirname(path))) or 'base'
    return sources
