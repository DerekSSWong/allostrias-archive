"""Which item classes each affix can roll onto.

An affix record does not say where it can appear. The game states it from the
other side: a `Class=LootItemTable_DynWeight` record under
records/items/loottables/ names both the item bases it can drop
(`lootName<N>`) and the affix pools that apply to those bases
(`prefixTableName<N>`, `rarePrefixTableName<N>`, and the suffix equivalents).
Each pool then lists its members as `randomizerName<N>`. Walking that join
yields affix -> item class, already computed by the game.

TWO MISTAKES ARE BAKED INTO THIS MODULE AS COMMENTS BECAUSE BOTH WERE MADE:

  * NOT the reroll tables. The 22 files under loottables/rerolltables/ are the
    Reforge NPC's feature -- paying to reroll an existing item -- which is
    related to drop eligibility but not guaranteed identical, and covers a
    third of the affixes. The real mechanism is the ~2,600 DynWeight tables.
  * CASE MATTERS in the pool field names. `prefixTableName1` (lowercase p) is
    the MAGICAL-tier pool and `rarePrefixTableName1` the Rare-tier one. A
    pattern that only matches capital "Prefix" silently drops every
    Magical-tier reference, which reads as Rare resolving fully while Magical
    resolves at 9% -- a shortfall that looks like missing data rather than a
    broken regex.
"""
import re

from ...archive import values as V

# Drop tables are NOT confined to records/items/loottables/. 69 of them live
# under records/endlessdungeon/ (Shattered Realm), and they are the only route
# to the caster-weapon and focus affix pools -- omitting them leaves 1,077
# affixes with no eligibility at all, which reads as missing data rather than
# as a folder that was never scanned. So the scan is by Class, everywhere.
DYN_WEIGHT = 'LootItemTable_DynWeight'

# records/sandbox/kamil and .../jakub hold 61 more. They are developer scratch
# -- named after people, not content -- and including them adds eligibility
# the shipped game never grants. Excluded, and the gate confirms the exclusion
# is what makes the slot sets match the oracle exactly.
EXCLUDED_ROOTS = ('records/sandbox/',)

LOOT_FIELD = re.compile(r'^lootName\d+$')
MEMBER_FIELD = re.compile(r'^randomizerName(\d+)$')
# Lowercase prefix/suffix = Magical tier; rare-prefixed = Rare tier. Both are
# real and they mean different things; see the module docstring.
POOL_FIELD = re.compile(
    r'^(rare[Pp]refix|prefix|rare[Ss]uffix|suffix)TableName\d+$')


def _tier_of(field: str) -> str:
    return 'rare' if field.startswith('rare') else 'magical'


class Collector:
    """eligibility's half of the shared tree pass.

    THE WALK ITSELF IS NOT HERE. This module needs every record only because a
    DynWeight table can be anywhere -- it keeps roughly 2,600 of the 82,448 it
    is offered -- and drops needs the same walk, so one loop in
    extract/shared_pass.py feeds both instead of the tree being read twice.

    ⚠️ `offer` RECEIVES NON-DEFAULT ATTRIBUTES, where the standalone version
    tested `Class` on the raw record before computing them. The two are
    equivalent because values.non_default() ALWAYS keeps `Class` -- it is the
    one field it will not drop, by design, precisely because every extractor
    keys off it. drops has always relied on that; this now does too.

    ⚠️ `item` IS NOT FILLED UNTIL THE WALK ENDS -- items is a consumer of the
    same pass. So `offer` only holds the DynWeight tables, and `finish`, which
    runs after items', resolves their loot targets to classes.
    """

    def __init__(self, conn, db, _tags):
        self.conn, self.db = conn, db
        self.affix_ids = {row['path']: row['id']
                          for row in conn.execute('SELECT id, path FROM affix')}
        self.held: list[dict] = []
        self.pool_members: dict[str, dict[str, tuple[int, int] | None]] = {}
        self.pairs: set[tuple[int, str, str]] = set()
        self.levels: dict[int, tuple[int, int]] = {}
        self.tables = 0
        self.unresolved_base = 0
        self.unresolved_affix = 0
        self.excluded = 0

    def _members(self, pool_path: str) -> dict[str, tuple[int, int] | None]:
        """The affixes in one pool file, each with the item-level window its
        entry rolls in (randomizerLevelMin/Max<N>), or None where the entry
        states none. Memoised -- a pool is referenced by many drop tables, so
        this is asked far more often than there are pools."""
        key = pool_path.lower()
        if key not in self.pool_members:
            found = {}
            if key in self.db:
                attrs = V.non_default(self.db.read(key))
                for field, values in attrs.items():
                    m = MEMBER_FIELD.match(field)
                    if not m:
                        continue
                    lo = attrs.get(f'randomizerLevelMin{m.group(1)}')
                    hi = attrs.get(f'randomizerLevelMax{m.group(1)}')
                    # non_default() drops a 0, so a Min missing beside a Max is 0
                    window = (int(float(lo[0])) if lo else 0, int(float(hi[0]))) if hi else None
                    for v in values:
                        if isinstance(v, str) and v:
                            found[v.lower()] = window
            self.pool_members[key] = found
        return self.pool_members[key]

    def offer(self, path: str, _attrs: dict, kept: dict):
        if V.first_str(kept, 'Class') != DYN_WEIGHT:
            return
        if path.startswith(EXCLUDED_ROOTS):
            self.excluded += 1
            return
        self.held.append(kept)

    def _resolve(self, kept: dict, item_class: dict[str, str]):
        classes = set()
        for field, values in kept.items():
            if not LOOT_FIELD.match(field):
                continue
            for value in values:
                if not isinstance(value, str) or not value:
                    continue
                found = item_class.get(value.lower())
                if found:
                    classes.add(found)
                else:
                    # A loot target that is not in `item` is machinery (a
                    # nested table) or a base this catalogue does not carry.
                    self.unresolved_base += 1
        if not classes:
            return
        self.tables += 1

        for field, values in kept.items():
            if not POOL_FIELD.match(field):
                continue
            tier = _tier_of(field)
            for pool in values:
                if not isinstance(pool, str) or not pool:
                    continue
                for member, window in self._members(pool).items():
                    affix_id = self.affix_ids.get(member)
                    if affix_id is None:
                        self.unresolved_affix += 1
                        continue
                    if window:
                        lo, hi = self.levels.get(affix_id, window)
                        self.levels[affix_id] = (min(lo, window[0]), max(hi, window[1]))
                    for cls in classes:
                        self.pairs.add((affix_id, cls, tier))

    def finish(self) -> dict[str, int]:
        item_class = {row['path']: row['class']
                      for row in self.conn.execute('SELECT path, class FROM item')}
        for kept in self.held:
            self._resolve(kept, item_class)
        self.conn.execute('DELETE FROM affix_eligibility')
        self.conn.executemany(
            'INSERT INTO affix_eligibility (affix_id, item_class, tier) '
            'VALUES (?,?,?)', sorted(self.pairs))
        self.conn.execute('DELETE FROM affix_level')
        self.conn.executemany(
            'INSERT INTO affix_level (affix_id, level_min, level_max) VALUES (?,?,?)',
            sorted((a, lo, hi) for a, (lo, hi) in self.levels.items()))
        self.conn.commit()
        reachable = len({p[0] for p in self.pairs})
        return {'drop tables walked': self.tables,
                'eligibility pairs': len(self.pairs),
                'affixes reachable': reachable,
                'affixes with a level window': len(self.levels),
                'affixes that never drop': len(self.affix_ids) - reachable,
                'unresolved loot targets': self.unresolved_base,
                'unresolved pool members': self.unresolved_affix,
                'sandbox tables excluded': self.excluded}
