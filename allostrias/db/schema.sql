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
    -- The tier word the game renders IN FRONT of the name: Mythical,
    -- Empowered, Elite, and ~46 mundane ones (Worn, Leather, Infantry).
    --
    -- This is why `name` alone cannot identify an item. A record under
    -- records/items/upgraded/ shares its itemNameTag with the base it upgrades,
    -- so both resolve to "Deathmarked Claw" and only the style tells them
    -- apart. 1,788 records carry one.
    --
    -- `style_tag` is kept raw beside the resolved text because one tag
    -- (tagStyleArmorFabric01, 2 records) resolves in no archive: the fact that
    -- a record HAS a style is not the same as knowing what it is called, and
    -- collapsing them would lose the first.
    style_tag      TEXT,                   -- itemStyleTag, NULL if none
    style          TEXT,                   -- resolved English, NULL if unresolved
    classification TEXT,                   -- Rare / Epic / Legendary / ...
    level_req      INTEGER,
    set_path       TEXT,                   -- lootsets/*.dbr, resolved in a later step
    -- Monster Infrequent. Derived in extract/mi.py AFTER drops exist, because
    -- the exclusion it depends on (a blueprint pointing at the record) needs
    -- the loot-table walk. NULL until that step runs.
    is_mi          INTEGER,
    -- What the game shows. GENERATED, not stored: it is a function of two
    -- columns in the same row, so it cannot drift from them and costs nothing.
    --
    -- ⚠️ STILL NOT UNIQUE, and must never be used as a key. Adding the style
    -- splits 1,175 of the 2,025 colliding names; 850 remain -- "Murderer's
    -- Armor" is 18 records with one style between them, level-tier variants of
    -- the same gear. Names are not unique in this game and the style was never
    -- going to make them so.
    --
    -- The composition "<style> <name>" is VERIFIED for the two Unique tiers
    -- against an independent oracle -- Item Assistant's own rendered names,
    -- 579 of 579 exact, see tests/test_stash_iagd.py. The other 48 style
    -- families have no oracle in any data this project holds; they are assumed
    -- to render the same way, and that assumption is recorded here rather than
    -- buried.
    display_name   TEXT GENERATED ALWAYS AS (
                       CASE WHEN name IS NULL THEN NULL
                            WHEN style IS NULL THEN name
                            ELSE style || ' ' || name END) VIRTUAL
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
    -- Prefix / Suffix / Crafting, from the folder. Crafting is the bonus a
    -- crafted item carries -- the save gives it its own field, apart from
    -- prefix and suffix -- and it has no affix_eligibility rows because it
    -- rolls from no pool table. An empty eligibility means "not obtainable"
    -- for the other two kinds only.
    kind     TEXT NOT NULL,
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

-- The stats an affix grants its PETS, through `petBonusName`.
--
-- The affix names a petbonus record and the stats live there, but the BAND is
-- the affix's: the game rolls them with the affix's own lootRandomizerJitter
-- (Subjugator's I stores +10% pet damage at jitter 32 and shows 7-13). Two pet
-- records are named by affixes of different jitter, so the band cannot live on
-- the pet record -- which is why this is not the `bonus` table.
CREATE TABLE IF NOT EXISTS affix_pet_stat (
    affix_id INTEGER NOT NULL REFERENCES affix(id) ON DELETE CASCADE,
    field    TEXT    NOT NULL,
    idx      INTEGER NOT NULL,
    value    REAL,
    lo       REAL,
    hi       REAL,
    txt      TEXT,
    PRIMARY KEY (affix_id, field, idx)
) WITHOUT ROWID;

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

-- ---------------------------------------------------------------------------
-- Crafting recipes.
--
-- A blueprint names its output twice: `artifactName` is often a LOOT TABLE
-- rather than an item, and `forcedRandomArtifactName` is the concrete result.
-- Both are kept -- the table is what the game rolls against, the forced name
-- is what you actually get.
--
-- The base reagent slot accepts ALTERNATIVES: 115 blueprints list up to 7
-- acceptable items for it. The numbered slots never do. `alternative` marks
-- which option a row is, so a slot with seven entries reads as one
-- requirement with seven ways to satisfy it rather than seven requirements.
CREATE TABLE IF NOT EXISTS recipe (
    id             INTEGER PRIMARY KEY,
    blueprint_id   INTEGER NOT NULL REFERENCES item(id) ON DELETE CASCADE,
    output_item_id INTEGER REFERENCES item(id),
    output_table   TEXT,          -- artifactName, when it is a loot table
    cost           INTEGER,
    quantity       INTEGER
);

CREATE TABLE IF NOT EXISTS recipe_reagent (
    recipe_id   INTEGER NOT NULL REFERENCES recipe(id) ON DELETE CASCADE,
    slot        TEXT    NOT NULL,   -- 'base', '1', '2', ...
    alternative INTEGER NOT NULL,   -- 0 unless the slot lists options
    item_id     INTEGER REFERENCES item(id),
    item_path   TEXT    NOT NULL,   -- kept even when the item is not catalogued
    quantity    INTEGER,
    PRIMARY KEY (recipe_id, slot, alternative)
) WITHOUT ROWID;

-- ---------------------------------------------------------------------------
-- Item sets.
--
-- A set's bonuses are ARRAYS INDEXED BY PIECE COUNT, and the index is
-- RIGHT-ALIGNED: the LAST entry always applies at the full set. Most arrays
-- are exactly as long as the member list, but 11 are shorter -- [0,0,0,3] on
-- a six-piece set means +3 at six pieces, not at four. Reading such an array
-- from the left would attribute a full-set bonus to half a set.
CREATE TABLE IF NOT EXISTS item_set (
    id          INTEGER PRIMARY KEY,
    path        TEXT NOT NULL UNIQUE,
    name        TEXT,
    description TEXT,
    members     INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS set_member (
    set_id  INTEGER NOT NULL REFERENCES item_set(id) ON DELETE CASCADE,
    item_id INTEGER REFERENCES item(id),
    item_path TEXT NOT NULL,
    PRIMARY KEY (set_id, item_path)
) WITHOUT ROWID;

CREATE TABLE IF NOT EXISTS set_bonus (
    set_id INTEGER NOT NULL REFERENCES item_set(id) ON DELETE CASCADE,
    pieces INTEGER NOT NULL,      -- how many worn pieces this applies at
    field  TEXT    NOT NULL,
    value  REAL,
    txt    TEXT,
    PRIMARY KEY (set_id, pieces, field)
) WITHOUT ROWID;

CREATE INDEX IF NOT EXISTS set_member_item_idx ON set_member(item_id);

-- ---------------------------------------------------------------------------
-- Skills that items and sets reference.
--
-- SCOPED TO WHAT IS REFERENCED -- 3,120 records of the 13,993 in the
-- archives. Every skill an item grants, augments, modifies, or that a set
-- bonus names, is here; the rest are monster and internal skills that nothing
-- in this catalogue points at. Widening it is one prefix change if character
-- stat derivation ever needs the whole tree.
--
-- 1,936 of them are Skill_Modifier records, which carry NO skillDisplayName
-- by design -- a modifier is described on the skill it modifies. Their `name`
-- is NULL and that is correct, not missing.
CREATE TABLE IF NOT EXISTS skill (
    id          INTEGER PRIMARY KEY,
    path        TEXT NOT NULL UNIQUE,
    class       TEXT,
    name_tag    TEXT,
    name        TEXT,
    description TEXT,
    max_level   INTEGER
);

-- Skill values are frequently PER-LEVEL ARRAYS, and some are expressions
-- ('charLevel/4+1') rather than numbers. Numbers go in `num`, everything
-- else stays as text in `txt` rather than being evaluated.
CREATE TABLE IF NOT EXISTS skill_stat (
    skill_id INTEGER NOT NULL REFERENCES skill(id) ON DELETE CASCADE,
    field    TEXT    NOT NULL,
    idx      INTEGER NOT NULL,
    num      REAL,
    txt      TEXT,
    PRIMARY KEY (skill_id, field, idx)
) WITHOUT ROWID;

CREATE INDEX IF NOT EXISTS skill_name_idx      ON skill(name);
CREATE INDEX IF NOT EXISTS skill_stat_field_idx ON skill_stat(field);
