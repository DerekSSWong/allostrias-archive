"""One walk of the record tree, two consumers.

WHY THIS MODULE EXISTS. `drops` and `eligibility` both need every record in
the tree and neither can be narrowed to a prefix: a loot table can be anywhere
(items, endlessdungeon, sandbox) and a holder is anywhere at all -- 89% of
holders are outside records/items/, across seven top-level folders. Reading
the tree costs 16 s, and before this module the build read it twice.

NARROWING WAS TRIED FIRST AND MEASURED, because it is the cheaper fix and
costs no coupling. It works for eligibility (3 prefixes, 8.1 s) and does
NOT work for drops: the seven prefixes it needs still cover 54,713 records and
scan in 15.90 s against 16.06 s for all 82,448. The 27,735 records that could
be skipped are fx, sounds, terraintextures and level art -- tiny records that
decompress almost instantly -- while everything expensive is needed. Record
COUNT is not proportional to scan cost, and an estimate made from counts said
this would save 5 s.

So the saving here is real but it is bought with coupling: two modules that
were independent now run inside a loop neither of them owns. Anything added
here has to be worth that.

WHAT THIS MODULE MUST NOT BECOME. It is not a place to put extraction logic.
Every rule about what a drop or an eligibility pair IS stays in its own
module; this file knows only that both want the same records. A third
consumer joins by exposing the same two methods, and a consumer that wants a
PREFIX rather than the whole tree should keep its own loop -- paying 8 s to
avoid reading 53,000 records it does not want is the better trade, and
extract/vendors.py is the example.
"""
import time

from ...archive import values as V
from . import drops, eligibility


def extract(conn, db, tags: dict[str, str]) -> dict[str, int | str]:
    """Fill both modules' tables from a single pass.

    The consumers are constructed BEFORE the walk because each reads the
    catalogue as it exists now -- `item` and `affix`, filled by earlier
    extractors -- and written after it, because neither can know its own
    answer until every record has been offered.
    """
    consumers = [drops.Collector(conn, db, tags),
                 eligibility.Collector(conn, db, tags)]

    start = time.perf_counter()
    for path, attrs in db.iter_records():
        # Computed ONCE and shared. drops needs it for every record; the
        # standalone eligibility recomputed it for the ~2,600 it kept.
        kept = V.non_default(attrs)
        for consumer in consumers:
            consumer.offer(path, kept)
    scan = time.perf_counter() - start

    # Timed per consumer and reported, not for tuning but because the build
    # report is the only place the cost of each extractor is visible. Merging
    # two entries into one would otherwise turn two numbers into one and hide
    # which half is expensive -- and "eligibility takes 16.9 s" was itself
    # misleading, since 15.7 s of it was this walk and 1.2 s was the work.
    counts: dict[str, int | str] = {'tree scan seconds': f'{scan:.1f}'}
    for consumer in consumers:
        started = time.perf_counter()
        counts.update(consumer.finish())
        counts[f'{type(consumer).__module__.rsplit(".", 1)[-1]} seconds'] = \
            f'{time.perf_counter() - started:.1f}'
    return counts
