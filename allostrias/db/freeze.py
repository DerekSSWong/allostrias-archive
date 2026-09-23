"""Freeze the current saves as a fixture the gates can hold numbers against.

A live save is not a reference. The character gets played: gear changes, a
devotion node is bought, and a gate pinned to "Offensive Ability is 1975" goes
red for a reason that is not a bug. So the numbers the gates assert belong to a
COPY taken deliberately at a moment someone looked at, and the act of taking it
is a command rather than something that happens on its own.

    python3 main.py freeze          # copy the live saves into the fixture dir
    python3 main.py freeze --list   # what is frozen now, and how stale

Only player.gdc is copied. The .gst side files are account-wide rather than
per-character, and the sheet does not read them; copying them would freeze the
stash as a side effect of freezing a character.

⚠️ THE FIXTURES ARE GITIGNORED AND MUST STAY THAT WAY. They are this player's
own characters, in a public repo -- tests/test_no_leaks.py is about strings,
and a .gdc would sail past it because the leak is the whole file.
"""
import os
import shutil
import time

from ..archive import gdc

FIXTURE_RELPATH = os.path.join('tests', 'fixtures', 'saves')


def fixture_dir(root: str) -> str:
    return os.path.join(root, FIXTURE_RELPATH)


def frozen(root: str) -> list[tuple[str, str]]:
    """[(dir name, player.gdc path)] already frozen, or [] if none are."""
    try:
        return gdc.character_dirs(fixture_dir(root))
    except gdc.SaveError:
        return []


def freeze(cfg, root: str) -> list[tuple[str, int, bool]]:
    """Copy every live character save into the fixture dir.

    Returns (name, bytes, changed) per character. `changed` says whether the
    copy differs from what was already frozen, which is the only interesting
    thing about running this twice: a gate's numbers move only when it is True.
    """
    dest_main = os.path.join(fixture_dir(root), 'main')
    os.makedirs(dest_main, exist_ok=True)
    out = []
    for name, src in gdc.character_dirs(cfg.saves):
        dest = os.path.join(dest_main, name, 'player.gdc')
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        before = open(dest, 'rb').read() if os.path.isfile(dest) else None
        data = open(src, 'rb').read()
        # Verified before it is kept: a save caught mid-write would freeze a
        # corrupt fixture, and a fixture is the thing everything else trusts.
        gdc.read_save(src)
        shutil.copy2(src, dest)
        out.append((name, len(data), before != data))
    return out


def describe(root: str) -> list[str]:
    lines = []
    for name, path in frozen(root):
        age = (time.time() - os.path.getmtime(path)) / 86400
        lines.append(f'  {name:<14} {os.path.getsize(path):>7} B   '
                     f'frozen {age:.0f} day(s) ago')
    return lines or ['  nothing frozen yet -- run `python3 main.py freeze`']
