"""When a granted skill fires, in the game's own words.

ONE vocabulary, shared by every surface that prints it: all four GD Catalogue
tabs (via build_catalogue), GD Lens and the Transfer Stash. The concept used to live in three hand-written tables that disagreed -- a seven-entry one for granted skills, a two-entry one for
refresh/cooldown lines whose gaps printed raw field names like "Chance on OnKill"
on published cards, and a twelve-entry one in the stash.

WHAT IS SHARED IS THE FACT, NOT THE LAYOUT. This returns a phrase and nothing
else. The catalogue puts it on its own "{skill}: ..." line, because its cards
group a skill's lines by matching the text after "Grants: " verbatim and
appending there would break that grouping; the stash appends it to the skill's
name in parentheses, because that is where the game itself puts it. Both are
right, and neither belongs here.

Callers pass their own tag map rather than this module loading one: the two repos
already build byte-identical maps from the same files, and a third loader is the
kind of duplication this module exists to remove.

THE STRINGS ARE THE GAME'S. `tagAutoSkillCondition01`-`12` in tags_items.txt, and
`tagRefreshSkillCondition01`-`12` in tagsgdx3_ui.txt, which say the same twelve
things in the same words once parentheses and colour codes are stripped --
asserted below rather than assumed, since it is the reason one table can serve
both families.

WHAT PAIRS EACH TAG WITH ITS triggerType IS THE TAG'S OWN WORDING, not its number
and NOT the template's picklist, whose order (OnEquip;OnKill;LowHealth;...) from
database/templates.arc disagrees with the numbering outright. Four pairings are
further confirmed against real in-game tooltips captured by Item Assistant:
AttackEnemy, AttackEnemyCrit, OnKill and Block. `.gdstash`'s build re-checks those
four every run and names the eight that rest on the tag text alone.

`CastDebuf` is in the picklist and has no tag and no record. It is left unmapped
on purpose: an unmapped trigger must raise rather than borrow a neighbour's words.

PORTED FROM gd-lib's skill_triggers.py, not imported: allostrias must build on
an install where gd-lib has never run. Only `import re`, so the port is the
file. tests/test_item_stats.py diffs it against the original wherever the
original is present.
"""
import re

AUTO_TAG = 'tagAutoSkillCondition%02d'
REFRESH_TAG = 'tagRefreshSkillCondition%02d'

# triggerType -> which of the twelve conditions it is.
TRIGGER_CONDITION = {
    'LowHealth': 1,        # {}% Chance at {}% Health
    'LowMana': 2,          # {}% Chance at {}% Energy
    'HitByEnemy': 3,       # when Hit
    'HitByMelee': 4,       # when Hit by Melee Attacks
    'HitByProjectile': 5,  # when Hit by Ranged Attacks
    'CastBuff': 6,         # when a Buff is Cast
    'AttackEnemy': 7,      # on Attack
    'OnEquip': 8,          # Active while Equipped
    'HitByCrit': 9,        # when Hit by a Critical
    'AttackEnemyCrit': 10,  # on Critical Attack
    'Block': 11,           # on Block
    'OnKill': 12,          # on Enemy Death
}

# The two triggers whose condition names a THRESHOLD as well as a chance. Their
# tag has a second placeholder; every other tag has one.
THRESHOLD_TRIGGERS = ('LowHealth', 'LowMana')

_SLOT_RE = re.compile(r'\{%(?:\.(\d+))?([dfs])(\d)\}')
_COLOUR_RE = re.compile(r'\{\^.\}')


def format_tag(text, args):
    """Fill a Grim Dawn format tag: {%d0} is arg 0 as an integer, {%.0f1} is arg 1
    to 0 decimals.

    Raises on a token it does not know rather than leaving it on screen or
    dropping it: the tag files are data nobody here controls, and a half-filled
    string reads exactly like a finished one.
    """
    def sub(m):
        places, kind, idx = m.group(1), m.group(2), int(m.group(3))
        if idx >= len(args):
            raise ValueError(f'tag {text!r} wants argument {idx}, given {args}')
        v = args[idx]
        if kind == 'd':
            return str(int(float(v)))
        if kind == 'f':
            return f'{float(v):.{int(places or 0)}f}'
        return str(v)
    out = _SLOT_RE.sub(sub, text)
    left = re.search(r'\{[^}]*\}', out)
    if left:
        raise ValueError(f'tag {text!r} left {left.group(0)} unsubstituted')
    return out


def _phrase_template(tags, n):
    """One condition's wording, stripped of the parentheses and colour codes that
    are presentation rather than vocabulary."""
    text = tags.get(AUTO_TAG % n)
    if not text:
        raise ValueError(f'{AUTO_TAG % n} is not in the extracted text files')
    return _COLOUR_RE.sub('', text).strip('()').replace('  ', ' ').strip()


def condition_phrase(tags, trigger, chance, param=None):
    """"15% Chance on Attack", "100% Chance at 50% Health".

    No parentheses and no leading skill name: those are the caller's business.
    Raises rather than guessing -- an unmapped trigger, a threshold trigger with
    no threshold, and an UNSET picklist field (which stores the whole list of
    choices, as 861 records in this database do) each mean the data cannot say
    when this fires, and a plausible sentence about that is worse than none.
    """
    if ';' in str(trigger):
        raise ValueError(f'triggerType {trigger!r} is the whole picklist, so it '
                         f'is unset and nothing says when this fires')
    if trigger not in TRIGGER_CONDITION:
        raise ValueError(f'triggerType {trigger!r} has no condition string')
    args = [first_value(chance)]
    if trigger in THRESHOLD_TRIGGERS:
        if param is None:
            raise ValueError(f'{trigger} fires at a threshold and none was given, '
                             f'so the level it fires at is unknown')
        args.append(first_value(param))
    return format_tag(_phrase_template(tags, TRIGGER_CONDITION[trigger]), args)


def first_value(value):
    """A DBR numeric field, which may be a ';'-separated per-level list."""
    return str(value).split(';')[0].strip()


CHANCE_RE = re.compile(r'^chanceToRun=([\d.;\s]+)', re.M)
TRIGGER_RE = re.compile(r'^triggerType=(\S+)', re.M)
PARAM_RE = re.compile(r'^triggerParam=([\d.]+)', re.M)


def controller_phrase(tags, ctrl_txt):
    """The condition an auto-cast controller record describes."""
    trigger, chance = TRIGGER_RE.search(ctrl_txt), CHANCE_RE.search(ctrl_txt)
    if not trigger or not chance:
        raise ValueError('controller record has no triggerType/chanceToRun')
    param = PARAM_RE.search(ctrl_txt)
    return condition_phrase(tags, trigger.group(1), chance.group(1),
                            param.group(1) if param else None)


def check_families_agree(item_tags, ui_tags):
    """Both tag families must say the same twelve things.

    This is the assumption that lets one table serve granted skills and
    refresh/cooldown lines alike, so it is asserted on every build rather than
    trusted. Returns the number of conditions compared.
    """
    for trigger, n in sorted(TRIGGER_CONDITION.items(), key=lambda kv: kv[1]):
        a = item_tags.get(AUTO_TAG % n)
        b = ui_tags.get(REFRESH_TAG % n)
        if not a or not b:
            raise AssertionError(f'condition {n:02d} ({trigger}) is missing from '
                                 f'{"tagAuto" if not a else "tagRefresh"}SkillCondition')
        norm = lambda s: _COLOUR_RE.sub('', s).strip('()').replace('  ', ' ').strip()
        if norm(a) != norm(b):
            raise AssertionError(
                f'condition {n:02d} ({trigger}) reads {norm(a)!r} for a granted '
                f'skill and {norm(b)!r} for a refresh line; one table can no '
                f'longer serve both families')
    return len(TRIGGER_CONDITION)
