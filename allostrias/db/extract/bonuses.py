"""What an item grants by REFERENCE: completion bonuses, pet bonuses, skills.

Three fields on an item point at records that hold the actual effect, and
until they are followed the item looks emptier than it is. 1,965 items name a
granted skill, 528 a pet bonus, 170 a completion-bonus pool -- all of them
stored as bare paths.

THE COMPLETION POOL IS A CHOICE, NOT A SUM. `bonusTableName` points at a
LootRandomizerTable whose members are ordinary LootRandomizer records; a
component that completes gets ONE of them. Flattening the nine members of
Aether Soul's pool into nine bonuses would read as a component granting all
nine at once, so `pool_path` is carried through to keep the grouping.

Pool members roll. They are LootRandomizer records with their own
lootRandomizerJitter, so their bands come from the same roll_band as affixes
-- 8% Fire Resist at jitter 50 is 4-12, not a flat 8.

Pet bonuses do NOT roll. They are petbonus.tpl records carrying stats
directly, and jitter is left NULL rather than defaulted to zero, because zero
would assert "measured, does not roll" where NULL says "different mechanism".

SKILL MODIFIERS HAVE NO NAME OF THEIR OWN, and that is the game's design
rather than a gap here: a Skill_Modifier record carries no skillDisplayName
because it is described on the skill it modifies. So `modifierSkillName`
resolves to NULL every time, and `modifiedSkillName` -- the skill being
modified, which IS named -- is stored alongside it as its own relation. A
fallback that copied the modified skill's name onto the modifier would read
as two separate skills with one name.
"""
from ...archive import values as V
from ...archive.rolls import roll_band

POOL_FIELD = 'bonusTableName'
PET_FIELD = 'petBonusName'
MEMBER_PREFIX = 'randomizerName'

# (field prefix, level-field prefix, relation). Numbered fields are probed
# 1..8; the game uses at most 3 today but the numbering is its own, not ours.
SKILL_REFS = (
    ('itemSkillName', 'itemSkillLevel', 'granted'),
    ('augmentSkillName', 'augmentSkillLevel', 'augment'),
    ('augmentMasteryName', 'augmentMasteryLevel', 'mastery'),
    ('modifierSkillName', 'modifierSkillLevel', 'modifier'),
    ('modifiedSkillName', 'modifiedSkillLevel', 'modified'),
)
MAX_NUMBERED = 8

# Bookkeeping on a bonus record: describes the bonus, is not part of it.
BOOKKEEPING = frozenset({
    'Class', 'templateName', 'FileDescription', 'itemClassification',
    'levelRequirement', 'lootRandomizerCost', 'lootRandomizerJitter',
    'lootRandomizerName', 'marketAdjustmentPercent',
})


def _stat_rows(bonus_id, attrs, jitter):
    for row in V.stat_rows(attrs):
        if row.field in BOOKKEEPING:
            continue
        if row.txt is not None:
            yield (bonus_id, row.field, row.idx, None, None, None, row.txt)
        elif jitter:
            lo, hi = roll_band(row.num, jitter)
            yield (bonus_id, row.field, row.idx, row.num, lo, hi, None)
        else:
            # No jitter means a fixed value, so the band collapses to a point
            # rather than being left blank or invented.
            yield (bonus_id, row.field, row.idx, row.num, row.num, row.num, None)


def extract(conn, db, tags: dict[str, str]) -> dict[str, int]:
    for table in ('item_skill', 'item_bonus', 'bonus_stat', 'bonus'):
        conn.execute(f'DELETE FROM {table}')

    items = {row['id']: row['path']
             for row in conn.execute('SELECT id, path FROM item')}

    bonus_id_of: dict[str, int] = {}
    bonus_rows, bonus_stats, item_bonus_rows, skill_rows = [], [], [], []
    skill_name_cache: dict[str, str | None] = {}
    missing_targets = 0

    def bonus_for(path: str, kind: str) -> int | None:
        """Register a bonus record, reading it once. None if it is not here."""
        nonlocal missing_targets
        if path in bonus_id_of:
            return bonus_id_of[path]
        if path not in db:
            missing_targets += 1
            return None
        attrs = V.non_default(db.read(path))
        # A completion member states its own jitter; a pet bonus has none, and
        # NULL is kept rather than 0 -- see the module docstring.
        jitter = (V.first(attrs, 'lootRandomizerJitter', 0.0) or 0.0
                  if kind == 'completion' else None)
        new_id = len(bonus_rows) + 1
        bonus_rows.append((new_id, path, kind, jitter))
        bonus_stats.extend(_stat_rows(new_id, attrs, jitter or 0.0))
        bonus_id_of[path] = new_id
        return new_id

    def skill_name(path: str) -> str | None:
        if path not in skill_name_cache:
            name = None
            if path in db:
                tag = V.first_str(V.non_default(db.read(path)),
                                  'skillDisplayName')
                name = tags.get(tag) if tag else None
            skill_name_cache[path] = name
        return skill_name_cache[path]

    for item_id, item_path in items.items():
        attrs = V.non_default(db.read(item_path))

        pool = V.first_str(attrs, POOL_FIELD)
        if pool:
            pool = pool.lower()
            pool_attrs = V.non_default(db.read(pool)) if pool in db else {}
            for field, values in pool_attrs.items():
                if not field.startswith(MEMBER_PREFIX):
                    continue
                for member in values:
                    if not isinstance(member, str) or not member:
                        continue
                    found = bonus_for(member.lower(), 'completion')
                    if found is not None:
                        item_bonus_rows.append(
                            (item_id, found, 'completion', pool))

        pet = V.first_str(attrs, PET_FIELD)
        if pet:
            found = bonus_for(pet.lower(), 'pet')
            if found is not None:
                item_bonus_rows.append((item_id, found, 'pet', None))

        for name_field, level_field, relation in SKILL_REFS:
            for suffix in ('',) + tuple(str(n) for n in range(1, MAX_NUMBERED + 1)):
                target = V.first_str(attrs, name_field + suffix)
                if not target:
                    continue
                level = V.first(attrs, level_field + suffix)
                if level is None and not suffix:
                    level = V.first(attrs, level_field + 'Eq')
                skill_rows.append((
                    item_id, relation, target.lower(), skill_name(target.lower()),
                    int(level) if isinstance(level, (int, float)) else None))

    conn.executemany('INSERT INTO bonus (id, path, kind, jitter) '
                     'VALUES (?,?,?,?)', bonus_rows)
    conn.executemany('INSERT INTO bonus_stat '
                     '(bonus_id, field, idx, value, lo, hi, txt) '
                     'VALUES (?,?,?,?,?,?,?)', bonus_stats)
    conn.executemany('INSERT OR IGNORE INTO item_bonus '
                     '(item_id, bonus_id, relation, pool_path) '
                     'VALUES (?,?,?,?)', item_bonus_rows)
    conn.executemany('INSERT OR IGNORE INTO item_skill '
                     '(item_id, relation, skill_path, skill_name, level) '
                     'VALUES (?,?,?,?,?)', skill_rows)
    conn.commit()
    named = sum(1 for r in skill_rows if r[3])
    return {'bonus records': len(bonus_rows),
            'bonus stat rows': len(bonus_stats),
            'item-bonus links': len(item_bonus_rows),
            'item-skill links': len(skill_rows),
            'skills that resolved to a name': named,
            'reference targets absent': missing_targets}
