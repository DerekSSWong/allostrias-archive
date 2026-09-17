-- stash.sqlite -- derived entirely from the .gst files in the save directory.
--
-- Disposable, like the catalogue and unlike profile.sqlite: every row here can
-- be read back out of the save files in milliseconds, so this database is
-- rebuilt from scratch on every launch rather than kept in step with a
-- staleness check. The save files change every time the game is played; the
-- archives change when the game is patched. Different clocks, different rules.
--
-- Nothing here is joined to catalogue.sqlite by id -- they are separate files
-- and an integer key would not survive a catalogue rebuild. Item records are
-- stored as their `records/....dbr` path, which is stable, and a reader that
-- wants names or stats ATTACHes the catalogue and joins on `item.path`.

CREATE TABLE IF NOT EXISTS build_meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

-- One row per file read. Provenance, not a gate: nothing here decides whether
-- to rebuild, because the rebuild is unconditional. It exists so `status` can
-- say what the numbers came from and when.
--
-- `mode` is the file's own extension and is NOT interpreted. `expansion` is
-- the byte the file states about itself, and it is the thing that actually
-- distinguishes the eras: the four files of this save read 0, 1, 3 and 7 for
-- .bst/.cst/.dst/.gst, which is a bitmask of owned expansions. That is
-- recorded as the observation it is; no name is attached to a bit here.
CREATE TABLE IF NOT EXISTS source_file (
    relpath      TEXT PRIMARY KEY,   -- transfer.gst, reagents.gst, ...
    kind         TEXT NOT NULL,      -- transfer | reagents
    mode         TEXT NOT NULL,      -- gst, bst, cst, dst, ...
    size         INTEGER NOT NULL,
    mtime_ns     INTEGER NOT NULL,
    file_version INTEGER NOT NULL,   -- the outer framing version
    version      INTEGER NOT NULL,   -- the block's own content version
    expansion    INTEGER,            -- transfer only; NULL for reagents
    mod_name     TEXT NOT NULL       -- '' for the main campaign
);

-- ---------------------------------------------------------------------------
-- The shared stash

-- A page is a tab. Recorded even when empty, because an empty tab is a real
-- part of the stash's shape and its absence would read as "there is no tab".
CREATE TABLE IF NOT EXISTS stash_page (
    id     INTEGER PRIMARY KEY,
    mode   TEXT    NOT NULL,
    idx    INTEGER NOT NULL,         -- page order within the file
    width  INTEGER NOT NULL,
    height INTEGER NOT NULL,
    UNIQUE (mode, idx)
);

-- One row per item sitting in the stash.
--
-- This is what the FILE says and nothing more. The five record paths and the
-- seed are every input a roll needs, but the roll itself is not computed here:
-- replaying a seed is a separate problem (see archive/rolls.py, which carries
-- only the band), and a stored number would go stale the day that replay is
-- corrected. Join to the catalogue for what the base and affixes can roll.
--
-- An absent affix is NULL, never ''. The file spells "no prefix" as a
-- zero-length string; storing that verbatim would give the same fact two
-- spellings and make every query test for both.
--
-- ⚠️ WHAT IS NOT HERE, so it is not inferred from silence: the component's and
-- the relic bonus's own contributions, and the augment's. An item listed here
-- with a component has that component's lines for real, and they appear
-- nowhere in this database.
CREATE TABLE IF NOT EXISTS stash_item (
    id              INTEGER PRIMARY KEY,
    page_id         INTEGER NOT NULL REFERENCES stash_page(id),
    x               INTEGER NOT NULL,   -- grid column, stored as float in the file
    y               INTEGER NOT NULL,   -- grid row
    base_path       TEXT    NOT NULL,
    prefix_path     TEXT,
    suffix_path     TEXT,
    modifier_path   TEXT,
    transmute_path  TEXT,               -- the illusion applied to it, if any
    seed            INTEGER NOT NULL,
    component_path  TEXT,
    relic_bonus_path TEXT,
    augment_path    TEXT,
    stack           INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS stash_item_base_idx ON stash_item(base_path);
CREATE INDEX IF NOT EXISTS stash_item_page_idx ON stash_item(page_id);

-- ---------------------------------------------------------------------------
-- Crafting materials

-- The materials tab: components, advanced components, rare materials and the
-- two quest items that stack there. `count` is the stack, which is the field
-- GD Stash's own reader calls getStackCount -- position alone could not settle
-- it, for the same reason the stash item's stack could not.
--
-- A material at zero IS STORED. The game keeps the row once the material has
-- been seen, and dropping it would turn "I have none left" into "I have never
-- had one", which is a different fact.
CREATE TABLE IF NOT EXISTS reagent (
    id        INTEGER PRIMARY KEY,
    mode      TEXT    NOT NULL,
    item_path TEXT    NOT NULL,
    count     INTEGER NOT NULL,
    UNIQUE (mode, item_path)
);

CREATE INDEX IF NOT EXISTS reagent_item_idx ON reagent(item_path);
