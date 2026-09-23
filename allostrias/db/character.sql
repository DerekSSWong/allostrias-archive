-- The characters, in profile.sqlite -- derived entirely from the player.gdc
-- files in the save directory.
--
-- ⚠️ THESE TABLES ARE A MIRROR, inside a database that is otherwise not one.
-- profile.sqlite is the one file in cache/ that is never dropped, because what
-- the user authors lives there; these four tables are the exception and are
-- emptied and refilled on EVERY launch, like the stash. A character deleted in
-- the game leaves here on the next launch. That is the chosen behaviour, not
-- an accident: nothing here is a record of what a character USED to be.
--
-- Consequence for anything added alongside them: a schema change cannot be
-- handled the way stash.sqlite handles it, by deleting the file. It drops and
-- recreates these tables only. See character.py.
--
-- WHAT IS STORED IS WHAT THE FILE SAYS. No rolled value, no total, no
-- character sheet -- the save holds none of those either (Offensive Ability,
-- armour, every resistance and all damage are computed at runtime). Items are
-- their `records/....dbr` paths, which are stable across a catalogue rebuild;
-- ATTACH cache/catalogue.sqlite and join on item.path / skill.path for what
-- they contain. An integer key across the two files would not survive a
-- rebuild and there deliberately is not one.

CREATE TABLE IF NOT EXISTS character_meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

-- One row per character whose save READ AND VERIFIED. A character whose save
-- did not is in character_read_error instead and is NOT here -- so every
-- column below can be NOT NULL, and `SELECT * FROM character` can never hand
-- back a half-read character that looks whole.
CREATE TABLE IF NOT EXISTS character (
    dir_name      TEXT PRIMARY KEY,   -- the save folder, leading underscore and all
    name          TEXT NOT NULL,      -- as the game shows it
    uid           TEXT NOT NULL,      -- the header's 16-byte id, hex
    class_tag     TEXT NOT NULL,      -- tagSkillClassName0309 -- the mastery COMBO
    level         INTEGER NOT NULL,
    hardcore      INTEGER NOT NULL,
    male          INTEGER NOT NULL,
    expansion     INTEGER NOT NULL,

    -- ⚠️ difficulty_raw IS NOT THE TIER. Three of the six characters this was
    -- built against store 16 while playing Normal; the low nibble is the tier
    -- and what the 0x10 bit means is unknown. difficulty_tier is that nibble,
    -- 0/1/2 = Normal/Elite/Ultimate, and the reader refuses a byte that masks
    -- to anything else rather than defaulting to Normal. The tier IS the
    -- resistance penalty, so a guess here would move nine resistances by 25.
    difficulty_raw       INTEGER NOT NULL,
    difficulty_tier      INTEGER NOT NULL,
    -- What is UNLOCKED, not what has been cleared: finishing a difficulty
    -- unlocks the next, and a merit unlocks one outright. Never read this as
    -- an achievement.
    difficulty_unlocked  INTEGER NOT NULL,

    money         INTEGER NOT NULL,
    experience    INTEGER NOT NULL,

    -- UNSPENT points, all three. What was spent is in the attributes below and
    -- in character_skill.
    attribute_points INTEGER NOT NULL,
    skill_points     INTEGER NOT NULL,
    devotion_points  INTEGER NOT NULL,
    -- Devotion points BOUND, which equals the number of devotion rows in
    -- character_skill with level > 0. Two blocks of the save, decoded under
    -- two different layouts, agreeing -- see tests/test_characters.py.
    devotion_total   INTEGER NOT NULL,

    -- ⚠️ THE BASE ALLOCATION, NOT THE SHEET. The game displays these after
    -- equipment, devotion and passive skills, so the two disagree by design:
    -- 506/114/50 here against 1036/370/387 displayed. Each lands exactly on
    -- 50 + 8n, and health/energy on 250 + the growth those points bought.
    physique     REAL NOT NULL,
    cunning      REAL NOT NULL,
    spirit       REAL NOT NULL,
    health_base  REAL NOT NULL,
    energy_base  REAL NOT NULL,

    active_weapon_set INTEGER NOT NULL,   -- 0 or 1; the other set is worn by nobody
    masteries_allowed INTEGER NOT NULL,

    -- Provenance. `layout_*` is the item tail that verified for this file --
    -- it is discovered per save, not assumed, because item records gained
    -- fields across game versions. `skills_tail_bytes` says whether this save
    -- EXERCISES block 8's variable tail: a save with none cannot prove the
    -- tail is read correctly, and that is exactly how a wrong reading of it
    -- once survived every gate.
    header_checksum_ok INTEGER NOT NULL,
    layout_tail_ints   INTEGER NOT NULL,
    layout_tail_byte   INTEGER NOT NULL,
    layout_ascended    INTEGER NOT NULL,
    skills_tail_bytes  INTEGER NOT NULL,
    source_size        INTEGER NOT NULL,
    source_mtime_ns    INTEGER NOT NULL
);

-- A character whose save would not read. SEPARATE FROM `character` ON PURPOSE:
-- a failed read must not be able to masquerade as a character with no skills
-- and no gear, which is what a row with NULLs in it would look like to every
-- query that forgot to check. Absence from both tables means the save file was
-- not there at all.
--
-- Expected in normal use: the game rewrites a save while it is being played,
-- and the launch that catches it mid-write lands here for that one character.
-- The other characters still build.
CREATE TABLE IF NOT EXISTS character_read_error (
    dir_name        TEXT PRIMARY KEY,
    error           TEXT NOT NULL,
    source_size     INTEGER NOT NULL,
    source_mtime_ns INTEGER NOT NULL
);

-- Mastery bars, class skills and devotion nodes, exactly as block 8 stores
-- them: one list, one row each.
--
-- A ROW AT level 0 IS NOT AN ABSENCE. The save lists skills the character can
-- see but has not bought, and dropping them would lose the difference between
-- a skill passed over and a skill out of reach. Filter on level > 0 for what
-- was actually invested in.
--
-- `devotion_group` is non-zero on exactly the devotion records and nothing
-- else -- a clean partition, no exceptions across six characters, and the gate
-- checks both directions. Its MAGNITUDE is not a point count.
--
-- The mastery BARS are the `_classtraining_` records: their level is the bar,
-- which governs the attribute and health grants. A "+1 to all Soldier skills"
-- from gear does not move it.
CREATE TABLE IF NOT EXISTS character_skill (
    dir_name           TEXT NOT NULL REFERENCES character(dir_name) ON DELETE CASCADE,
    skill_path         TEXT NOT NULL,      -- records/skills/....dbr
    level              INTEGER NOT NULL,
    devotion_group     INTEGER NOT NULL,
    devotion_experience INTEGER NOT NULL,
    auto_cast_skill    TEXT,               -- '' in the file; NULL here
    PRIMARY KEY (dir_name, skill_path)
) WITHOUT ROWID;

CREATE INDEX IF NOT EXISTS character_skill_path_idx ON character_skill(skill_path);

-- The sixteen equipment slots: twelve armour and jewellery, plus two weapon
-- sets of two. Every slot gets a row, empty or not, so "which slots are bare"
-- is a query rather than a list of slot names written out again.
--
-- ⚠️ AN EMPTY SLOT IN THE FILE CARRIES THE PREVIOUS SLOT'S AFFIX STRINGS --
-- the game writes the struct without clearing it. That residue is dropped by
-- the reader (see gdc.py) and an empty slot here is empty in every column. It
-- is real in the file and worth +30% and +10 Spirit to a lightly-geared
-- character that believes it.
--
-- WEAPON SETS ARE BOTH STORED. `weapon_set` is NULL for armour, 0 or 1 for a
-- weapon. Only the set matching character.active_weapon_set is worn -- see the
-- character_worn view, which is the thing to query.
--
-- The seed is the ITEM's, and it is what makes the stored stats in the
-- catalogue a midpoint rather than an answer: every rollable stat on the base
-- and both affixes is jittered from it. No rolled value is stored here; that
-- replay belongs with archive/rolls.py and a stored number would go stale the
-- day it is corrected.
CREATE TABLE IF NOT EXISTS character_item (
    id               INTEGER PRIMARY KEY,
    dir_name         TEXT NOT NULL REFERENCES character(dir_name) ON DELETE CASCADE,
    slot             TEXT NOT NULL,     -- head ... relic, mainhand, offhand
    weapon_set       INTEGER,           -- NULL for armour, else 0 or 1
    base_path        TEXT,              -- NULL when the slot is empty
    prefix_path      TEXT,
    suffix_path      TEXT,
    modifier_path    TEXT,              -- a CRAFTING affix, and a real stat source
    transmute_path   TEXT,              -- illusion; appearance only
    seed             INTEGER,
    component_path   TEXT,
    relic_bonus_path TEXT,              -- a relic's completion bonus, also real
    augment_path     TEXT,
    UNIQUE (dir_name, slot, weapon_set)
);

CREATE INDEX IF NOT EXISTS character_item_base_idx ON character_item(base_path);

-- What the character is actually WEARING: filled slots, and only the active
-- weapon set. The rule lives here because getting it wrong is silent -- the
-- off-hand of the stowed set adds its stats to nothing in the game and to
-- everything in a naive query.
CREATE VIEW IF NOT EXISTS character_worn AS
SELECT i.*
FROM character_item i
JOIN character c ON c.dir_name = i.dir_name
WHERE i.base_path IS NOT NULL
  AND (i.weapon_set IS NULL OR i.weapon_set = c.active_weapon_set);
