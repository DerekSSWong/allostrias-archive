#!/usr/bin/env python3
"""Every granted-skill block the renderer can print keeps the two rules the page
reads it by (sheet/shell.html grantWalker, the user's display of 2026-09-29):

  1. "Grants: X" heads it and every line after it starts "X: " -- so stripping
     that prefix never leaves a line still carrying its skill's name, or strips
     a line that is not the skill's.
  2. The skill's description, when it has one, is the SECOND line, and the
     page's test for it -- ends in "." or carries no digit -- holds for every
     description and for no first line of a skill that has none. (Three
     descriptions end otherwise: "...every strike," and two "(Passive bonus)".)

Over every item and affix in the catalogue that grants a skill, and every set.
"""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from allostrias import settings as S                # noqa: E402
from allostrias import item_lines as L              # noqa: E402
from allostrias import item_stats as I              # noqa: E402
from allostrias.db import catalogue                 # noqa: E402
from allostrias.sheet import build as SB            # noqa: E402

cfg = S.load()


def description(txt):
    """The granted skill's own description, following the same one buff hop."""
    skill = I.read_rel(re.search(r'^itemSkillName=' + I.PATH, txt, re.M).group(1)) or ''
    if not re.search(r'^skillDisplayName=', skill, re.M):
        hop = re.search(r'^buffSkillName=' + I.PATH, skill, re.M)
        skill = (I.read_rel(hop.group(1)) if hop else '') or ''
    m = re.search(r'^skillBaseDescription=(\S+)', skill, re.M)
    return I.clean_name(I.SKILL_TAGS.get(m.group(1), '')) if m else ''


def check(where, lines, desc, bad):
    if not lines:
        return 0
    if not lines[0].startswith('Grants: '):
        bad.append(f'{where}: the block does not open with "Grants:": {lines[0]!r}')
        return 1
    name = lines[0][len('Grants: '):]
    rest = [l for l in lines[1:]]
    if any(not l.startswith(name + ': ') for l in rest):
        bad.append(f'{where}: a line of {name} lacks its "{name}: " -- {next(l for l in rest if not l.startswith(name + ": "))!r}')
    body = [l[len(name) + 2:] for l in rest]
    looks = lambda t: t.endswith('.') or not re.search(r'\d', t)
    if desc and (not body or body[0] != desc or not looks(desc)):
        bad.append(f'{where}: {name}\'s description is not its second line, or would not read as one')
    if not desc and body and looks(body[0]):
        bad.append(f'{where}: {name} has no description, yet its first line reads as one: {body[0]!r}')
    return 1


def main():
    conn = catalogue.connect(cfg.catalogue_db, create=False)
    bad, n, with_desc = [], 0, 0
    for (p,) in conn.execute('SELECT path FROM item UNION ALL SELECT path FROM affix'):
        txt = I.read_rel(p) or ''
        if not re.search(r'^itemSkillName=', txt, re.M):
            continue
        # any level serves: the rules are about shape, not numbers
        lines = [l for l in I.resolve_item_skill(txt, 50) if l]
        desc = description(txt)
        with_desc += bool(desc and lines)
        n += check(p, lines, desc, bad)
    for (p,) in conn.execute('SELECT DISTINCT set_path FROM item WHERE set_path IS NOT NULL'):
        _, after = L.set_block(SB.rec(p) or {})
        at = next((i for i, l in enumerate(after) if l.startswith('Grants: ')), None)
        if at is not None:
            srec = I.read_rel(p) or ''
            n += check(p, after[at:], description(srec), bad)
    print(f'{n} granted-skill blocks, {with_desc} with a description')
    assert n > 1000 and with_desc, 'too few blocks -- the gate would pass on nothing'
    if bad:
        print('\nFAIL')
        for b in bad[:20]:
            print('  ', b)
        print(f'  ({len(bad)} in all)')
        raise SystemExit(1)
    print('OK')


if __name__ == '__main__':
    main()
