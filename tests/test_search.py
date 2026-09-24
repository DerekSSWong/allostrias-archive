#!/usr/bin/env python3
"""The search engine the Affixes view ships is gd-lib's, verbatim.

allostrias/affixes/search.js and search_conformance.js are COPIES of gd-lib's,
because allostrias may not need gd-lib to build. A copy nobody compares is how
three hand-kept engines drifted before gd-lib made them one, so:

  - the conformance cases run here against the copy in this repo, and
    allostrias/sheet/check.js runs them again against the copy the built page
    carries;
  - when gd-lib is checked out beside this repo, both files must be
    byte-identical to its. SKIPS that half loudly when it is not.
"""
import os
import shutil
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from _oracle import ROOT, sibling                        # noqa: E402

HERE = os.path.join(ROOT, 'allostrias', 'affixes')
PAIRS = (('search.js', 'search.js'),
         ('search_conformance.js', os.path.join('tools', 'search_conformance.js')))

if shutil.which('node') is None:
    print('SKIPPED -- no node, so the search engine is UNCHECKED in this tree.')
    raise SystemExit(0)

script = ("require(process.argv[1]);"
          "const r=require(process.argv[2])(globalThis.GDSearch,'allostrias copy');"
          "r.fails.forEach(f=>console.error('FAIL: '+f));"
          "console.log(r.count+' cases');process.exit(r.fails.length?1:0);")
r = subprocess.run(['node', '-e', script, os.path.join(HERE, 'search.js'),
                    os.path.join(HERE, 'search_conformance.js')],
                   capture_output=True, text=True)
print(r.stdout.strip(), r.stderr.strip())
assert r.returncode == 0, 'the copied search engine fails its own conformance cases'

lib = sibling('.gdlib')
if not os.path.isfile(os.path.join(lib, 'search.js')):
    print(f'SKIPPED PART -- no gd-lib at {lib}: the copies are UNCOMPARED in this tree')
else:
    for mine, theirs in PAIRS:
        a = open(os.path.join(HERE, mine), 'rb').read()
        b = open(os.path.join(lib, theirs), 'rb').read()
        assert a == b, f'{mine} has drifted from gd-lib\'s {theirs}: copy it again'
    print('both files byte-identical to gd-lib')
print('\nSEARCH OK')
