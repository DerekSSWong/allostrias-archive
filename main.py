#!/usr/bin/env python3
"""allostrias-archive command line.

    status            what the settings point at, and whether a rebuild is due
    rebuild [--force] rebuild cache/catalogue.sqlite from the game archives

cache/ holds three databases and they are not governed by one rule, so the
rule lives here, in code, rather than in the directory layout where it could be
assumed:

  catalogue.sqlite  derived from the game archives. `rebuild` drops it, and a
                    staleness check decides when that is due.
  stash.sqlite      derived from the save files. Rebuilt on EVERY launch,
                    before any command runs -- the saves move every session,
                    and reading them costs milliseconds.
  stash_iagd.sqlite derived from Item Assistant's collection, if that path is
                    configured. Same rule, same reason. Absent entirely when
                    `iagd` is blank -- the two stashes are disjoint halves of
                    one collection, and an empty half is not the same as a
                    half that was never looked at.
  profile.sqlite    the one file here that cannot be regenerated. Never
                    dropped by anything; backed up before a rebuild and then
                    left alone.

                    ⚠️ Its character_* tables ARE regenerable and are refilled
                    from the saves on every launch, exactly like the stash.
                    The file is durable; those four tables are a mirror. That
                    is why a schema change there drops the TABLES and not the
                    database -- see db/character.py.
"""
import argparse
import os
import sqlite3
import sys
import time

from allostrias import settings as S
from allostrias.archive import arc, arz
from allostrias.archive import gdc, gst
from allostrias.archive.savecrypt import SaveError
from allostrias.db import catalogue, character, iagd, stash
from allostrias.db.extract import (affixes, bonuses, factions, items, mi,
                                   recipes, shared_pass, skills, vendors,
                                   zones)


# Shown by `status` only. The tier is what the database stores; naming it is a
# display concern and the names live here rather than in the schema.
DIFFICULTY = gdc.DIFFICULTIES


def backup_profile(cfg: S.Settings) -> str | None:
    """Copy profile.sqlite aside before a rebuild touches the cache directory.

    Uses SQLite's own backup API rather than copying the file, so a profile
    with a live WAL is captured consistently instead of being copied mid-write.
    """
    if not os.path.isfile(cfg.profile_db):
        return None
    source = sqlite3.connect(cfg.profile_db)
    target = sqlite3.connect(cfg.profile_backup_db)
    try:
        source.backup(target)
    finally:
        target.close()
        source.close()
    return cfg.profile_backup_db


def cmd_status(cfg: S.Settings, _args) -> int:
    print('paths')
    print(f'  game   {cfg.game}')
    print(f'  saves  {cfg.saves}')
    print(f'  iagd   {cfg.iagd or "(not configured)"}')

    print('\narchives, in load order')
    for i, path in enumerate(cfg.arz_paths):
        print(f'  {i}  {os.path.relpath(path, cfg.game):34} '
              f'{os.path.getsize(path) / 1e6:6.1f} MB')

    print('\ncache')
    for label, path in (('catalogue', cfg.catalogue_db),
                        ('stash', cfg.stash_db),
                        ('stash_iagd', cfg.stash_iagd_db),
                        ('profile', cfg.profile_db)):
        if os.path.isfile(path):
            print(f'  {label:10} {os.path.getsize(path) / 1e6:6.1f} MB')
        elif label == 'stash_iagd' and not cfg.iagd:
            print(f'  {label:10} iagd not configured')
        else:
            print(f'  {label:10} not built')

    if os.path.isfile(cfg.stash_db):
        print('\nstash, rebuilt this launch')
        for row in stash.summary(cfg.stash_db):
            if row['kind'] == 'reagents':
                held = f'{row["materials"]} materials'
            else:
                pages = f'{row["pages"]} page' + ('s' if row['pages'] != 1 else '')
                held = f'{pages}, {row["items"]} items'
            print(f'  {row["relpath"]:14} {held:24} '
                  f'v{row["version"]}'
                  + (f', expansion bits {row["expansion"]}'
                     if row['expansion'] is not None else ''))

    if os.path.isfile(cfg.profile_db):
        print('\ncharacters, rebuilt this launch')
        for row in character.summary(cfg.profile_db):
            if row['error']:
                print(f'  {row["dir_name"]:14} UNREADABLE: {row["error"]}')
                continue
            print(f'  {row["dir_name"]:14} level {row["level"]:<4} '
                  f'{DIFFICULTY[row["difficulty_tier"]]:9}'
                  f'{row["invested"]:3} skills, {row["devotion_total"]:2} '
                  f'devotion, {row["worn"]:2} items worn')

    if cfg.iagd and os.path.isfile(cfg.stash_iagd_db):
        found = iagd.summary(cfg.stash_iagd_db)
        source = found['source'] or {}
        wal = source.get('wal_size')
        print('\niagd collection, rebuilt this launch')
        print(f'  {source.get("relpath", "?"):14} {found["items"]} items, '
              f'{found["records"]} records   '
              f'{source.get("size", 0) / 1e6:.0f} MB'
              + (f' + {wal / 1e6:.1f} MB write-ahead log' if wal else ''))

    if not os.path.isfile(cfg.catalogue_db):
        print('\nrebuild needed: never built')
        return 0
    conn = catalogue.connect(cfg.catalogue_db, create=False)
    try:
        reason = catalogue.staleness(conn, cfg.game, cfg.arz_paths)
    finally:
        conn.close()
    print(f'\n{"rebuild needed: " + reason if reason else "up to date"}')
    return 0


def cmd_rebuild(cfg: S.Settings, args) -> int:
    fresh = not os.path.isfile(cfg.catalogue_db)
    if not fresh and not args.force:
        conn = catalogue.connect(cfg.catalogue_db, create=False)
        try:
            reason = catalogue.staleness(conn, cfg.game, cfg.arz_paths)
        finally:
            conn.close()
        if reason is None:
            print('up to date; nothing to do (use --force to rebuild anyway)')
            return 0
        print(f'rebuilding: {reason}')

    saved = backup_profile(cfg)
    if saved:
        print(f'profile backed up to {os.path.basename(saved)}')

    # Drop only the catalogue. Deleting the cache directory would take the
    # profile with it, which is the one thing here that cannot be regenerated.
    for suffix in ('', '-wal', '-shm'):
        stale_file = cfg.catalogue_db + suffix
        if os.path.exists(stale_file):
            os.remove(stale_file)

    t0 = time.time()
    conn = catalogue.connect(cfg.catalogue_db)
    try:
        catalogue.apply_schema(conn)
        tags = arc.load_tags(cfg.text_arc_paths)
        print(f'  tags        {len(tags)}')
        with arz.Database(cfg.arz_paths) as db:
            print(f'  records     {len(db)} '
                  f'({db.override_count} patched by an expansion)')
            # `shared_pass` is where eligibility and drops run: both need the
            # whole record tree, so one walk feeds both. See that module --
            # this tuple is no longer the whole story.
            for extractor in (items, affixes, bonuses, shared_pass, mi,
                              factions, recipes, skills, vendors,
                              zones):
                for label, count in extractor.extract(conn, db, tags).items():
                    print(f'  {label:22} {count}')
        # Stamped last, on purpose: a stamp written before the data would mark
        # a build that then failed as fresh.
        catalogue.stamp(conn, cfg.game, cfg.arz_paths)
    finally:
        conn.close()
    size = os.path.getsize(cfg.catalogue_db) / 1e6
    print(f'built in {time.time() - t0:.1f}s, {size:.1f} MB')
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog='allostrias-archive')
    sub = parser.add_subparsers(dest='command', required=True)
    sub.add_parser('status', help='paths, archives and whether a rebuild is due')
    rebuild = sub.add_parser('rebuild', help='rebuild the catalogue')
    rebuild.add_argument('--force', action='store_true',
                         help='rebuild even if the archives are unchanged')
    args = parser.parse_args(argv)

    try:
        cfg = S.load()
    except S.SettingsError as exc:
        print(f'settings: {exc}', file=sys.stderr)
        return 2

    # Before the command, not inside it: every command that reads the stash
    # should see this session's saves, and `status` should report what was
    # actually just read rather than what a previous launch found.
    #
    # A failure here does NOT stop the command. The stash builds from files
    # the game may be rewriting at this moment, and refusing to run `status`
    # -- the command you reach for when something looks wrong -- would be the
    # worst possible response to that. The previous database is left intact,
    # the reason is printed where it cannot be mistaken for output, and the
    # exit code carries the failure even when the command itself succeeds.
    stash_failure = None
    try:
        stash.refresh(cfg)
    except (gst.SaveError, OSError) as exc:
        stash_failure = exc
        print(f'stash: {exc}', file=sys.stderr)
    # Separate try: Item Assistant is a different program with a different way
    # of being unavailable, and one of them failing must not hide the other.
    try:
        iagd.refresh(cfg)
    except (iagd.IagdError, OSError) as exc:
        stash_failure = stash_failure or exc
        print(f'iagd: {exc}', file=sys.stderr)
    # Third separate try, same reason: a save directory that cannot be read at
    # all is a different failure from a stash that cannot, and one must not
    # hide the other. A character whose own save will not parse does NOT raise
    # here -- it is recorded as unreadable and counted below, so the other
    # characters still build.
    try:
        unreadable = character.refresh(cfg)['unreadable']
        if unreadable:
            stash_failure = stash_failure or RuntimeError(
                f'{unreadable} character save(s) could not be read')
            print(f'characters: {unreadable} save(s) could not be read; see '
                  f'character_read_error', file=sys.stderr)
    except (SaveError, OSError) as exc:
        stash_failure = stash_failure or exc
        print(f'characters: {exc}', file=sys.stderr)

    code = {'status': cmd_status, 'rebuild': cmd_rebuild}[args.command](cfg, args)
    return code or (1 if stash_failure else 0)


if __name__ == '__main__':
    sys.exit(main())
