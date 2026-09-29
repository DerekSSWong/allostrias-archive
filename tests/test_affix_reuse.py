"""Gate: the server reuses affixes.json only when its inputs are unchanged.

`affixes.main(reuse=True)` is what the Refresh server's startup calls, to skip
a 5 s rebuild of a bundle no save can change. A reuse rule that is too loose
serves a stale corpus after a game patch or a code change, and nothing else
would notice. `build` is stubbed, so this checks the rule, not the corpus --
test_affix_corpus does that.
"""
import os
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from allostrias import settings as S               # noqa: E402
from allostrias.affixes import build as B          # noqa: E402
from allostrias.db import catalogue                # noqa: E402

cfg = S.load()
out = os.path.join(cfg.cache_dir, 'test_affix_reuse')
shutil.rmtree(out, ignore_errors=True)
bundle = os.path.join(out, 'affixes.json')

builds = []
B.build = lambda conn: (builds.append(1) or ({'t': [], 'f': []}, {}))


def run(reuse):
    before = len(builds)
    B.main(out, reuse=reuse)
    return len(builds) > before


try:
    assert run(reuse=True), 'no bundle yet, but nothing was built'
    assert os.path.isfile(bundle + '.inputs'), 'built without recording its inputs'
    assert not run(reuse=True), 'same inputs, but it rebuilt'
    assert run(reuse=False), 'reuse=False must always build: the gates rely on it'
    print('same inputs reused; reuse=False always builds')

    # Any input moving must rebuild. Each is changed through what `inputs`
    # reads, so the check follows the function rather than a list of its own.
    conn = catalogue.connect(cfg.catalogue_db, create=False)
    real = B.inputs(conn, cfg)
    digest = catalogue.code_digest
    catalogue.code_digest = lambda: 'changed'
    try:
        assert B.inputs(conn, cfg) != real, 'a code change does not move the inputs'
        assert run(reuse=True), 'code changed, but it reused'
    finally:
        catalogue.code_digest = digest
    assert run(reuse=True), 'code changed back, but it reused the other build'

    for archive in (cfg.arz_paths[0], cfg.text_arc_paths[0]):
        st = os.stat(archive)
        os.utime(archive, ns=(st.st_atime_ns, st.st_mtime_ns + 1_000_000_000))
        try:
            assert run(reuse=True), f'{os.path.basename(archive)} changed, but it reused'
        finally:
            os.utime(archive, ns=(st.st_atime_ns, st.st_mtime_ns))
        assert run(reuse=True), 'archive restored, but it reused the other build'
    print('a code change, a game archive and a text archive each force a rebuild')

    # A stamp must never vouch for a bundle whose write did not finish.
    B.build = lambda conn: (_ for _ in ()).throw(RuntimeError('build died'))
    with open(bundle + '.inputs', 'w') as fh:
        fh.write('stale')
    try:
        B.main(out, reuse=True)
    except RuntimeError:
        pass
    assert not os.path.exists(bundle + '.inputs'), 'a failed build left its stamp'
    print('a failed build leaves no stamp')
finally:
    shutil.rmtree(out, ignore_errors=True)
