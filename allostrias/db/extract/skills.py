"""The skills items and sets point at.

Scoped to what is REFERENCED: 3,120 records of the 13,993 in the archives.
Everything an item grants, augments or modifies is covered; the remainder are
monster and internal skills nothing in this catalogue names. Widening is a
one-line change if character stat derivation ever needs the full tree.

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


def extract(conn, db, tags: dict[str, str]) -> dict[str, int]:
    conn.execute('DELETE FROM skill_stat')
    conn.execute('DELETE FROM skill')

    skill_rows, stat_rows = [], []
    absent = 0
    for path in sorted(referenced_paths(conn)):
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
            'skill stat rows': len(stat_rows),
            'with a display name': named,
            'modifiers (no name by design)':
                sum(1 for r in skill_rows if r[2] == 'Skill_Modifier'),
            'referenced but absent': absent}
