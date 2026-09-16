"""Where a creature spawns -- the one thing the game does not ship parseably.

Map placement lives in Grim Dawn's compiled level files, which nothing here
reads, so the archives cannot answer "which zone". grimtools.com computes it
from the same game data and publishes it client-side; this module owns the
fetch and the parse of that bundle.

KEYED BY DESCRIPTION TAG, NOT BY MONSTER RECORD. The obvious table -- "monster
record -> zone" -- would be derived from grimtools AND from the archives, so a
game update would invalidate it and demand a 9 MB download to rebuild. Keyed
by the tag both sides already speak, this depends on grimtools alone and the
join to creatures is done locally.

THE ONLY NETWORK ACCESS IN THIS REPO. A failed fetch must never fail the
build: zones come back empty and the catalogue is visibly missing them, which
is the honest outcome. It must also never invent them.
"""
import hashlib
import json
import re
import urllib.error
import urllib.request

BUNDLE_URL = 'https://www.grimtools.com/monsterdb/js/monsterdb.js'
FETCH_TIMEOUT = 120
# The bundle is ~9 MB. Anything far smaller is a challenge page or an error
# document served with a 200, which this site does for any unknown path.
MIN_PLAUSIBLE_BYTES = 1_000_000

# Python's default 'Python-urllib/3.x' is refused with a 403; any other agent
# is served normally. This one identifies the tool honestly rather than
# impersonating a browser -- the data is public and served to anyone who asks
# under a name, and a request that lies about who it is would be a worse
# citizen than one that is simply refused.
USER_AGENT = ('allostrias-archive/0.1 '
              '(+https://github.com/DerekSSWong/allostrias-archive)')


class SpawnError(Exception):
    """The bundle could not be fetched or is not the shape we know."""


def fetch(url: str = BUNDLE_URL, timeout: int = FETCH_TIMEOUT) -> str:
    request = urllib.request.Request(url, headers={'User-Agent': USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read()
    except (urllib.error.URLError, OSError, TimeoutError) as exc:
        raise SpawnError(f'could not fetch {url}: {exc}') from exc
    if len(raw) < MIN_PLAUSIBLE_BYTES:
        raise SpawnError(
            f'{url} returned {len(raw)} bytes, far short of the ~9 MB bundle. '
            'grimtools serves its app HTML with a 200 for unknown paths, so a '
            'short body means the path moved, not that the data shrank.')
    return raw.decode('utf-8', 'replace')


def _object_at(text: str, anchor: str) -> str:
    """The `{...}` following `anchor`, via a string-aware brace walk.

    NOT a regex. The bundle is one minified line per assignment with braces and
    quotes nested arbitrarily; scanning for the matching `}` without tracking
    string state stops inside the first `"}"` in a display name.
    """
    try:
        start = text.index(anchor) + len(anchor)
    except ValueError:
        raise SpawnError(f'{anchor} not present -- the bundle format changed')
    if text[start] != '{':
        raise SpawnError(f'{anchor} is not followed by an object')
    depth, i, in_string, escaped = 0, start, False, False
    while i < len(text):
        char = text[i]
        if in_string:
            if escaped:
                escaped = False
            elif char == '\\':
                escaped = True
            elif char == '"':
                in_string = False
        elif char == '"':
            in_string = True
        elif char == '{':
            depth += 1
        elif char == '}':
            depth -= 1
            if depth == 0:
                return text[start:i + 1]
        i += 1
    raise SpawnError(f'{anchor} is not closed -- the download is truncated')


def _flat_json(text: str, anchor: str) -> dict:
    """A flat {key: value} object, as JSON.

    The `\\s*` before the key is load-bearing: the bundle wraps long lines, so
    a key can follow ",\\n" and a pattern anchored straight after the comma
    leaves it unquoted -- and the parse then dies megabytes later.
    """
    body = _object_at(text, anchor)
    return json.loads(re.sub(r'([{,])\s*([A-Za-z_]\w*):', r'\1"\2":', body))


def _member(chunk: str, out: dict):
    if ':' not in chunk:
        return
    key = chunk[:chunk.index(':')].strip()
    found = re.search(r'[{,]\s*d:"([^"]+)"', chunk)
    if key and found:
        out[key] = found.group(1)


def _monster_tags(text: str) -> dict[str, str]:
    """grimtools monster id -> its `d:` description tag.

    allMonsters is one object of a few thousand members with dozens of fields
    each. Scanning backwards from a `d:"tag"` to the nearest `mNNN:{` finds the
    WRONG member, because the keys are not in sorted order -- so split on
    top-level commas and read each member whole.
    """
    body = _object_at(text, 'window.allMonsters=')[1:-1]
    out: dict[str, str] = {}
    depth, in_string, escaped, start = 0, False, False, 0
    for i, char in enumerate(body):
        if in_string:
            if escaped:
                escaped = False
            elif char == '\\':
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == '{':
            depth += 1
        elif char == '}':
            depth -= 1
        elif char == ',' and depth == 0:
            _member(body[start:i], out)
            start = i + 1
    _member(body[start:], out)
    return out


def parse(text: str) -> tuple[list[tuple[str, str, int]], dict]:
    """(rows, meta). Rows are (monster tag, zone tag, placements).

    REFUSES RATHER THAN RETURNING A SHORT TABLE. Every failure here is silent
    by nature -- a moved anchor, a changed minifier, a truncated download all
    yield SOME rows. The zone cross-check is the one that cannot be faked:
    every zone that monsterSpawns places into must be named by spawnLocations,
    which holds exactly on good input and breaks the moment either object is
    read from the wrong offset.

    Several grimtools monster ids share one description tag -- distinct
    creature records with the same display name in different zones -- so their
    placements are SUMMED rather than deduplicated.
    """
    version = re.search(r'window\.gameVersion="([^"]+)"', text)
    zones = _flat_json(text, 'window.spawnLocations=')
    spawns = _flat_json(text, 'window.monsterSpawns=')
    tags = _monster_tags(text)
    if not zones or not spawns or not tags:
        raise SpawnError('one of spawnLocations / monsterSpawns / allMonsters '
                         'parsed empty -- the bundle format has changed')

    unknown = {z for placed in spawns.values() for z in placed} - set(zones)
    if unknown:
        raise SpawnError(
            f'{len(unknown)} zone id(s) are placed but never named, e.g. '
            f'{sorted(unknown)[:5]} -- the two objects did not come from the '
            'same parse')

    # At least one zone carries the literal string "null" as its tag. Written
    # out it becomes a place called "null"; dropped silently it becomes a
    # monster that spawns nowhere. Counted, so the meta says what was dropped.
    nameless = {z for z, tag in zones.items() if not tag or tag == 'null'}

    totals: dict[tuple[str, str], int] = {}
    for monster_id, placed in spawns.items():
        tag = tags.get(monster_id)
        if not tag:
            continue                 # a monster grimtools has no tag for
        for zone_id, count in placed.items():
            if zone_id in nameless:
                continue
            key = (tag, zones[zone_id])
            totals[key] = totals.get(key, 0) + count

    rows = [(tag, zone, count) for (tag, zone), count in sorted(totals.items())]
    meta = {
        'source': BUNDLE_URL,
        'game_version': version.group(1) if version else '',
        'digest': hashlib.sha256(text.encode('utf-8', 'replace')).hexdigest(),
        'rows': len(rows),
        'monsters': len({t for t, _z, _n in rows}),
        'zones': len({z for _t, z, _n in rows}),
        'untagged_monsters': sum(1 for m in spawns if m not in tags),
        'nameless_zones': len(nameless),
    }
    return rows, meta
