"""Opening, stamping and invalidating catalogue.sqlite.

The rebuild gate lives here. It answers one question -- are the archives this
catalogue was built from still the archives on disk? -- by comparing size and
mtime of each source file against `source_archive`. That is enough to catch a
game update and cheap enough to run on every launch, which is the point: the
expensive scan should happen when the game changes and never otherwise.

Hashing the archives would be stricter and costs ~180 MB of reads per launch
to defend against an edit that preserves both size and mtime. Not worth it;
`rebuild --force` covers the case where someone believes it happened.
"""
import hashlib
import os
import sqlite3

SCHEMA_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'schema.sql')
# Everything whose contents decide what the catalogue CONTAINS. Hashed into
# the stamp so a logic change invalidates the build exactly as a game update
# does.
#
# Without this the gate compares archive size/mtime and schema version only,
# and a fix to the extraction logic leaves a stale catalogue while reporting
# "up to date; nothing to do". That happened: rolls.py was corrected, rebuild
# skipped, and the wrong numbers stayed in the database until --force. Silent
# staleness is the failure this project keeps paying for.
PACKAGE_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCHEMA_VERSION = '12'  # recipes and item sets


def code_digest() -> str:
    """A hash over every .py and .sql file that shapes the catalogue.

    Walked and sorted rather than listed, so a new extractor is covered the
    moment it exists -- a hardcoded file list would omit exactly the module
    someone just added.
    """
    digest = hashlib.sha256()
    for root, dirs, files in os.walk(PACKAGE_ROOT):
        dirs[:] = sorted(d for d in dirs if d != '__pycache__')
        for name in sorted(files):
            if not name.endswith(('.py', '.sql')):
                continue
            path = os.path.join(root, name)
            digest.update(os.path.relpath(path, PACKAGE_ROOT).encode())
            with open(path, 'rb') as handle:
                digest.update(handle.read())
    return digest.hexdigest()


def connect(path: str, create: bool = True) -> sqlite3.Connection:
    if not create and not os.path.isfile(path):
        raise FileNotFoundError(
            f'no catalogue at {path}; run `main.py rebuild` first')
    os.makedirs(os.path.dirname(path), exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    # WAL keeps reads working while a build writes, and survives a crash
    # mid-rebuild without leaving a half-written catalogue that opens cleanly.
    conn.execute('PRAGMA journal_mode=WAL')
    conn.execute('PRAGMA foreign_keys=ON')
    return conn


def apply_schema(conn: sqlite3.Connection):
    with open(SCHEMA_PATH, encoding='utf-8') as fh:
        conn.executescript(fh.read())
    conn.commit()


def stamp(conn: sqlite3.Connection, game_root: str, archive_paths: list[str]):
    """Record what this catalogue was built from. Call once, at the end of a
    build -- a stamp written before the data would mark a failed build fresh."""
    conn.execute('DELETE FROM source_archive')
    conn.executemany(
        'INSERT INTO source_archive (ordinal, relpath, size, mtime_ns) '
        'VALUES (?, ?, ?, ?)',
        [(i, os.path.relpath(p, game_root), os.path.getsize(p),
          os.stat(p).st_mtime_ns)
         for i, p in enumerate(archive_paths)])
    conn.executemany(
        'INSERT OR REPLACE INTO build_meta (key, value) VALUES (?, ?)',
        [('schema_version', SCHEMA_VERSION), ('code_digest', code_digest())])
    conn.commit()


def staleness(conn: sqlite3.Connection, game_root: str,
              archive_paths: list[str]) -> str | None:
    """Why this catalogue needs rebuilding, or None if it does not.

    Returns a human-readable reason rather than a bool so the CLI can say what
    changed instead of announcing an unexplained several-minute scan.
    """
    row = conn.execute(
        "SELECT value FROM build_meta WHERE key='schema_version'").fetchone()
    if row is None:
        return 'never built'
    if row['value'] != SCHEMA_VERSION:
        return f'schema {row["value"]} -> {SCHEMA_VERSION}'

    stored_code = conn.execute(
        "SELECT value FROM build_meta WHERE key='code_digest'").fetchone()
    if stored_code is None:
        return 'built before extractor code was tracked'
    if stored_code['value'] != code_digest():
        return 'extractor code changed'

    stored = {r['relpath']: (r['ordinal'], r['size'], r['mtime_ns'])
              for r in conn.execute('SELECT * FROM source_archive')}
    current = {os.path.relpath(p, game_root): (i, os.path.getsize(p),
                                               os.stat(p).st_mtime_ns)
               for i, p in enumerate(archive_paths)}

    for relpath in sorted(set(stored) - set(current)):
        return f'{relpath} is gone'
    for relpath in sorted(set(current) - set(stored)):
        return f'{relpath} is new'
    for relpath, (ordinal, size, mtime) in current.items():
        was_ordinal, was_size, was_mtime = stored[relpath]
        if was_ordinal != ordinal:
            return f'{relpath} moved in load order ({was_ordinal} -> {ordinal})'
        if was_size != size:
            return f'{relpath} changed size ({was_size} -> {size})'
        if was_mtime != mtime:
            return f'{relpath} was modified'
    return None
