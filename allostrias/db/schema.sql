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

-- ---------------------------------------------------------------------------
-- Items
--
-- One row per OBTAINABLE record under records/items/. That folder is mostly
-- not items: of 26,001 records, 12,528 are loot machinery (drop tables,
-- randomizers, chests) and only ~9,000 are things a character can hold. The
-- split is by `Class`, enumerated explicitly in extract/items.py rather than
-- inferred, so a class added by a game update fails the build instead of
-- being silently dropped.
--
-- There is deliberately NO is_mi / is_craftable / is_vendor column here. None
-- of those is a property of the item record -- an MI is defined by which
-- monsters drop it, craftability by a blueprint pointing at it. They arrive
-- as views once drops and recipes exist. Guessing them from record shape is
-- how faction vendor gear gets mislabelled as Monster Infrequent.
CREATE TABLE IF NOT EXISTS item (
    id             INTEGER PRIMARY KEY,
    path           TEXT NOT NULL UNIQUE,   -- records/items/....dbr
    class          TEXT NOT NULL,          -- ArmorProtective_Head, ItemRelic, ...
    family         TEXT NOT NULL,          -- ArmorProtective, ItemRelic, ...
    slot           TEXT,                   -- Head, Axe2h, ... NULL off-equipment
    folder         TEXT NOT NULL,          -- gearhead, faction, materia, ...
    is_equipment   INTEGER NOT NULL,       -- 1 if it occupies a gear slot
    name_tag       TEXT,                   -- itemNameTag, else description
    name           TEXT,                   -- resolved English, NULL if untagged
    classification TEXT,                   -- Rare / Epic / Legendary / ...
    level_req      INTEGER,
    set_path       TEXT,                   -- lootsets/*.dbr, resolved in a later step
    -- Monster Infrequent. Derived in extract/mi.py AFTER drops exist, because
    -- the exclusion it depends on (a blueprint pointing at the record) needs
    -- the loot-table walk. NULL until that step runs.
    is_mi          INTEGER
);

CREATE INDEX IF NOT EXISTS item_name_idx           ON item(name);
CREATE INDEX IF NOT EXISTS item_class_idx          ON item(class);
CREATE INDEX IF NOT EXISTS item_classification_idx ON item(classification, level_req);
CREATE INDEX IF NOT EXISTS item_folder_idx         ON item(folder);

-- Every non-default field of every item, one row per value.
--
-- Long form because item fields are sparse and hundreds wide: a wide table
-- would be ~430 columns of which 37 are set. `idx` preserves array order,
-- which matters because the array-valued fields are the ones that join
-- records together (affixCheckList, lootTable, records).
--
-- num and txt are exclusive: numbers stay comparable without CAST, strings
-- stay joinable. A missing row means the field is at its default, which for
-- this data means zero -- never "unknown".
--
-- lo/hi are the band the stat actually rolls between; `num` is the stored
-- MIDPOINT, which is not what the game shows. `roll` says which of three
-- cases produced them, because two of them look alike in the numbers:
--   'rolled'    lo/hi are the real band
--   'fixed'     the field draws nothing; lo = hi = num, exactly
--   'unmodeled' NOT KNOWN to roll. lo/hi are NULL on purpose -- a band would
--               claim it rolls and a fixed point would claim it does not.
CREATE TABLE IF NOT EXISTS item_stat (
    item_id INTEGER NOT NULL REFERENCES item(id) ON DELETE CASCADE,
    field   TEXT    NOT NULL,
    idx     INTEGER NOT NULL,
    num     REAL,
    txt     TEXT,
    lo      REAL,
    hi      REAL,
    roll    TEXT,
    PRIMARY KEY (item_id, field, idx)
) WITHOUT ROWID;

CREATE INDEX IF NOT EXISTS item_stat_field_idx ON item_stat(field, num);
CREATE INDEX IF NOT EXISTS item_stat_txt_idx   ON item_stat(field, txt);

-- ---------------------------------------------------------------------------
-- Affixes
--
-- One row per LootRandomizer record under records/items/lootaffixes/. These
-- are NOT items and are deliberately not in the `item` table: an affix has no
-- slot of its own, it modifies whatever it rolls onto.
--
-- NOTHING IS DEDUPLICATED HERE. 738 records are byte-identical to a sibling
-- and sit in the same pool tables (the _b/_c class-prefix pairs). Two entries
-- in one pool may be HOW that affix rolls twice as often, so collapsing them
-- would silently halve those rates. They are stored in full and grouped only
-- at display time, where the decision is reversible.
CREATE TABLE IF NOT EXISTS affix (
    id       INTEGER PRIMARY KEY,
    path     TEXT NOT NULL UNIQUE,
    kind     TEXT NOT NULL,      -- Prefix / Suffix, from the folder
    name_tag TEXT,
    name     TEXT,               -- resolved English; several records share one
    rarity   TEXT,               -- itemClassification
    level_req INTEGER,
    jitter   REAL,               -- lootRandomizerJitter: the roll half-width %
    cost     INTEGER
);

CREATE INDEX IF NOT EXISTS affix_name_idx ON affix(name);
CREATE INDEX IF NOT EXISTS affix_kind_idx ON affix(kind, rarity);

-- Every non-default field of an affix, with the band it rolls between.
--
-- `value` is the game's stored number and is the MIDPOINT, not the roll.
-- lo/hi come from rolls.roll_band and are NULL for text fields, which do not
-- roll. Storing all three means a query can show "18 (14-22)" without
-- recomputing, and a wrong band is visible next to the value it came from.
CREATE TABLE IF NOT EXISTS affix_stat (
    affix_id INTEGER NOT NULL REFERENCES affix(id) ON DELETE CASCADE,
    field    TEXT    NOT NULL,
    idx      INTEGER NOT NULL,
    value    REAL,
    lo       REAL,
    hi       REAL,
    txt      TEXT,
    PRIMARY KEY (affix_id, field, idx)
) WITHOUT ROWID;

CREATE INDEX IF NOT EXISTS affix_stat_field_idx ON affix_stat(field);

-- ---------------------------------------------------------------------------
-- Affix eligibility: which item classes an affix can roll onto.
--
-- An affix record says nothing about where it can appear. The game states it
-- the other way round, in the drop tables: a Class=LootItemTable_DynWeight
-- record names BOTH the item bases it drops (lootName<N>) and the affix pools
-- that apply to them (prefixTableName<N> / rarePrefixTableName<N> and the
-- suffix equivalents). Joining those two lists is the eligibility fact, and
-- the game has already computed it.
--
-- Stored as item CLASS, not as a display label, so it joins directly to
-- item.class and no second slot vocabulary has to be kept in step.
CREATE TABLE IF NOT EXISTS affix_eligibility (
    affix_id   INTEGER NOT NULL REFERENCES affix(id) ON DELETE CASCADE,
    item_class TEXT    NOT NULL,     -- ArmorProtective_Waist, WeaponMelee_Axe, ...
    tier       TEXT    NOT NULL,     -- 'magical' or 'rare': which pool reached it
    PRIMARY KEY (affix_id, item_class, tier)
) WITHOUT ROWID;

CREATE INDEX IF NOT EXISTS affix_eligibility_class_idx
    ON affix_eligibility(item_class);

-- ---------------------------------------------------------------------------
-- The drop graph: who can hand out which item.
--
-- The archives never state this directly. An item names nobody; a loot table
-- names items and other tables; a creature or chest names a table. So "what
-- drops this" is a reachability question over three record kinds.
--
-- A HOLDER IS ANY RECORD THAT NAMES A TABLE AND IS NOT ITSELF ONE -- not just
-- a creature. Boss chests under records/items/lootchests/, Shattered Realm
-- bosses under records/endlessdungeon/, and a handful of live bosses that
-- still ship under records/sandbox/ (The Dread, Namadea) all hold tables.
-- Filtering to /creatures/ looks obviously right and loses 53 items.
CREATE TABLE IF NOT EXISTS loot_table (
    id    INTEGER PRIMARY KEY,
    path  TEXT NOT NULL UNIQUE,
    class TEXT NOT NULL      -- LootItemTable_DynWeight / LootMasterTable / LevelTable
);

CREATE TABLE IF NOT EXISTS holder (
    id         INTEGER PRIMARY KEY,
    path       TEXT NOT NULL UNIQUE,
    class      TEXT NOT NULL,
    kind       TEXT NOT NULL,    -- top-level folder: creatures, items, sandbox, ...
    is_monster INTEGER NOT NULL, -- Class=Monster, as opposed to a chest or object
    name_tag   TEXT,             -- `description`, the creature's name tag
    name       TEXT,             -- resolved English, NULL when the game names it nowhere
    -- Monster-only, NULL on chests and objects. classification is the rarity
    -- the farm ranking weights by: SuperBoss > Boss > Hero > Champion > Common.
    classification TEXT,         -- monsterClassification
    min_level  INTEGER,
    max_level  INTEGER,
    experience INTEGER
);

CREATE INDEX IF NOT EXISTS holder_name_idx    ON holder(name);
CREATE INDEX IF NOT EXISTS holder_monster_idx ON holder(is_monster);

-- One row per (item, holder) pair the graph reaches.
CREATE TABLE IF NOT EXISTS item_drop (
    item_id   INTEGER NOT NULL REFERENCES item(id) ON DELETE CASCADE,
    holder_id INTEGER NOT NULL REFERENCES holder(id) ON DELETE CASCADE,
    PRIMARY KEY (item_id, holder_id)
) WITHOUT ROWID;

CREATE INDEX IF NOT EXISTS item_drop_holder_idx ON item_drop(holder_id);

-- ---------------------------------------------------------------------------
-- Spawn zones. THE ONE TABLE NOT DERIVED FROM THE GAME ARCHIVES.
--
-- Map placement lives in Grim Dawn's compiled level files, which nothing here
-- parses. grimtools.com computes it from the same game data and publishes it
-- client-side; `spawn_meta` records exactly which download these rows came
-- from, because unlike everything else in this catalogue they cannot be
-- re-derived locally.
--
-- Keyed by monster DESCRIPTION TAG, not by creature record: the tag is the one
-- identifier both sides already speak, so this table depends on grimtools
-- alone and survives a game re-extract. The join to holders is done in SQL.
--
-- A FAILED FETCH LEAVES THESE EMPTY AND THE BUILD SUCCEEDS. Zones are then
-- visibly absent rather than guessed, which is the honest outcome for the one
-- thing this repo cannot compute for itself.
CREATE TABLE IF NOT EXISTS monster_zone (
    monster_tag TEXT    NOT NULL,
    zone_tag    TEXT    NOT NULL,
    zone_name   TEXT,               -- resolved English, NULL if the tag is unknown
    placements  INTEGER NOT NULL,   -- summed across creature records sharing a tag
    PRIMARY KEY (monster_tag, zone_tag)
) WITHOUT ROWID;

CREATE INDEX IF NOT EXISTS monster_zone_zone_idx ON monster_zone(zone_name);

CREATE TABLE IF NOT EXISTS spawn_meta (
    key   TEXT PRIMARY KEY,
    value TEXT
);

-- ---------------------------------------------------------------------------
-- Bonuses an item grants through a REFERENCE rather than its own fields.
--
-- A component carries its own stats (Aether Soul: +30 DA, +16% Aether Resist,
-- +10% Aether damage) AND points at a completion-bonus POOL. The pool is a
-- LootRandomizerTable whose members are ordinary LootRandomizer records, so
-- they roll bands exactly like affixes do -- the pool is the "one of these N"
-- you get when the component completes, and `pool_path` keeps that grouping.
--
-- Pet bonuses are a different shape: a petbonus.tpl record carrying stats
-- directly, with no pool and no roll.
CREATE TABLE IF NOT EXISTS bonus (
    id     INTEGER PRIMARY KEY,
    path   TEXT NOT NULL UNIQUE,
    kind   TEXT NOT NULL,       -- 'completion' or 'pet'
    jitter REAL                 -- NULL for pet bonuses, which do not roll
);

CREATE TABLE IF NOT EXISTS bonus_stat (
    bonus_id INTEGER NOT NULL REFERENCES bonus(id) ON DELETE CASCADE,
    field    TEXT    NOT NULL,
    idx      INTEGER NOT NULL,
    value    REAL,
    lo       REAL,
    hi       REAL,
    txt      TEXT,
    PRIMARY KEY (bonus_id, field, idx)
) WITHOUT ROWID;

-- pool_path is NULL for pet bonuses and set for completion bonuses, where it
-- says which pool the member came from -- without it, a component's nine
-- mutually exclusive outcomes read as nine simultaneous ones.
CREATE TABLE IF NOT EXISTS item_bonus (
    item_id   INTEGER NOT NULL REFERENCES item(id) ON DELETE CASCADE,
    bonus_id  INTEGER NOT NULL REFERENCES bonus(id) ON DELETE CASCADE,
    relation  TEXT    NOT NULL,
    pool_path TEXT,
    PRIMARY KEY (item_id, bonus_id, relation)
) WITHOUT ROWID;

-- Skills an item references, with the display name resolved.
--
-- Four different relations, and they are NOT the same thing:
--   granted   itemSkillName      -- the skill the item gives you
--   augment   augmentSkillName*  -- +N to a skill you already have
--   mastery   augmentMasteryName*-- +N to every skill in a mastery
--   modifier  modifierSkillName* -- a modifier applied to another skill
CREATE TABLE IF NOT EXISTS item_skill (
    item_id    INTEGER NOT NULL REFERENCES item(id) ON DELETE CASCADE,
    relation   TEXT    NOT NULL,
    skill_path TEXT    NOT NULL,
    skill_name TEXT,
    level      INTEGER,
    PRIMARY KEY (item_id, relation, skill_path)
) WITHOUT ROWID;

CREATE INDEX IF NOT EXISTS item_skill_name_idx ON item_skill(skill_name);

-- ---------------------------------------------------------------------------
-- Factions.
--
-- The id is the game's own `myFaction` value -- 'User9', 'Survivors' -- and it
-- is what items point at through `factionSource`. The display name comes from
-- the tag `tagFaction<id>`, which is what the game itself renders.
--
-- THE RECORD FILENAME IS NOT THE NAME. factiongdx3_dread.dbr declares
-- myFaction=User19, and tagFactionUser19 reads 'Traps'; factiongdx3_traps.dbr
-- declares User20, which reads 'The Dread'. The two are swapped relative to
-- their filenames. The tag wins, because the tag is what the player sees.
CREATE TABLE IF NOT EXISTS faction (
    id   TEXT PRIMARY KEY,       -- myFaction: User9, Survivors, Aetherials...
    name TEXT,                   -- resolved from tagFaction<id>
    path TEXT NOT NULL UNIQUE
);

-- ---------------------------------------------------------------------------
-- Faction vendors and the stock they reliably carry.
--
-- STATIC STOCK ONLY. `marketStaticItems` is a fixed list -- what the vendor
-- always has. The other market fields (marketFileName's random tables,
-- marketAxeTable and friends) describe what MIGHT roll into the shop, which
-- is a different claim; recording those as "sold by" would make nearly every
-- vendor sell nearly everything.
--
-- Standing comes from the FIELD NAME on the faction market record --
-- friendlyNormalTable, respectedNormalTable, honoredNormalTable,
-- reveredNormalTable -- not from the stock table's filename. The game states
-- the tier structurally and that is what is read.
--
-- The vendor's faction comes from its own `factions` field, resolved through
-- the faction record's myFaction. No filename prefix is interpreted.
CREATE TABLE IF NOT EXISTS vendor (
    id         INTEGER PRIMARY KEY,
    path       TEXT NOT NULL UNIQUE,
    name       TEXT,
    faction_id TEXT REFERENCES faction(id)
);

CREATE TABLE IF NOT EXISTS vendor_stock (
    vendor_id INTEGER NOT NULL REFERENCES vendor(id) ON DELETE CASCADE,
    item_id   INTEGER NOT NULL REFERENCES item(id) ON DELETE CASCADE,
    standing  TEXT    NOT NULL,   -- Friendly / Respected / Honored / Revered
    PRIMARY KEY (vendor_id, item_id, standing)
) WITHOUT ROWID;

CREATE INDEX IF NOT EXISTS vendor_stock_item_idx ON vendor_stock(item_id);
