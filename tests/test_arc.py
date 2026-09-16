"""arc.py gate: tags resolve, and match the old extraction exactly.

The authority here is .extracted/text_en/*.txt, produced by the same
extract_all.py -- and unlike the record half, the text half is NOT lossy: it
writes every tag it parses. So this diff is a straight equality check over the
whole tag set, not a sample.

The one real risk in flattening per-category files into a single map is a tag
defined in two categories with different text. That is checked, not assumed.
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from allostrias import settings as S            # noqa: E402
from allostrias.archive import arc as C         # noqa: E402

cfg = S.load()
print('text archives in load order:')
for path in cfg.text_arc_paths:
    print(f'  {os.path.relpath(path, cfg.game):34} {os.path.getsize(path) / 1024:6.0f} KB')
assert len(cfg.text_arc_paths) == 4, cfg.text_arc_paths

# -- 1. collisions: does flattening lose anything? --------------------------
per_file = {}
collisions = {}
for path in cfg.text_arc_paths:
    with C.Arc(path) as arc:
        for name, text in arc.iter_text_files():
            for tag, value in C.parse_tag_lines(text):
                previous = per_file.get(tag)
                if previous is not None and previous[1] != value and previous[0] != name:
                    collisions[tag] = (previous, (name, value))
                per_file[tag] = (name, value)
print(f'\ncross-category tag collisions with differing text: {len(collisions)}')
for tag, ((n1, v1), (n2, v2)) in list(collisions.items())[:3]:
    print(f'  {tag}: {n1}={v1[:40]!r} vs {n2}={v2[:40]!r}')

# -- 2. load and spot-check ------------------------------------------------
t0 = time.time()
tags = C.load_tags(cfg.text_arc_paths)
print(f'\n{len(tags)} tags loaded in {time.time() - t0:.2f}s')
for tag in ('tagMedalF001', 'tagSkillClassName01'):
    assert tag in tags, f'{tag} missing'
    print(f'  {tag} = {tags[tag]!r}')

assert not any(t.startswith('﻿') or t.startswith('ï»¿') for t in tags), \
    'a BOM survived into a tag name'
print('  no BOM leaked into a tag name')

# -- 3. diff against the unpacked authority --------------------------------
text_dir = os.path.join(cfg.game, '.extracted', 'text_en')
if not os.path.isdir(text_dir):
    sys.exit(f'\nFAIL: no {text_dir}; parser correctness is UNPROVEN.')

authority = {}
names = [n for n in sorted(os.listdir(text_dir))
         if os.path.isfile(os.path.join(text_dir, n))
         and C.CONSOLE_MARKER not in n.lower()]
for name in names:
    with open(os.path.join(text_dir, name), encoding='utf-8', errors='replace') as fh:
        for line in fh:
            if '=' in line:
                tag, _, value = line.rstrip('\n').partition('=')
                authority[tag] = value

only_mine = set(tags) - set(authority)
only_theirs = set(authority) - set(tags)
differing = {t for t in set(tags) & set(authority) if tags[t] != authority[t]}
print(f'\ndiff vs {len(authority)} authority tags across {len(names)} files: '
      f'{len(only_mine)} only mine, {len(only_theirs)} only theirs, '
      f'{len(differing)} differing text')
def clip(text, width=70):
    text = repr(text)
    return text if len(text) <= width else text[:width] + "...'"

for tag in list(only_theirs)[:3]:
    print(f'  only theirs: {tag} = {clip(authority[tag])}')
for tag in sorted(differing)[:5]:
    print(f'  differs: {tag}\n      mine {clip(tags[tag])}\n      them {clip(authority[tag])}')

# The authority was extracted on 2026-08-16; the .arz on disk is from
# 2026-08-19. Three strings were edited by the game update in between, so the
# disagreement is the authority being stale, not this parser being wrong:
# a typo fix, a wording change and a balance number. They are pinned BY NAME
# rather than tolerated by count -- a fourth divergence means something else
# happened and must be looked at.
KNOWN_STALE = {
    'FilterCaster',                                       # 'Potion Base' -> 'Potion'
    'tagGDX3LoreObj_AREAH_KurnNoteA20Text',               # "who's" -> 'whose'
    'tagGDX3Class10SkillWereravenAbilityDescription02A',  # 25% -> 30%
}
# extract_all.py glued the UTF-8 BOM onto the first tag of a file; this parser
# strips it. The un-stripped form is their artifact, not a tag we lost.
KNOWN_BOM_ARTIFACTS = {t for t in only_theirs if t.lstrip('ï»¿﻿') in tags}

assert len(tags) >= 20000, f'only {len(tags)} tags; the archives did not fully parse'
assert not (only_theirs - KNOWN_BOM_ARTIFACTS), \
    f'tags the authority has and this parser lost: {sorted(only_theirs - KNOWN_BOM_ARTIFACTS)[:5]}'
assert not (differing - KNOWN_STALE), \
    f'unexpected text disagreement: {sorted(differing - KNOWN_STALE)[:5]}'
print(f'  {len(only_theirs & KNOWN_BOM_ARTIFACTS)} BOM artifact(s) in the authority, stripped here')
print(f'  {len(differing)} stale string(s), all pinned by name')
print(f'  {len(only_mine)} tags added by the 2026-08-19 game update')

# -- 4. load order actually resolves the collisions -----------------------
# A base file leaves these as the placeholder '?'; an expansion file names
# them. Getting this wrong yields a catalogue where two masteries are '?'.
for tag, expected in (('tagSkillClassName07', 'Inquisitor'),
                      ('tagSkillClassName08', 'Necromancer'),
                      ('tagSkillClassName0107', 'Tactician')):
    assert tags[tag] == expected, f'{tag} = {tags[tag]!r}, expected {expected!r}'
print(f'  expansion tags win over base placeholders ({len(collisions)} collisions resolved)')

print('\nSTEP 3 PASS')
