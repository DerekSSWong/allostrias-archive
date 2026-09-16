"""settings.py gate: a bad path must RAISE, not degrade.

The happy path is the easy half. The half that matters is that every way of
getting settings.ini wrong produces an exception, because the alternative -- a
Settings object holding a path that isn't there -- builds an empty catalogue
that looks exactly like a full one.
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from allostrias import settings as S  # noqa: E402


def write_ini(body: str) -> str:
    fd, path = tempfile.mkstemp(suffix='.ini')
    with os.fdopen(fd, 'w') as fh:
        fh.write(body)
    return path


def expect_raise(label: str, body: str | None, path: str | None = None):
    target = path if body is None else write_ini(body)
    try:
        S.load(target)
    except S.SettingsError as exc:
        print(f'  raises  {label}: {str(exc).splitlines()[0]}')
        return
    raise AssertionError(f'{label}: expected SettingsError, got a Settings')


real = S.load()
print('real settings.ini:')
for key in ('game', 'saves', 'iagd'):
    value = getattr(real, key)
    assert value is None or os.path.exists(value), f'{key} does not exist'
    print(f'  {key:6} ok')
assert os.path.isfile(real.arz_path), 'arz_path missing'
assert os.path.isfile(real.text_arc_path), 'text_arc_path missing'
print(f'  arz    ok  ({os.path.getsize(real.arz_path) / 1e6:.0f} MB)')
print(f'  text   ok  ({os.path.getsize(real.text_arc_path) / 1e3:.0f} KB)')

# catalogue and profile must be distinct files: rebuild drops one, keeps the other.
assert real.catalogue_db != real.profile_db
print('  cache  ok  catalogue and profile are separate files')

print('failure modes:')
expect_raise('no file', None, '/nonexistent/settings.ini')
expect_raise('no [paths]', '[other]\ngame = /tmp\n')
expect_raise('blank game', '[paths]\ngame =\nsaves = /tmp\n')
expect_raise('blank saves', f'[paths]\ngame = {real.game}\nsaves =\n')
expect_raise('game not a dir', '[paths]\ngame = /etc/hostname\nsaves = /tmp\n')
expect_raise('game without database.arz',
             f'[paths]\ngame = /tmp\nsaves = {real.saves}\n')
expect_raise('saves without main/',
             f'[paths]\ngame = {real.game}\nsaves = /tmp\n')
expect_raise('iagd set but wrong',
             f'[paths]\ngame = {real.game}\nsaves = {real.saves}\n'
             f'iagd = /nonexistent/userdata.db\n')

# Blank iagd is a CHOICE, not an error -- the tool works without it.
blank = S.load(write_ini(f'[paths]\ngame = {real.game}\nsaves = {real.saves}\niagd =\n'))
assert blank.iagd is None
print('  blank iagd -> None (optional, as designed)')

# A literal '%' in a path must survive: interpolation is off.
pct = os.path.join(tempfile.mkdtemp(), '100%game')
os.makedirs(os.path.join(pct, 'database'))
os.makedirs(os.path.join(pct, 'main'))
open(os.path.join(pct, 'database', 'database.arz'), 'w').close()
got = S.load(write_ini(f'[paths]\ngame = {pct}\nsaves = {pct}\n'))
assert got.game == pct, got.game
print("  '%' in a path survives (interpolation disabled)")

print('\nSTEP 1 PASS')
