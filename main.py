#!/usr/bin/env python3
"""allostrias-archive command line.

    status            what the settings point at, and whether a rebuild is due
    rebuild [--force] rebuild cache/catalogue.sqlite from the game archives

`rebuild` drops and recreates the CATALOGUE only. cache/profile.sqlite holds
saves and preferences and is never dropped -- it is backed up first and then
left alone. The two databases share a directory, so that rule lives here, in
code, rather than in the directory layout where it could be assumed.
"""
import argparse
import os
import sqlite3
import sys
import time

from allostrias import settings as S
from allostrias.archive import arc, arz
from allostrias.db import catalogue
from allostrias.db.extract import affixes, eligibility, items


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
                        ('profile', cfg.profile_db)):
        if os.path.isfile(path):
            print(f'  {label:10} {os.path.getsize(path) / 1e6:6.1f} MB')
        else:
            print(f'  {label:10} not built')

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
            for extractor in (items, affixes, eligibility):
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

    return {'status': cmd_status, 'rebuild': cmd_rebuild}[args.command](cfg, args)


if __name__ == '__main__':
    sys.exit(main())
