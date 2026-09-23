"""Resolve a texture by name across the game's four archive layers.

Built on this repo's own `arc.py`, not gd-lib's `arc_parse`. That swap is the
point -- no page here may make another project's tree a build dependency -- and
it also sheds a bug: `arc_parse.find()` returns -1 on a miss, which then indexes
the LAST file in the archive and hands back a believable wrong icon.

Lives in `archive/` rather than beside one page because three pages resolve
textures now: the character sheet, the item browser and the UI palette.

Grim Dawn layers its archives -- base, then gdx1..gdx3, later winning. The
layering matters for what it ADDS rather than for staleness: 1,467 of the 3,008
icon paths on named equipment are absent from the base archive, while only 9 of
its names are ever redefined by an expansion.
"""
import os

from . import tex
from .. import settings as S
from .arc import Arc

LAYERS = ['', 'gdx1', 'gdx2', 'gdx3']


class Textures:
    def __init__(self, archive: str, game: str = None):
        game = game or S.load().game
        self.arcs = []
        self.where = {}
        for layer in LAYERS:
            path = os.path.join(game, layer, 'resources', archive)
            if not os.path.exists(path):
                continue
            arc = Arc(path)
            n = len(self.arcs)
            self.arcs.append(arc)
            for i, s in enumerate(arc.names):
                self.where[s.lower()] = (n, i)

    def get(self, name: str):
        """The decoded texture, or None if no layer defines `name`.

        A miss returns None and never a texture. `bitmap=` fields carry an
        `items/` prefix the archive's own paths do not, and skill icons carry a
        `ui/` one; both spellings resolve here so a caller does not have to
        know which record it came from.
        """
        key = name.lower().strip()
        for k in (key, key[6:] if key.startswith('items/') else None,
                  key[3:] if key.startswith('ui/') else None):
            if k and k in self.where:
                n, i = self.where[k]
                data = self.arcs[n].read_file(i)
                return tex.decode(data) if data else None
        return None
