"""Quests.arc -> `quest_reward`: the items a quest hands out.

A quest is not a record. Its script is a .qst file in each era's Quests.arc,
and it names what it rewards by record path: an item directly (the Forgotten
Gods cults give the Korvan Swiftness, Dreeg's Vector and Rahn's Might rune
blueprints that way, and nothing else in the game does) or a loot table, which
is followed through its children here as the drop walk follows it.

A REWARD IS NOT A DROP, and the table is separate for that reason: item_drop
feeds the Monster Infrequent rule, and a quest's blueprint is no MI.

The .qst format is not decoded. Its record paths are plain ASCII, so they are
found by pattern; every one kept is checked to be a catalogued item or a loot
table, and a quest that names neither contributes nothing. What that cannot say
is WHICH step rewards the item, or whether a step is conditional (a choice
between two rewards reads as both) -- "a quest can give this", nothing more.
"""
import os
import re

from ... import settings as S
from ...archive.arc import Arc

PATH = re.compile(rb'records/[a-z0-9_/&]+\.dbr')


def _quest_refs(paths):
    """{quest name: {record path}} over every .qst in the given Quests.arc files,
    later eras overriding earlier ones under the same name."""
    out = {}
    for arc_path in paths:
        with Arc(arc_path) as arc:
            for i, name in enumerate(arc.names):
                if name.endswith('.qst'):
                    data = (arc.read_file(i) or b'').lower()
                    out[name] = {m.decode() for m in PATH.findall(data)}
    return out


def extract(conn, db, _tags) -> dict[str, int]:
    conn.execute('DELETE FROM quest_reward')
    items = {row['path']: row['id'] for row in conn.execute('SELECT id, path FROM item')}
    tables = {row['path'] for row in conn.execute('SELECT path FROM loot_table')}

    def expand(path, seen):
        """Items a loot table can give, through nested tables."""
        if path in seen:
            return set()
        seen.add(path)
        out = set()
        for values in db.read(path).values():
            for v in values:
                ref = v.lower() if isinstance(v, str) else None
                if ref in tables:
                    out |= expand(ref, seen)
                elif ref in items:
                    out.add(ref)
        return out

    rows, quests = set(), set()
    for quest, refs in _quest_refs(S.load().quest_arc_paths).items():
        got = {r for r in refs if r in items}
        for table in refs & tables:
            got |= expand(table, set())
        for path in got:
            rows.add((items[path], os.path.splitext(quest)[0]))
        if got:
            quests.add(quest)
    conn.executemany('INSERT INTO quest_reward (item_id, quest) VALUES (?,?)', sorted(rows))
    conn.commit()
    return {'quests with a reward': len(quests),
            'items a quest gives': len({r[0] for r in rows})}
