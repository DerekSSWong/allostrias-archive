"""settings.ini -> three validated paths.

The whole program reads the game through these three paths, so a wrong one is
not a small error: it is a catalogue built from nothing that still looks like a
catalogue. Every accessor here therefore either returns a path that exists or
raises. There is no guessing, no default install location, and no "try the
other place" fallback -- an unresolved path is a bug in the settings file and
the user is the only one who can fix it.

`iagd` is the one optional path (the tool works without Item Assistant), so it
returns None when blank. Blank is a choice; a path that is set but wrong is
still an error.
"""
import configparser
import os
from dataclasses import dataclass

# Repo root: allostrias/settings.py -> allostrias/ -> root.
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SETTINGS_PATH = os.path.join(ROOT, 'settings.ini')
EXAMPLE_PATH = os.path.join(ROOT, 'settings.example.ini')

# The game ships FOUR databases, not one: a base and three expansions. A record
# present in more than one is patched by the LATER archive, so this order is
# load order and must not be sorted or globbed into a set -- reading only
# database.arz yields 34,182 records of which 11,097 are the pre-expansion
# versions, which is worse than missing them because they still look valid.
#
# Expansions the user does not own are simply absent; that is not an error.
# Crucible (survivalmode*/ and mods/survivalmode/) is deliberately NOT here --
# its loot tables reference monsters that exist in no farmable zone.
ARZ_RELPATHS = (
    os.path.join('database', 'database.arz'),
    os.path.join('gdx1', 'database', 'GDX1.arz'),
    os.path.join('gdx2', 'database', 'GDX2.arz'),
    os.path.join('gdx3', 'database', 'GDX3.arz'),
)
# Same stacking rule, same order: an expansion restates tags it changes.
TEXT_ARC_RELPATHS = (
    os.path.join('resources', 'Text_EN.arc'),
    os.path.join('gdx1', 'resources', 'Text_EN.arc'),
    os.path.join('gdx2', 'resources', 'Text_EN.arc'),
    os.path.join('gdx3', 'resources', 'Text_EN.arc'),
)
# The base archive alone proves a directory is the game install.
ARZ_RELPATH = ARZ_RELPATHS[0]


class SettingsError(Exception):
    """settings.ini is missing, incomplete, or points somewhere it shouldn't."""


@dataclass(frozen=True)
class Settings:
    game: str            # game install root
    saves: str           # save root holding main/ and the .gst files
    iagd: str | None     # Item Assistant userdata.db, or None if unconfigured

    @property
    def arz_path(self) -> str:
        """The base archive. Use `arz_paths` to build anything."""
        return os.path.join(self.game, ARZ_RELPATH)

    @property
    def arz_paths(self) -> list[str]:
        """Every database that exists, in load order. Later patches earlier."""
        return self._present(ARZ_RELPATHS)

    @property
    def text_arc_paths(self) -> list[str]:
        """Every English text archive that exists, in load order."""
        return self._present(TEXT_ARC_RELPATHS)

    def _present(self, relpaths) -> list[str]:
        found = [os.path.join(self.game, rel) for rel in relpaths]
        return [p for p in found if os.path.isfile(p)]

    @property
    def cache_dir(self) -> str:
        return os.path.join(ROOT, 'cache')

    @property
    def catalogue_db(self) -> str:
        """Derived from the game archives. Disposable: `rebuild` drops it."""
        return os.path.join(self.cache_dir, 'catalogue.sqlite')

    @property
    def profile_db(self) -> str:
        """Saves and user preferences. NOT disposable -- `rebuild` must not
        touch this file, which is why it is named separately from the
        catalogue rather than living in one database with it."""
        return os.path.join(self.cache_dir, 'profile.sqlite')

    @property
    def profile_backup_db(self) -> str:
        return os.path.join(self.cache_dir, 'profile.backup.sqlite')


def _require_dir(value: str, key: str, contains: str | None = None) -> str:
    path = os.path.abspath(os.path.expanduser(value))
    if not os.path.isdir(path):
        raise SettingsError(
            f"[paths] {key} is not a directory: {path}\n"
            f"  fix {SETTINGS_PATH}"
        )
    if contains and not os.path.exists(os.path.join(path, contains)):
        raise SettingsError(
            f"[paths] {key} does not look right: {path}\n"
            f"  expected to find {contains} inside it\n"
            f"  fix {SETTINGS_PATH}"
        )
    return path


def _require_file(value: str, key: str) -> str:
    path = os.path.abspath(os.path.expanduser(value))
    if not os.path.isfile(path):
        raise SettingsError(
            f"[paths] {key} is not a file: {path}\n"
            f"  fix {SETTINGS_PATH}"
        )
    return path


def load(path: str = SETTINGS_PATH) -> Settings:
    """Read and validate settings.ini. Raises SettingsError; never returns a
    Settings whose paths have not been checked against the filesystem."""
    if not os.path.isfile(path):
        raise SettingsError(
            f"no settings file at {path}\n"
            f"  copy {EXAMPLE_PATH} to settings.ini and fill in the three paths"
        )

    # interpolation=None: a '%' anywhere in a path is a literal, not a format
    # placeholder. Paths are data, not templates.
    parser = configparser.ConfigParser(interpolation=None)
    parser.read(path, encoding='utf-8')

    if not parser.has_section('paths'):
        raise SettingsError(f"{path} has no [paths] section")

    paths = parser['paths']
    missing = [k for k in ('game', 'saves') if not paths.get(k, '').strip()]
    if missing:
        raise SettingsError(
            f"[paths] {', '.join(missing)} is blank in {path}\n"
            f"  see {EXAMPLE_PATH} for what each one means"
        )

    game = _require_dir(paths['game'].strip(), 'game', contains=ARZ_RELPATH)
    saves = _require_dir(paths['saves'].strip(), 'saves', contains='main')

    # Optional: unconfigured is fine, misconfigured is not.
    raw_iagd = paths.get('iagd', '').strip()
    iagd = _require_file(raw_iagd, 'iagd') if raw_iagd else None

    return Settings(game=game, saves=saves, iagd=iagd)
