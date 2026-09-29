"""Gate: formulas.<mode> -> the blueprints the account has unlocked.

Read from the LIVE save directory: these files are account-wide and nothing
freezes them. What is held here is what the reader's output MEANS, not how many
there are: every entry is a blueprint the catalogue knows (so a misread path
cannot pass as one), stash.sqlite carries exactly what the files list, and a
file of another shape raises rather than coming back short.
"""
import os
import sqlite3
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from allostrias import settings as S                    # noqa: E402
from allostrias.archive import formulas, gst            # noqa: E402
from allostrias.archive.savecrypt import SaveError      # noqa: E402

cfg = S.load()
files = gst.save_files(cfg.saves, ('formulas',))
if not files:
    print(f'SKIPPED -- no formulas file in {cfg.saves}, so the reader is UNCHECKED here.')
    raise SystemExit(0)

ca = sqlite3.connect(cfg.catalogue_db)
blueprint = {p for (p,) in ca.execute("SELECT path FROM item WHERE class LIKE 'Item%Formula'")}
read, versions = {}, set()
for path in files:
    got = formulas.read(path)
    versions.add(got['version'])
    assert (got['expansion'] is None) == (got['version'] < 3), (path, got['version'], got['expansion'])
    paths = [p.lower() for p, _ in got['entries']]
    stray = [p for p in paths if p not in blueprint]
    assert not stray, f'{os.path.basename(path)} lists records that are no blueprint: {stray[:3]}'
    assert len(set(paths)) == len(paths), f'{os.path.basename(path)} lists a blueprint twice'
    read[gst.mode_of(path)] = set(paths)
    print(f"  {os.path.basename(path):14} v{got['version']} expansion {got['expansion']}: "
          f"{len(paths)} blueprints")
if versions != set(formulas.VERSIONS):
    print(f'UNCOVERED: no file of version {sorted(set(formulas.VERSIONS) - versions)} to read')

# stash.sqlite holds exactly the files' entries, per mode.
st = sqlite3.connect(cfg.stash_db)
stored = {}
for mode, p in st.execute('SELECT mode, blueprint_path FROM formula'):
    stored.setdefault(mode, set()).add(p.lower())
assert stored == read, 'stash.sqlite does not hold what the formulas files list'

# The union rule's premise, reported: an older-era file adds nothing the newest lacks.
by_core = {}
for mode, got in read.items():
    by_core.setdefault(mode[-1], []).append((mode, got))
for core, modes in by_core.items():
    newest = max(modes, key=lambda m: len(m[1]))
    extra = {m: len(g - newest[1]) for m, g in modes if g - newest[1]}
    print(f'  core {core}: older files add {extra or "nothing"} over {newest[0]}')

# A file cut short, or with a byte after the sentinel, raises.
with open(files[0], 'rb') as fh:
    whole = fh.read()
with tempfile.TemporaryDirectory() as tmp:
    for label, data in (('truncated', whole[:-5]), ('trailing byte', whole + b'\0')):
        p = os.path.join(tmp, 'formulas.gst')
        with open(p, 'wb') as fh:
            fh.write(data)
        try:
            formulas.read(p)
        except SaveError:
            continue
        raise AssertionError(f'a {label} formulas file read without complaint')
print('\nFORMULAS OK')
