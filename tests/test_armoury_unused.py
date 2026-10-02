"""Gate: nothing but the UI palette depends on the item browser ("Allostria's Armoury").

The user means to remove the Armoury (2026-10-02); the Gear Catalogue replaces it.
Until then nothing new may come to need it: no module outside allostrias/browser/
imports it or reads its build output, cache/browser/. The palette is the one
known dependant -- it wears the browser's frame (palette/assemble.py, and its
gate) -- and is named here so that removing the Armoury means moving that frame first.
"""
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PKG = os.path.join(ROOT, 'allostrias')
KNOWN = {os.path.join('allostrias', 'palette', 'assemble.py'),
         os.path.join('tests', 'test_palette_page.py')}
USES = re.compile(r"""from \.+browser\b|allostrias\.browser\b|import browser\b|['"]browser['"]\s*[,)]""")

found = set()
for top in (PKG, os.path.join(ROOT, 'tests')):
    for dirpath, dirs, files in os.walk(top):
        dirs[:] = [d for d in dirs if d != '__pycache__']
        if os.path.join('allostrias', 'browser') in dirpath:
            continue
        for f in files:
            if not f.endswith(('.py', '.js', '.html', '.sh')):
                continue
            p = os.path.join(dirpath, f)
            rel = os.path.relpath(p, ROOT)
            if rel in (os.path.join('tests', 'test_browser_page.py'),
                       os.path.join('tests', 'test_armoury_unused.py')):
                continue                  # the Armoury's own gate, and this one
            if USES.search(open(p, encoding='utf-8').read()):
                found.add(rel)

assert found <= KNOWN, f'depend on the Armoury: {sorted(found - KNOWN)}'
assert found == KNOWN, f'the palette no longer depends on the Armoury: drop it from KNOWN ({sorted(KNOWN - found)})'
print(f'only {", ".join(sorted(KNOWN))} depends on the Armoury\n\nPASS')
