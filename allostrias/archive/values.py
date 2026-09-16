"""What a record's values MEAN, and the rows they become.

Two facts about Grim Dawn's records drive this module:

1. EVERY record carries EVERY field of its template, defaults included. An
   item averages 430 fields of which 37 say anything -- the other 393 are the
   template's zeroes. Storing them all is 11.2 million rows across items
   alone, to answer no question the 962 thousand non-default rows cannot.

   So a field whose values are all default is DROPPED. This mirrors how the
   game's own authored .dbr sources only list overrides, and how gd-lib's
   extraction has always written them.

   The cost, stated plainly: in the catalogue, "absent" and "zero" become the
   same fact. For this data they already are -- an unset .dbr field is stored
   as 0, not as null -- so a reader must treat a missing row as zero and never
   as unknown. Nothing downstream may distinguish them, because the archive
   does not either.

2. 0.9% of kept fields are ARRAYS, up to 200 long, and they are exactly the
   fields that join records together: affixCheckList, records, lootTable.
   Collapsing them would flatten the eligibility and drop graphs, so position
   is preserved and every value gets its own row.
"""
from typing import Iterator, NamedTuple

# A field is dropped when every one of its values is in here. Copied from the
# game's own idea of "unset": numeric zero, false, the empty string -- plus
# one string default that the attack-speed template spells out rather than
# leaving blank.
#
# 0, 0.0 and False are one element in this set, since Python hashes them
# equal. That is the intended behaviour, not an oversight: all three mean
# unset, and a bool field that survives is necessarily True.
DEFAULT_VALUES = frozenset({0.0, 0, False, '', 'CharacterAttackSpeedAverage'})

# The record's type. Always kept, even though its value is never default,
# because every extractor keys off it and a special case here is cheaper than
# every caller remembering it might be missing.
TYPE_FIELD = 'templateName'


class StatRow(NamedTuple):
    """One value of one field, typed for storage.

    `num` and `txt` are exclusive: numbers stay numeric so a query can compare
    them without CAST, strings stay text so they can be joined on. Booleans
    arrive as 1 -- a False would have been dropped as default.
    """
    field: str
    idx: int
    num: float | None
    txt: str | None


def is_default(value) -> bool:
    return value in DEFAULT_VALUES


def non_default(attrs: dict[str, list]) -> dict[str, list]:
    """Drop every field whose values are all default; keep templateName.

    A field with SOME default values keeps them all, positions included --
    a damage array of [0, 12, 0] is three facts, not one.
    """
    kept = {}
    for field, values in attrs.items():
        if field == TYPE_FIELD:
            kept[field] = values
        elif any(v not in DEFAULT_VALUES for v in values):
            kept[field] = values
    return kept


def stat_rows(attrs: dict[str, list]) -> Iterator[StatRow]:
    """Non-default fields as typed, positioned rows."""
    for field, values in non_default(attrs).items():
        for idx, value in enumerate(values):
            if isinstance(value, str):
                yield StatRow(field, idx, None, value)
            elif isinstance(value, bool):
                yield StatRow(field, idx, float(value), None)
            else:
                yield StatRow(field, idx, float(value), None)


def first(attrs: dict[str, list], field: str, default=None):
    """The first value of a field, or `default` if it is absent or empty.

    For the many fields that are single-valued in practice. It does NOT hide a
    missing field behind a plausible number -- the caller passes the default
    it wants and is responsible for it being right.
    """
    values = attrs.get(field)
    return values[0] if values else default


def first_str(attrs: dict[str, list], field: str) -> str | None:
    value = first(attrs, field)
    return value if isinstance(value, str) and value else None
