"""What a stored stat value actually rolls between.

A record stores the MIDPOINT of a stat, not the value you get. The width comes
from `lootRandomizerJitter` on the same record. Ported from gd-lib's
affix_table.roll_band, which solved and verified it; the verification notes are
kept because they are what stop the rule being "improved" back into a wrong
one.

Only the BAND lives here. Replaying a specific item's seed to get the value it
actually rolled is a different problem (gd-lib's rolls.py) and is not needed
until saved items are read.
"""
import math


def roll_band(value: float, jitter: float) -> tuple[float, float]:
    """(lo, hi) the game will actually roll for a stored value.

    SOLVED, NOT FITTED. The record stores the midpoint and
    `lootRandomizerJitter` the half-width as a percentage, floored -- but
    never below 1:

        half = max(1, floor(|v| * jitter / 100));  lo = v - half, hi = v + half

    The `max(1, ...)` IS PART OF THE FORMULA, not a guard on it. Plain floor
    collapses the band on small values and the game disagrees: `of Menhir's
    Wall` stores +2% Defensive Ability at jitter 28 and rolls 1-3, where
    floor(0.56) = 0 would give a fixed 2. round() fixes that case and breaks
    five others (10 at jitter 28 rolls 8-12; round gives 7-13).

    THE MULTIPLICATIVE FORM IS WRONG and it is the one you would write first:
    round(v * (1 +/- j/100)) misses 10 of 25 checked values. `of Blood`'s focus
    variant stores 95 at jitter 5 and rolls 91-99; multiplicative says 90-100.
    Floor of the half-width, not a scaling of the endpoints.

    Verified upstream against 25 values read off grimdb (v=4..124, jitter
    5..28, 25/25 exact), then against `Wraithbound` in full -- 118 of 120
    numeric lines exact across four slot families.

    TWO LINES REMAIN OPEN and no rule here explains them, both `characterLife`
    on an accessory: v=150 j=18 shows 124/177 against 123/177, and v=200 j=15
    shows 170/229 against 170/230. Both observed bands are an ODD number wide,
    which no symmetric half-width can produce, and the narrowing is on a
    different side each time -- so it is not a rounding mode. Recorded rather
    than fitted: a rule invented to cover two points out of 120 would be the
    believable wrong answer, not a finding.

    No jitter means the value is fixed, so the band collapses to a point
    instead of being guessed at.

    EVERY LINE ROLLS INDEPENDENTLY. There is no single "quality" per affix.
    Observed on a real drop: `of the Eagle` carries Strength/Dexterity/
    Intelligence all at midpoint 5 with one jitter of 35, so all three share
    the band 4-6 -- and the item rolled +6 / +4 / +4. Same band, three separate
    draws, both extremes hit. One line's roll says nothing about another's, and
    no record anywhere states how many draws are taken.
    """
    if not jitter:
        return (value, value)
    half = max(1, math.floor(abs(value) * jitter / 100.0))
    return (value - half, value + half)
