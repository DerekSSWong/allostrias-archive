"""The character-independent half of the loot filter, shipped to the page.

PORTED FROM GD Lens's raynbow.py. The filter is a `text_en` localisation
override, not a code mod: every line is `tag={^X}<name>{^-}`, and the game
repaints the name. Two kinds of line, and only one is a grade:

  affixes   all 481 named prefix and suffix tags, coloured by this character's
            grade -- the page decides that, since it moves with every verdict
  bases     every item base, style and quality tag on droppable gear, coloured
            by its own tier -- here to CLOSE the affix's colour, never graded

⚠️ THE OUTPUT IS CHARACTER-SPECIFIC AND ONLY THE HEADER CAN SAY SO. A grade is
what one character wants; two players sharing a file would be reading each
other's priorities. The header names whose it is.
"""
import collections

from .. import item_stats as I

# ⚠️ THE NAME IS THE INSTALL PATH: the game loads whatever sits at
# settings/text_en/tagsgdx3_uimain.txt, and renamed it is inert.
FILENAME = 'tagsgdx3_uimain.txt'
# CRLF, because a Windows game reads it and every text_en file it ships uses it.
EOL = '\r\n'
# ⚠️ EVERY LINE ENDS WITH THIS. A `{^X}` code colours everything after it until
# something clears it, and an item's name is five concatenated tags: an
# unclosed prefix colour ran straight through the item base.
RESET = '{^-}'
CHARACTER_MARK = '%CHARACTER%'

# The game's own `{^X}` codes, copied from gd-lib's palette.py (the gate diffs
# them). Only the five CONFIRMED -- matched to a record's itemClassification by
# our own join -- are the rarity ramp; Silver rests on the selector alone.
PALETTE = {
    'A': ('Aqua', '#80FFD5'),            'B': ('Blue', '#39ABCF'),
    'C': ('Cyan', '#00FFFF'),            'D': ('Dark Gray', '#191919'),
    'E': ('Brown', '#49392A'),           'F': ('Fuchsia', '#FF69B5'),
    'G': ('Green', '#10EB5D'),           'H': ('Grayish Orange', '#C7BAA9'),
    'I': ('Indigo', '#5A039A'),          'K': ('Khaki', '#F1E78C'),
    'L': ('Olive', '#92CC00'),           'M': ('Maroon', '#800000'),
    'O': ('Orange', '#F3A44D'),          'P': ('Purple', '#BD94C6'),
    'Q': ('Grayish Magenta', '#B5A8B9'), 'R': ('Red', '#FF4200'),
    'S': ('Silver', '#9A9A9A'),          'T': ('Teal', '#00FFD2'),
    'W': ('White', '#FFFFFF'),           'X': ('Dark Green', '#38592E'),
    'Y': ('Yellow', '#FFF62C'),          'Z': ('Cobalt', '#6A91E0'),
}
CONFIRMED = ('W', 'Y', 'G', 'B', 'I')
TIER_ORDER = ('Common', 'Magical', 'Rare', 'Epic', 'Legendary')
TIER_COLOUR = dict(zip(TIER_ORDER, CONFIRMED))

# `status: ASSERTED` · `source: chosen by the user on 2026-09-02 for GD Lens.`
# The game's own rarity ramp, so an S lights up the way a legendary does.
# ⚠️ Keys are GRADE letters, values PALETTE codes: 'B' and 'S' are on both
# sides meaning different things, and every one is correct.
GRADE_COLOUR = {'F': 'W', 'C': 'Y', 'B': 'G', 'A': 'B', 'S': 'I'}
# An affix carrying nothing this character wants. Not F's White: F means
# "carries something you want, barely", and one colour cannot say both.
UNGRADED_COLOUR = 'S'


def affix_names(conn):
    """tag -> display name for every named prefix and suffix, droppable or not:
    one that helps nobody still belongs in the file, coloured as ungraded."""
    out = {}
    for tag, name in conn.execute(
            "SELECT DISTINCT name_tag, name FROM affix "
            "WHERE kind IN ('Prefix', 'Suffix') AND name IS NOT NULL"):
        if out.setdefault(tag, name) != name:
            raise ValueError(f'{tag} resolves to two names')
    return out


def base_names(conn):
    """tag -> (display name, colour code) for item bases, styles and qualities.

    The gear tree minus relics (a relic name is never composed with an affix),
    each tag coloured by the tier of the record carrying it.

    ⚠️ ONE TAG CAN SPAN TIERS, AND THE STRONGEST THAT CAN *DROP* WINS. An
    Awakened Legendary carries the SAME name tag as the Epic it upgrades and is
    only ever crafted, so best-of-outright painted a droppable Epic Indigo.
    "Can drop" is the archive's own drop graph: an item_drop row. A tag with no
    droppable record keeps its strongest tier -- "we found no drop" must never
    pass itself off as "there is no drop".

    A tag with no display name is SKIPPED: a line we cannot name is a line we
    cannot write."""
    quality = dict(conn.execute(
        "SELECT item_id, txt FROM item_stat WHERE field='itemQualityTag' AND idx=0"))
    droppable = {r[0] for r in conn.execute('SELECT DISTINCT item_id FROM item_drop')}
    tiers, dropped = collections.defaultdict(set), collections.defaultdict(set)
    for item_id, path, name_tag, style_tag, cls in conn.execute(
            'SELECT id, path, name_tag, style_tag, classification FROM item '
            'WHERE classification IN (%s)' % ','.join('?' * len(TIER_ORDER)), TIER_ORDER):
        folder = path.rsplit('/', 1)[0]
        if '/gear' not in folder or 'gearrelic' in folder:
            continue
        for tag in (name_tag, style_tag, quality.get(item_id)):
            if tag:
                tiers[tag].add(cls)
                if item_id in droppable:
                    dropped[tag].add(cls)
    out = {}
    for tag, seen in tiers.items():
        name = I.ITEM_TAGS.get(tag)
        if name:
            out[tag] = (name, TIER_COLOUR[max(dropped.get(tag) or seen, key=TIER_ORDER.index)])
    return out


def header():
    """The comment block, with CHARACTER_MARK for the page to fill in."""
    order = ['F', 'C', 'B', 'A', 'S']
    legend = ['#   {^%s} %-16s %s' % (GRADE_COLOUR[g], PALETTE[GRADE_COLOUR[g]][0],
                                      'grade ' + g) for g in reversed(order)]
    legend.append('#   {^%s} %-16s %s' % (UNGRADED_COLOUR, PALETTE[UNGRADED_COLOUR][0],
                                          'nothing this character wants'))
    return ['# ##############################',
            "# ### Allostria's Archive loot filter",
            '# ##############################',
            '#',
            '# Character: ' + CHARACTER_MARK,
            '#',
            '# Every affix name below is coloured by what it is worth TO THIS',
            '# CHARACTER, not by its rarity. It is not meaningful for anyone else.',
            '#',
            ] + legend + [
            '#',
            '# A text_en override, not a mod. Install to either:',
            '#   <Grim Dawn>/settings/text_en/' + FILENAME,
            '#   <Documents>/My Games/Grim Dawn/Settings/text_en/' + FILENAME,
            '#',
            '# Affix names carry the grade. Item, style and quality names carry',
            '# their own rarity, so they read the same on the ground and in the',
            '# tooltip; they are not graded.',
            '#', '']


def build(conn):
    names, bases = affix_names(conn), base_names(conn)
    clash = sorted(set(names) & set(bases))
    if clash:
        raise ValueError(f'{len(clash)} tags are both an affix and an item base: {clash[:3]}')
    lines = list(names.values()) + [n for n, _ in bases.values()] + header()
    bad = [l for l in lines if not l.isascii()]
    if bad:
        # The page sorts tags by UTF-16 code unit and writes the file as-is; a
        # non-ASCII name would need an encoding decision nobody has made.
        raise ValueError(f'non-ASCII filter text: {bad[:3]}')
    return {'filename': FILENAME, 'eol': EOL, 'reset': RESET, 'mark': CHARACTER_MARK,
            'header': header(), 'names': names,
            'bases': {t: list(v) for t, v in bases.items()},
            'gradeColour': GRADE_COLOUR, 'ungraded': UNGRADED_COLOUR}
