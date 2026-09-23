"""The skills a character can have, plus the skills items and sets point at.

TWO SCOPES, UNIONED, and each answers a different question:

  * REFERENCED -- everything an item grants, augments or modifies. Without it
    a "+2 to Blade Arc" on a medal names a record the catalogue does not hold.
  * THE PLAYER TREE -- records/skills/playerclass*, /devotion/ and /default/.
    Without it 262 of the 433 skills invested across six real characters
    resolve to nothing, devotion worst of all at 209 of 209 missing. A
    character's own skills are exactly what profile.sqlite stores paths to.

The remaining ~4,600 records are monster and internal skills that neither an
item nor a player character can reach, and they stay out: the rule is "what a
player can have or an item can grant", which is checkable, rather than "all of
them", which only looks simpler.

TWO SHAPES THAT ARE NOT ERRORS:

  * 1,936 of the referenced records are Skill_Modifier, which carry no
    skillDisplayName at all -- a modifier is described on the skill it
    modifies. A NULL name there is the right answer.
  * Skill values are often PER-LEVEL ARRAYS, and some are expressions like
    'charLevel/4+1' rather than numbers. Expressions are kept as text rather
    than evaluated: the level they resolve against is the character's, which
    this catalogue does not have.
"""
from ...archive import values as V

# The player-facing tree. Every skill a character can put a point in lives
# under one of these: the ten masteries (playerclass01..10, plus the
# itemskills* folders which are reached through items and covered by the
# reference sweep), the constellation, and the skills the game grants everyone.
PLAYER_PREFIXES = ('records/skills/playerclass',
                   'records/skills/devotion/',
                   'records/skills/default/')

NAME_FIELD = 'skillDisplayName'
DESC_FIELD = 'skillBaseDescription'
MAX_LEVEL_FIELD = 'skillMaxLevel'
BOOKKEEPING = frozenset({'Class', 'templateName', 'FileDescription',
                         NAME_FIELD, DESC_FIELD})


def referenced_paths(conn) -> set[str]:
    """Every skill record the catalogue points at, from any direction."""
    paths = {row[0] for row in conn.execute(
        'SELECT DISTINCT skill_path FROM item_skill')}
    paths |= {row[0] for row in conn.execute(
        "SELECT DISTINCT txt FROM set_bonus "
        "WHERE field LIKE '%SkillName%' AND txt IS NOT NULL")}
    paths |= {row[0] for row in conn.execute(
        "SELECT DISTINCT txt FROM item_stat "
        "WHERE field LIKE '%SkillName%' AND txt IS NOT NULL")}
    return {p for p in paths if p}


def player_paths(db) -> set[str]:
    """Every record under the player-facing tree, referenced or not.

    Read from the archive rather than from what the catalogue happens to point
    at: a devotion node nothing references is still a node the player can bind
    a point to, and that is the whole reason this scope exists.
    """
    found = set()
    for prefix in PLAYER_PREFIXES:
        found.update(db.paths(prefix))
    return found


def wanted_paths(conn, db) -> set[str]:
    """The union of the two scopes. The gate checks both halves separately."""
    return referenced_paths(conn) | player_paths(db)


def extract(conn, db, tags: dict[str, str]) -> dict[str, int]:
    conn.execute('DELETE FROM skill_stat')
    conn.execute('DELETE FROM skill')

    skill_rows, stat_rows = [], []
    absent = 0
    wanted = wanted_paths(conn, db)
    for path in sorted(wanted):
        if path not in db:
            absent += 1
            continue
        attrs = V.non_default(db.read(path))
        skill_id = len(skill_rows) + 1
        name_tag = V.first_str(attrs, NAME_FIELD)
        desc_tag = V.first_str(attrs, DESC_FIELD)
        skill_rows.append((
            skill_id, path,
            V.first_str(attrs, 'Class'),
            name_tag,
            V.clean_name(tags.get(name_tag)) if name_tag else None,
            V.clean_name(tags.get(desc_tag)) if desc_tag else None,
            V.first(attrs, MAX_LEVEL_FIELD),
        ))
        for row in V.stat_rows(attrs):
            if row.field in BOOKKEEPING:
                continue
            stat_rows.append((skill_id, row.field, row.idx, row.num, row.txt))

    conn.executemany(
        'INSERT INTO skill (id, path, class, name_tag, name, description, '
        'max_level) VALUES (?,?,?,?,?,?,?)', skill_rows)
    conn.executemany(
        'INSERT OR IGNORE INTO skill_stat (skill_id, field, idx, num, txt) '
        'VALUES (?,?,?,?,?)', stat_rows)
    conn.commit()
    named = sum(1 for r in skill_rows if r[4])
    return {'skills': len(skill_rows),
            'player-tree skills': len(player_paths(db)),
            'skill stat rows': len(stat_rows),
            'with a display name': named,
            'modifiers (no name by design)':
                sum(1 for r in skill_rows if r[2] == 'Skill_Modifier'),
            'referenced but absent': absent}
