"""Step 8b gate: monster identity on the holders that drop things.

The failure guarded against is a monster that holds an item but resolves to no
NAME. It does not error -- it looks exactly like a chest to anything asking
"who drops this" -- so the item silently loses its source.

The check DERIVES the difference between the two causes rather than pinning a
count, because only one of them is a bug:

  * a tag the text files define SOMEWHERE but that did not resolve means a
    file group was left out of the lookup. Upstream hit exactly this: the
    endlessdungeon tag files were omitted from a curated map, taking every
    Shattered Realm boss's name with them, plus six hostile NPCs whose display
    text lives in storyelements. This must be ZERO.
  * a tag defined in NO text file is a leftover dev record with no name to
    find. Not fixable here, and not this module's problem.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from allostrias import settings as S               # noqa: E402
from allostrias.archive import arc as C            # noqa: E402
from allostrias.db import catalogue                # noqa: E402

cfg = S.load()
conn = catalogue.connect(cfg.catalogue_db, create=False)
one = lambda sql, *a: conn.execute(sql, a).fetchone()[0]

# -- 1. classification, the axis the farm ranking weights by ---------------
kinds = dict(conn.execute(
    "SELECT coalesce(classification,'(none)'), count(*) FROM holder "
    "WHERE is_monster=1 GROUP BY 1 ORDER BY 2 DESC"))
print(f'monster holders by classification: {kinds}')
for expected in ('Hero', 'Champion', 'Common', 'Boss', 'SuperBoss'):
    assert kinds.get(expected, 0) > 0, f'no {expected} monsters'

levelled = one('SELECT count(*) FROM holder WHERE is_monster=1 '
               'AND min_level IS NOT NULL AND max_level IS NOT NULL')
print(f'  {levelled} of {one("SELECT count(*) FROM holder WHERE is_monster=1")} '
      'carry a level range')
assert levelled > 2000, levelled

# -- 2. every tag the game defines must have resolved ---------------------
defined = set(C.load_tags(cfg.text_arc_paths))
for path in cfg.text_arc_paths:
    with C.Arc(path) as archive:
        for _name, text in archive.iter_text_files(skip_console=False):
            defined.update(tag for tag, _v in C.parse_tag_lines(text))

unnamed = conn.execute(
    'SELECT path, name_tag FROM holder WHERE is_monster=1 '
    'AND name_tag IS NOT NULL AND name IS NULL').fetchall()
wiring = [r for r in unnamed if r['name_tag'] in defined]
leftover = [r for r in unnamed if r['name_tag'] not in defined]
print(f'\n{len(unnamed)} monster holders with a tag but no name:')
print(f'  {len(wiring)} whose tag IS defined somewhere  <- must be 0')
print(f'  {len(leftover)} whose tag is defined nowhere  <- dev leftovers')
for row in leftover[:3]:
    print(f'     {row["name_tag"]}')
assert not wiring, (
    f'{len(wiring)} monsters lost a name that the text files DO define: '
    f'{[r["name_tag"] for r in wiring[:5]]} -- a tag file group is missing '
    'from the lookup')

# -- 3. the worked example -------------------------------------------------
print('\nGargoyle Girdle droppers, with rarity and level range:')
for row in conn.execute("""
        SELECT DISTINCT h.name, h.classification, h.min_level, h.max_level
        FROM item_drop d JOIN item i ON i.id=d.item_id
        JOIN holder h ON h.id=d.holder_id
        WHERE i.path='records/items/gearaccessories/waist/b201f_waist.dbr'
          AND h.is_monster=1 AND h.name IS NOT NULL
        ORDER BY h.classification, h.name"""):
    print(f"  {row['name']:24} {row['classification'] or '-':10} "
          f"lvl {row['min_level']}-{row['max_level']}")

hero = one("""SELECT count(*) FROM item_drop d JOIN item i ON i.id=d.item_id
    JOIN holder h ON h.id=d.holder_id
    WHERE i.path='records/items/gearaccessories/waist/b201f_waist.dbr'
      AND h.classification='Hero'""")
assert hero > 0, 'no Hero-class dropper; classification did not attach'

conn.close()
print('\nSTEP 8b PASS')
