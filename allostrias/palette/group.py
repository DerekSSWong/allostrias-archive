"""Collapse UI texture filenames into design ELEMENTS.

A palette that lists 4,139 files is a file listing, not a palette. The names
already carry the structure: Crate ships a button as four files, a frame as
eight, an icon family as a numbered run. Recovering those groups is what turns
the listing into something a designer can point at.

Order is load-bearing. `-msk` is stripped first because a mask carries its own
state suffix underneath it; the state suffix is taken before the numeric run
because `skills_tab1up` ends in neither a clean state nor a clean number until
the other has been removed.
"""
import re
from collections import defaultdict

# Button/control states, longest first so `upfocus` is not eaten by `up`.
STATES = ('disabled', 'upfocus', 'hidden', 'focus', 'over', 'down', 'up')
NINE = ('lt', 'ct', 'rt', 'lm', 'rm', 'lb', 'cb', 'rb')

# The SECOND 9-slice vocabulary. `generic/` spells the same eight pieces out in
# words instead of mainmenu's two-letter codes, and those are the frames worth
# reaching for, so the palette has to recognise both. Longest first: `borderleft`
# must not swallow the separate `borderleft3px` family.
CORNERS = ('cornerbottomleft', 'cornerbottomright', 'cornerupperleft', 'cornerupperright',
           'cornerleftbottom', 'cornerlefttop', 'cornerrightbottom', 'cornerrighttop')
EDGES = ('edgebottom', 'edgeleft', 'edgeright', 'edgetop',
         'borderbottom', 'borderleft', 'borderright', 'bordertop')
WORDY = tuple(sorted(CORNERS + EDGES + ('filler',), key=len, reverse=True))

_state_re = re.compile(r'^(?P<stem>.*?)[_-]?(?P<state>' + '|'.join(STATES) + r')$')
_nine_re = re.compile(r'^(?P<stem>.*)_(?P<part>' + '|'.join(NINE) + r')$')
_num_re = re.compile(r'^(?P<stem>.*?)(?P<num>\d+)$')
_wordy_re = re.compile(r'^(?P<stem>.*?)(?P<part>' + '|'.join(WORDY) + r')$')


def classify(path):
    """(kind, group key, member label) for one texture path.

    `kind` is what the group IS, and it decides how the palette draws it: a
    `state` group is one control shown in its rest state, a `nine` group is a
    frame that must be assembled before it means anything, a `series` is a set
    meant to be seen together.
    """
    stem, _, _ext = path.rpartition('.')
    mask = stem.endswith('-msk')
    if mask:
        stem = stem[:-4]

    m = _nine_re.match(stem)
    if m and m.group('part') in NINE:
        return 'nine', m.group('stem'), m.group('part'), mask

    m = _wordy_re.match(stem)
    if m and m.group('stem'):
        return 'nine', m.group('stem'), m.group('part'), mask

    m = _state_re.match(stem)
    if m and m.group('stem'):
        return 'state', m.group('stem'), m.group('state'), mask

    m = _num_re.match(stem)
    if m and m.group('stem'):
        return 'series', m.group('stem'), m.group('num'), mask

    return 'one', stem, '', mask


def group(paths):
    """Grouped, with singleton `series` demoted back to `one`.

    A numeric suffix only means "one of a set" when a set exists; `resistance01`
    alone is just a name that happens to end in a digit, and promoting it would
    invent a family of one.
    """
    buckets = defaultdict(list)
    for p in paths:
        kind, key, label, mask = classify(p)
        buckets[(kind, key)].append((p, label, mask))

    # A suffix only means what it looks like when the group it implies actually
    # exists. `achievementgroup.tex` ends in "up" and is one texture, not a
    # button's rest state; `resistance01` ends in a number and is not a run of
    # one. Every kind therefore has a floor, and a group under it is demoted to
    # a plain texture rather than being allowed to invent a family.
    FLOOR = {'state': 2, 'nine': 4, 'series': 3}
    out = []
    for (kind, key), members in buckets.items():
        # A wordy 'nine' must show a corner AND an edge before it is a frame --
        # the vocabulary alone would also collect `genericbox_bevelleft` and
        # friends into a frame that cannot be assembled.
        if kind == 'nine' and any(m[1] in WORDY for m in members):
            labs = {m[1] for m in members}
            if not (labs & set(CORNERS) and labs & set(EDGES)):
                kind = 'one'
        if len(members) < FLOOR.get(kind, 1):
            for p, label, mask in members:
                out.append({'kind': 'one', 'key': p.rpartition('.')[0],
                            'members': [(p, '', mask)]})
            continue
        order = {**{s_: i for i, s_ in enumerate(STATES)},
                 **{n_: i for i, n_ in enumerate(NINE)},
                 **{w_: i for i, w_ in enumerate(WORDY)}}
        members.sort(key=lambda m: (order.get(m[1], 99), m[0]))
        out.append({'kind': kind, 'key': key, 'members': members})
    out.sort(key=lambda g: g['key'])
    return out
