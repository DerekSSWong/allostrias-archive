"""database.arz -> the record shape the sheet reads: {key: [str, ...]}.

The character sheet was written against `.extracted/`, a tree of plain-text
`key=value` files produced by gd-lib's extract_all.py and living in the GAME
directory. That made the sheet depend on another project having been run first,
which is not something a standalone tool can require. This module reads the
same records straight out of the .arz archives the archive already parses, and
reproduces `.extracted`'s shape exactly so the sheet's own rules -- which were
written against that shape -- keep their meaning.

⚠️ `.extracted` IS NOT A RAW DUMP, and a raw one is not a drop-in replacement.
A record that shows 46 keys there has 670 in the archive: the extractor drops
every field still at its default, which is what the authored .dbr files did in
the first place. Handing the sheet the raw record would sweep ~600 zero-valued
stats into a contribution list per item, and would print floats as
`-0.03999999910593033` where the game's own tooltip says `-0.04`. Both rules
are reproduced below.

The one difference kept deliberately: `.extracted` also merges
SurvivalMode1-3.arz, whose records are the Crucible's rebalanced creatures and
controllers, and merges them LAST so they WIN. A campaign character sheet
should not read Crucible values. This reads the four campaign archives that
`settings.arz_paths` names, and `tests/test_records.py` asserts no record any
character actually reads is one SurvivalMode redefines -- so if that ever stops
being true, it fails rather than quietly changing a number.
"""
from .arz import ArzError, Database

# A value the authored .dbr would not have bothered to write. Note 0, 0.0 and
# False are one another's equals in Python, so this set is smaller than it
# looks -- and True survives it, because True == 1 and 1 is not a member.
# 'CharacterAttackSpeedAverage' is the game's own default for the one string
# field that carries a default at all.
DEFAULT_VALUES = {0.0, 0, False, '', 'CharacterAttackSpeedAverage'}


def _fmt(v) -> str:
    """One value as `.extracted` writes it.

    `%g` is what turns the archive's float32 -0.03999999910593033 back into the
    -0.04 the record was authored with. It is not cosmetic: the sheet parses
    these strings back to numbers and prints some of them verbatim.
    """
    if isinstance(v, bool):
        return '1' if v else '0'
    if isinstance(v, float):
        return f'{v:g}'
    return str(v)


def _split(values: list[str]) -> list[str]:
    """The semicolon split, which is a property of the TEXT and not of the data.

    `.extracted` joins a field's values with "; " and the sheet splits them back
    apart on ";". That round trip does one thing the archive does not: a SINGLE
    string value that already contains semicolons -- `targetingMode` is stored
    as the one string "Default;Point;Object;Target" -- comes back as four. The
    sheet's rules were written against the four. Splitting here is what makes
    "read the archive" and "read .extracted" the same sentence rather than
    nearly the same one.
    """
    out = [part.strip() for v in values for part in v.split(';')]
    return [p for p in out if p != '']


class Records:
    """Records by path, in `.extracted` shape, from the campaign archives.

        with Records(cfg.arz_paths) as records:
            d = records.get('records/items/...dbr')

    `get` returns None for a path no archive defines, rather than raising the
    way Database.read does: a missing record is a broken reference the sheet
    reports per slot ("base record missing"), not a crash. A caller that wants
    the raising behaviour should use Database directly.
    """

    def __init__(self, paths: list[str]):
        self.db = Database(paths)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def close(self):
        self.db.close()

    def __contains__(self, path: str) -> bool:
        return path.strip() in self.db

    def paths(self, prefix: str = '') -> list[str]:
        return self.db.paths(prefix)

    def text(self, path: str) -> str | None:
        """The record as `.extracted` WROTE it: `key=v1; v2` lines, or None.

        The stat-line renderers are regex-over-text -- they were written
        against those files -- so a caller that wants prose out of a record
        needs the text, not the dict.

        ⚠️ NOT `'; '.join(self.get(path)[k])`. `get` applies the semicolon split
        that the text round trip performs, so rebuilding a line from it would
        turn the single stored string "Default;Point;Object;Target" into
        "Default; Point; Object; Target" -- four values where the file has one.
        This renders from the raw attributes, which is the only way to get the
        bytes back.
        """
        try:
            attrs = self.db.read(path.strip())
        except ArzError:
            return None
        lines = []
        for key, values in attrs.items():
            if key == 'templateName':
                lines.append(f'templateName={values[0]}')
                continue
            kept = [v for v in values if v not in DEFAULT_VALUES]
            if kept:
                lines.append(f'{key}=' + '; '.join(_fmt(v) for v in kept))
        return '\n'.join(lines) + '\n' if lines else None

    def get(self, path: str) -> dict[str, list[str]] | None:
        if not path:
            return None
        try:
            attrs = self.db.read(path.strip())
        except ArzError:
            return None
        out: dict[str, list[str]] = {}
        for key, values in attrs.items():
            if key == 'templateName':
                # Passed through unfiltered and unformatted, first value only:
                # it is a path, and the default-filter would be meaningless.
                out[key] = _split([str(values[0])])
                continue
            kept = [v for v in values if v not in DEFAULT_VALUES]
            if not kept:
                continue
            # `or ['']` mirrors the text reader: a key written with nothing
            # left after the split is present-but-empty, not absent.
            out[key] = _split([_fmt(v) for v in kept]) or ['']
        return out or None
