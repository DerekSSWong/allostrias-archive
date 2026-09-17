-- stash_iagd.sqlite -- derived entirely from Item Assistant's userdata.db.
--
-- Disposable, and rebuilt on every launch for the same reason stash.sqlite is:
-- IAGD is a running program whose store changes whenever the player stashes
-- something, and reading the part we want costs ~6 ms.
--
-- This is the SECOND half of one collection, not a second copy of the first.
-- IAGD takes items OUT of the shared stash, so what is here is not in
-- stash.sqlite and what is there is not here -- measured at zero overlap on
-- (base record, seed) and zero even on base record alone. A question about
-- "everything I own" is the union of the two, never either alone.
--
-- Joined to the catalogue the same way stash.sqlite is: by `records/....dbr`
-- path, never by an integer key, because a catalogue rebuild reassigns those.

CREATE TABLE IF NOT EXISTS build_meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

-- Provenance, not a gate. Nothing here decides whether to rebuild.
CREATE TABLE IF NOT EXISTS source_file (
    relpath  TEXT PRIMARY KEY,   -- userdata.db
    size     INTEGER NOT NULL,
    mtime_ns INTEGER NOT NULL,
    wal_size INTEGER             -- NULL when no -wal was present
);

-- One row per item in IAGD's collection.
--
-- The columns line up with stash_item wherever both files say the same thing,
-- so the two stashes answer the same question the same way and a UNION needs
-- no translation. What is extra is extra in the SOURCE, not invented here:
-- IAGD records the Fangs-era ascendant affixes and the reroll counters, which
-- the shared stash file also carries but this project has never seen set.
--
-- ⚠️ IAGD's own `Name` and `Rarity` columns are NOT here. `Rarity` is a colour
-- name sitting one tier below the catalogue's word for the same item -- its
-- `Blue` is the catalogue's `Epic`, its `Epic` is the catalogue's `Legendary`,
-- for all 1,014 rows. Resolve both through the catalogue on `base_path`.
--
-- ⚠️ WHAT IS NOT HERE: rolled stats. IAGD computes them (`ComputedItemStat`)
-- and this deliberately does not import them -- they are a third-party
-- computation with no way to check it from here, and 101 of its rows point at
-- items IAGD no longer holds. The seed is stored; replaying it is the honest
-- route, and it is not written yet.
CREATE TABLE IF NOT EXISTS iagd_item (
    id                INTEGER PRIMARY KEY,   -- IAGD's own PlayerItem.Id
    base_path         TEXT    NOT NULL,
    prefix_path       TEXT,
    suffix_path       TEXT,
    modifier_path     TEXT,
    transmute_path    TEXT,
    seed              INTEGER NOT NULL,
    component_path    TEXT,
    relic_bonus_path  TEXT,
    relic_seed        INTEGER,
    augment_path      TEXT,
    augment_seed      INTEGER,
    component_combines INTEGER,
    stack             INTEGER NOT NULL,
    ascendant_path    TEXT,                  -- Fangs of Asterkarn
    ascendant_2h_path TEXT,
    rerolls_used      INTEGER,
    affix_rerolls_used INTEGER,
    mod               TEXT    NOT NULL,      -- '' for the main campaign
    is_hardcore       INTEGER NOT NULL,
    created_at        INTEGER                -- epoch ms, when IAGD stored it
);

CREATE INDEX IF NOT EXISTS iagd_item_base_idx     ON iagd_item(base_path);
-- (base_path, seed) identifies an item and is unique across all 1,014 held
-- here -- but NOT enforced, deliberately. That is an observation over one
-- collection, and two drops sharing a 32-bit seed is improbable rather than
-- impossible. A UNIQUE index would turn that coincidence into a crash on a
-- build that runs on EVERY launch, taking `status` down with it. The gate
-- asserts the uniqueness instead, where a violation is a finding to look at.
CREATE INDEX IF NOT EXISTS iagd_item_identity_idx ON iagd_item(base_path, seed);

-- IAGD's own index of which records an item references -- its base, plus a
-- second entry for the handful that have one. Carried because it is the only
-- place IAGD says what it thinks an item is made of, and it costs 1,112 rows.
--
-- Rows for items IAGD no longer holds are DROPPED on the way in, not stored
-- and explained: 9 of the source's 1,121 refer to nothing.
CREATE TABLE IF NOT EXISTS iagd_item_record (
    item_id INTEGER NOT NULL REFERENCES iagd_item(id),
    path    TEXT    NOT NULL,
    PRIMARY KEY (item_id, path)
);
