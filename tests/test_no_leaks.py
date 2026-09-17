"""No machine-specific or personal data in tracked files.

This repo is public and the data it reads is not: the game install path, the
Steam user id inside the save path, and the home directory all identify the
machine and its owner. settings.ini and cache/ are gitignored for that reason,
but nothing stopped a path being hardcoded into source -- and one was, in a
test constant, which is exactly the kind of thing that survives review because
it looks like configuration.

The patterns are DERIVED from the live settings rather than written down here,
so this checks the actual secrets rather than a list someone remembered to
update.
"""
import os
import re
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from allostrias import settings as S               # noqa: E402

cfg = S.load()

# What actually identifies this machine and its owner, derived from the live
# settings. Deliberately NOT every path segment: names like 'EvilSoft',
# 'steamuser' and 'AppData' are vendor and OS conventions that belong in
# settings.example.ini as documentation, and flagging them would train the
# reader to ignore this gate.
home = os.path.expanduser('~')
secrets = {home, cfg.game, cfg.saves}
if cfg.iagd:
    secrets.add(cfg.iagd)
secrets.add(os.path.basename(home))          # the username itself
# Numeric path segments are the Steam USER id -- the one identifier here a
# stranger could act on. Grim Dawn's APP id is also a long number and appears
# in every documented path in settings.example.ini; it is the same for every
# player on earth and is public, so it is not a secret and must not be flagged.
GRIM_DAWN_APP_ID = '219990'
for path in (cfg.saves, cfg.game, cfg.iagd or ''):
    secrets.update(n for n in re.findall(r'\d{6,}', path)
                   if n != GRIM_DAWN_APP_ID)
secrets.discard('')

tracked = subprocess.run(['git', 'ls-files'], cwd=S.ROOT,
                         capture_output=True, text=True, check=True)
files = [f for f in tracked.stdout.splitlines() if f]
assert files, 'git ls-files returned nothing; is this a repo?'

found = []
for relpath in files:
    path = os.path.join(S.ROOT, relpath)
    try:
        with open(path, encoding='utf-8', errors='replace') as fh:
            for lineno, line in enumerate(fh, 1):
                for secret in secrets:
                    if secret in line:
                        found.append(f'{relpath}:{lineno}: {secret!r}')
    except (IsADirectoryError, PermissionError):
        continue

print(f'{len(files)} tracked files scanned for {len(secrets)} machine-specific '
      f'strings')
for hit in found[:10]:
    print(f'  LEAK {hit}')
assert not found, f'{len(found)} tracked line(s) contain machine-specific data'

# And the two things that must stay ignored.
for relpath in ('settings.ini', 'cache/catalogue.sqlite',
                'cache/stash.sqlite'):
    result = subprocess.run(['git', 'check-ignore', '-q', relpath],
                            cwd=S.ROOT)
    assert result.returncode == 0, f'{relpath} is NOT gitignored'
print('  settings.ini and cache/ are gitignored')

print('\nNO LEAKS')
