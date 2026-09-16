"""Step 4 gate: the rebuild cycle, and the rule that protects profile.sqlite.

Two things are proven here and neither is about record contents:

  1. The staleness check actually detects a game update. Touching an archive
     must trigger a rebuild; not touching one must not. A gate that only ever
     tested the fresh-build path would pass against a check hardwired to True.
  2. `rebuild` leaves profile.sqlite BYTE-IDENTICAL and writes a backup. The
     catalogue is disposable; the profile is the only thing in cache/ that
     cannot be regenerated, and it shares a directory with the thing that gets
     deleted. That is the failure this asserts against.
"""
import hashlib
import io
import os
import sqlite3
import sys
import time
from contextlib import redirect_stdout

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import main                                      # noqa: E402
from allostrias import settings as S             # noqa: E402
from allostrias.db import catalogue              # noqa: E402

cfg = S.load()


def run(*argv) -> str:
    buf = io.StringIO()
    with redirect_stdout(buf):
        code = main.main(list(argv))
    assert code == 0, f'{argv} exited {code}'
    return buf.getvalue()


def digest(path: str) -> str:
    with open(path, 'rb') as fh:
        return hashlib.sha256(fh.read()).hexdigest()


# -- 1. first build ---------------------------------------------------------
for suffix in ('', '-wal', '-shm'):
    if os.path.exists(cfg.catalogue_db + suffix):
        os.remove(cfg.catalogue_db + suffix)
out = run('rebuild')
print('first build:', out.strip().splitlines()[-1])
assert os.path.isfile(cfg.catalogue_db), 'no catalogue written'
assert 'records     82448' in out, out
assert 'items' in out, out

# -- 2. a profile the rebuild must not harm --------------------------------
# Stands in for real saves and preferences, which Phase 4 will write here.
conn = sqlite3.connect(cfg.profile_db)
conn.execute('CREATE TABLE IF NOT EXISTS canary (note TEXT)')
conn.execute('DELETE FROM canary')
conn.execute("INSERT INTO canary VALUES ('irreplaceable')")
conn.commit()
conn.close()
before = digest(cfg.profile_db)

# -- 3. the gate says up to date, and skips ---------------------------------
out = run('rebuild')
assert 'up to date' in out, out
print('unchanged archives:', out.strip())

# -- 4. a simulated game update triggers a rebuild -------------------------
# mtime only, so the archive's bytes are untouched; this is exactly what a
# patch that rewrites a file to the same size looks like.
target = cfg.arz_paths[2]
original = os.stat(target)
os.utime(target, ns=(original.st_atime_ns, original.st_mtime_ns + 1_000_000_000))
try:
    conn = catalogue.connect(cfg.catalogue_db, create=False)
    reason = catalogue.staleness(conn, cfg.game, cfg.arz_paths)
    conn.close()
    assert reason and 'GDX2' in reason, f'update not detected, got {reason!r}'
    print('simulated update:', reason)
    out = run('rebuild')
    assert 'rebuilding' in out, out
finally:
    os.utime(target, ns=(original.st_atime_ns, original.st_mtime_ns))

# -- 5. the profile survived, and was backed up ----------------------------
assert os.path.isfile(cfg.profile_db), 'REBUILD DELETED THE PROFILE'
assert digest(cfg.profile_db) == before, 'REBUILD MODIFIED THE PROFILE'
assert os.path.isfile(cfg.profile_backup_db), 'no profile backup written'
conn = sqlite3.connect(cfg.profile_backup_db)
note = conn.execute('SELECT note FROM canary').fetchone()[0]
conn.close()
assert note == 'irreplaceable', f'backup holds {note!r}'
print('profile: unchanged and backed up, contents intact')

# -- 6. and the catalogue really was rebuilt after the touch ---------------
conn = catalogue.connect(cfg.catalogue_db, create=False)
rows = conn.execute('SELECT ordinal, relpath FROM source_archive '
                    'ORDER BY ordinal').fetchall()
version = conn.execute(
    "SELECT value FROM build_meta WHERE key='schema_version'").fetchone()[0]
after_restore = catalogue.staleness(conn, cfg.game, cfg.arz_paths)
conn.close()
assert [r['ordinal'] for r in rows] == [0, 1, 2, 3], rows
assert version == catalogue.SCHEMA_VERSION
print(f'stamp: schema {version}, {len(rows)} archives in load order')
# The mtime was restored in step 4, so the stamp now disagrees with disk --
# which is itself proof the check compares mtime rather than ignoring it.
assert after_restore is not None, 'staleness ignored a reverted mtime'
print(f'reverted mtime detected too: {after_restore}')

run('rebuild', '--force')
# The catalogue must contain the item spine, not just an empty schema: a
# rebuild that produced a valid but blank database would otherwise pass here.
conn = catalogue.connect(cfg.catalogue_db, create=False)
n_items = conn.execute('SELECT count(*) FROM item').fetchone()[0]
n_stats = conn.execute('SELECT count(*) FROM item_stat').fetchone()[0]
conn.close()
assert n_items == 9891, n_items
assert n_stats > 300_000, n_stats
print(f'\ncatalogue {os.path.getsize(cfg.catalogue_db) / 1e6:.1f} MB, '
      f'{n_items} items, {n_stats} stat rows')
print('\nSTEP 4 PASS')
