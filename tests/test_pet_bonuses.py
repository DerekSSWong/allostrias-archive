"""The pet bucket: three channels, the rank fold, and staying out of the
player's sheet.

The Pet Bonuses tab lists BONUSES GRANTED TO PETS, never a pet's totals. That
is what makes them summable -- a pet's base stats live on its own creature
record and differ per pet -- and it is why they live in a second bucket that
must never reach the player's contributions.

⚠️ THE FOLD INDEX IS THE TRAP. Gear bonuses and rank-1 devotion nodes both fold
at index 0, so a character built only of those passes whether the code folds at
the rank or not. GD Lens found this by reintroducing the bug and watching every
gate stay green. This derives the difference from the records instead of
trusting the sample, and prints which case the frozen set is in.
"""
import collections
import json
import os
import sqlite3
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from allostrias import settings as S                  # noqa: E402
from allostrias.sheet import build                    # noqa: E402

cfg = S.load()
BUNDLE = os.path.join(S.ROOT, 'cache', 'sheet', 'sheet.json')
if not os.path.isfile(BUNDLE):
    print('SKIPPED -- no sheet bundle; run `python3 -m allostrias.sheet.build`.')
    raise SystemExit(0)
b = json.load(open(BUNDLE))
chars = b['characters']
pet_section = [s for s in b['sheet'] if s[0] == 'Pet Bonuses']
assert pet_section, 'the sheet has no Pet Bonuses section'
sec_name, pet_rows, bucket = (list(pet_section[0]) + [''])[:3]
assert bucket == 'pet', f'the pet section ships bucket={bucket!r}, so the page '\
                        'will read the player contributions for it'

uncovered = []

# -- 1. the three channels ------------------------------------------------
kinds = collections.Counter(r[3] for c in chars
                            for rows in (c.get('petContrib') or {}).values()
                            for r in rows)
print(f'pet sources by kind: {dict(kinds)}')
gear = sum(v for k, v in kinds.items()
           if k in ('base', 'prefix', 'suffix', 'component', 'augment',
                    'completion bonus', 'crafting bonus', 'transmuted'))
assert gear, 'no gear-channel pet source at all'
assert kinds['skill'], 'no bought-skill/devotion pet source at all'
if not kinds['item skill']:
    uncovered.append('no worn item GRANTS a skill carrying petBonusName, so '
                     'channel 2 -- the one that is in neither the gear walk '
                     'nor the save\'s skill list -- runs in no gate')
print(f'  gear {gear}, bought skill {kinds["skill"]}, '
      f'item-granted skill {kinds["item skill"]}')

# -- 2. the fold index, derived ------------------------------------------
# A per-rank petbonus record read at the wrong index returns a plausible number.
# So: find a skill-channel source whose target record HAS a per-rank array and
# whose rank is above 1, and require the shipped value to be the one at that
# rank rather than the one at index 0.
pr = sqlite3.connect(os.path.join(S.ROOT, 'cache', 'profile.sqlite'))
pr.row_factory = sqlite3.Row
checked = 0
for ch in chars:
    inv = {r['skill_path']: r['level'] for r in pr.execute(
        'select skill_path, level from character_skill '
        'where dir_name=? and level>0', (ch['dir'],))}
    eff = {s['path']: s['eff'] for s in ch['skills']}
    for path, _lvl in inv.items():
        target = build.pet_target(path)
        if not target:
            continue
        rank = eff.get(path, 1)
        d = build.rec(target) or {}
        for field, vals in d.items():
            if len(vals) < 2 or rank < 2:
                continue
            try:
                arr = [float(v) for v in vals]
            except ValueError:
                continue
            at_rank = arr[min(rank - 1, len(arr) - 1)]
            if at_rank == arr[0]:
                continue                     # the two readings agree; no proof
            shipped = [r[0] for r in (ch.get('petContrib') or {}).get(field, [])]
            assert at_rank in shipped, (
                f'{ch["name"]}: {path} at rank {rank} should contribute '
                f'{at_rank} to {field} (index 0 would be {arr[0]}), '
                f'shipped {shipped}')
            checked += 1
if checked:
    print(f'  rank fold proved on {checked} per-rank source(s) whose value at '
          f'rank differs from index 0')
else:
    uncovered.append('no always-on pet skill is above rank 1 with a per-rank '
                     'array, so folding at index 0 unconditionally would pass '
                     'every assertion here')

# -- 3. the two buckets are read from different records -------------------
# ⚠️ NEITHER THE LABEL NOR THE VALUE CAN TELL THEM APART. A devotion node
# grants a stat to the player AND the same stat to pets from two DIFFERENT
# records -- and the two records can carry the SAME NUMBER. Ulo the Keeper of
# the Waters gives +15 Petrify Resist to both, which an earlier version of this
# assertion reported as the pet bonus being the player's stat copied. So the
# check is structural: every pet contribution names the petbonus record it was
# read from, and no player contribution may name one.
vias = set()
for ch in chars:
    for f, rows in (ch.get('petContrib') or {}).items():
        for row in rows:
            assert len(row) == 5, (
                f'{ch["name"]}: a pet contribution to {f} carries no `via`, so '
                f'nothing can prove it came from a petbonus record')
            via = row[4]
            vias.add(via)
            d = build.rec(via) or {}
            tpl = (d.get('templateName') or [''])[0].lower()
            assert tpl.endswith('petbonus.tpl'), (
                f'{ch["name"]}: pet {f} was read from {via}, whose template is '
                f'{tpl!r} -- that is not a pet bonus record')
    for f, rows in ch['contrib'].items():
        for row in rows:
            assert len(row) < 5 or row[4] not in vias, (
                f'{ch["name"]}: the player\'s {f} was read from {row[4]}, a '
                f'petbonus record -- the buckets have merged')
print(f'  {len(vias)} distinct petbonus records feed the tab, none of them the '
      f'player\'s sheet')

# -- 4. the cap belongs to the page, not to the build ---------------------
# The build ships raw sums; the page applies the 80 ceiling. If the build
# capped them, the contribution list would no longer add up to what it shows.
caps = [r for r in pet_rows if r.get('cap')]
assert caps, 'no pet row declares a cap; the 80 resist ceiling is not modelled'
over = 0
for ch in chars:
    P = ch.get('petContrib') or {}
    for r in caps:
        total = sum(v[0] for f in r['f'] for v in P.get(f, []))
        if total > r['cap']:
            over += 1
if over:
    print(f'  {over} row(s) sum above their cap, so the page ceiling is exercised')
else:
    uncovered.append('no pet resist row sums above 80, so the cap the page '
                     'applies is never reached and could be deleted unnoticed')

# -- 5. the excluded channel stays excluded -------------------------------
# SkillSecondary_PetModifier, reached by petSkillName, buffs ONE pet type. The
# game keeps it on the skill; folding it in would put a skeleton-only number on
# a row that says "all pets".
leaked = []
for ch in chars:
    for path in {s['path'] for s in ch['skills']}:
        d = build.rec(path) or {}
        nxt = (d.get('petSkillName') or [None])[0]
        if not nxt:
            continue
        mod = build.rec(nxt) or {}
        for f, vals in mod.items():
            if not build.wanted(f):
                continue
            try:
                v = float(vals[0])
            except (ValueError, IndexError):
                continue
            if v and any(r[0] == v and r[3] == 'skill'
                         for r in (ch.get('petContrib') or {}).get(f, [])):
                leaked.append(f'{ch["name"]}: {nxt} {f}={v}')
assert not leaked, f'petSkillName targets reached the tab: {leaked[:3]}'
print('  petSkillName (one pet type only) stays out')

# -- 6. who the bonuses are FOR, which is the whole verdict ---------------
# ⚠️ A SUMMON IS NOT A PET. `Class=Pet` scales off this tab; `PetPlayerScaling`
# inherits the PLAYER's stats and takes nothing from it. Both spawn from a
# skill and both look identical to any structural test, so the build reads the
# game's own class declaration ([[structural-proxy-is-not-evidence]]) and this
# derives the same answer from the records rather than trusting the list it
# shipped -- a `vctx.pets` copied out of thin air would match itself.
scaling = []
for ch in chars:
    want_pets, has_scaling = set(), []
    for sk in ch['skills']:
        if sk['eff'] <= 0:
            continue
        for target in (build.rec(sk['path']) or {}).get('spawnObjects') or []:
            cls = ((build.rec(target) or {}).get('Class') or [''])[0]
            if cls == 'Pet':
                want_pets.add(sk['n'])
            elif cls == 'PetPlayerScaling':
                has_scaling.append(sk['n'])
    got = set(ch['vctx'].get('pets') or [])
    assert got == want_pets, (
        f'{ch["name"]}: ships pets={sorted(got)}, the records say '
        f'{sorted(want_pets)}')
    if has_scaling and not want_pets:
        scaling.append((ch['name'], sorted(set(has_scaling))))
    print(f'  {ch["name"]:<12} {len(want_pets)} real pet skill(s), '
          f'{len(set(has_scaling))} player-scaling summon(s)')
if scaling:
    n, what = scaling[0]
    print(f'  the trap is live: {n} fields {", ".join(what)} and no real pet, '
          f'so a "has spawnObjects" test would grant '
          f'{len(pet_rows)} rows of advice nothing can spend')
else:
    uncovered.append('no character summons something player-scaling without '
                     'also having a real pet, so "not every summon is a pet" '
                     'is asserted against nothing here')

# ...and the tab is judged, which needs both a rule on the row and a threshold
# to read. Either half missing leaves 24 rows rendering a mark nothing decided.
assert all(r.get('rule') == 'pet' for r in pet_rows), (
    'the pet rows are not stamped with the pet rule: '
    f'{sorted({r.get("rule") for r in pet_rows})}')
assert build.TARGETS.get('petBuildDamage'), 'no pet-build threshold is shipped'

if uncovered:
    print('\nUNCOVERED (no frozen character exercises these)')
    for u in uncovered:
        print(f' - {u}')
print('\nPET BONUSES OK')
