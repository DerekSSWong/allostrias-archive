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
    return conn


def apply_schema(conn: sqlite3.Connection, schema_path: str):
    with open(schema_path, encoding='utf-8') as handle:
        conn.executescript(handle.read())
    conn.commit()
