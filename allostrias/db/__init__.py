"""Opening a database in cache/.

Both databases here are caches of something on disk -- the catalogue of the
game archives, the stash of the save files -- so the way they are opened is the
same and lives here rather than being written twice. What they are built FROM,
and when they are allowed to go stale, is not shared and stays in each module.
"""
import os
import sqlite3


def connect(path: str, create: bool = True, hint: str = '') -> sqlite3.Connection:
    """Open a cache database, creating it unless told not to.

    `create=False` is for readers: a missing file is then an error with a hint
    at the command that would make one, rather than an empty database that
    answers every question with nothing.
    """
    if not create and not os.path.isfile(path):
        raise FileNotFoundError(f'no database at {path}'
                                + (f'; {hint}' if hint else ''))
    os.makedirs(os.path.dirname(path), exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    # WAL keeps reads working while a build writes, and survives a crash
    # mid-build without leaving a half-written database that opens cleanly.
    conn.execute('PRAGMA journal_mode=WAL')
    conn.execute('PRAGMA foreign_keys=ON')
    # A CAP, NOT A RESERVATION: SQLite grows the page cache toward this limit
    # only as pages are actually touched, so opening the 76 KB stash costs
    # nothing and the 184 MB catalogue uses what it needs. Negative means KiB.
    #
    # Measured, on the build's largest write -- 4.74M item_drop rows into a
    # WITHOUT ROWID table with a secondary index:
    #
    #     default cache                          14.40 s
    #     creating the index after the insert     13.57 s
    #     cache 256 MB + temp_store MEMORY         5.54 s
    #
    # The win is not the insert itself but the index pages: at the default
    # 2 MB cache they are evicted and re-read from disk continuously, and a
    # bulk insert touches them in a scattered order by construction.
    #
    # ⚠️ synchronous=OFF IS DELIBERATELY NOT HERE. It was measured too and
    # saved a further 0.08 s -- for which the price is a database that can be
    # left corrupt rather than merely stale if the machine dies mid-build.
    # That is the one failure this project cannot recover from by rebuilding,
    # since the same crash could take the save files with it.
    conn.execute('PRAGMA cache_size=-262144')     # 256 MiB
    conn.execute('PRAGMA temp_store=MEMORY')
    return conn


def apply_schema(conn: sqlite3.Connection, schema_path: str):
    with open(schema_path, encoding='utf-8') as handle:
        conn.executescript(handle.read())
    conn.commit()
