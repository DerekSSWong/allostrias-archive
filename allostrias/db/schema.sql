-- catalogue.sqlite -- derived entirely from the game archives.
--
-- This file holds only what Phase 1 needs: the identity of the build itself.
-- Record tables arrive with the extractor that fills them, because DDL written
-- before there is anything to put in it gets written twice.
--
-- Nothing here is user data. This database is disposable by design: `rebuild`
-- drops and recreates it. Anything the user authored lives in profile.sqlite,
-- which rebuild must never touch.

CREATE TABLE IF NOT EXISTS build_meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

-- One row per archive the build read, so a game update is detectable without
-- re-parsing anything: stat() the files and compare. `ordinal` preserves LOAD
-- ORDER, which is not incidental -- a later archive patches an earlier one,
-- and a catalogue built in the wrong order is stale rather than empty.
CREATE TABLE IF NOT EXISTS source_archive (
    ordinal  INTEGER PRIMARY KEY,
    relpath  TEXT    NOT NULL UNIQUE,
    size     INTEGER NOT NULL,
    mtime_ns INTEGER NOT NULL
);
