#!/usr/bin/env python3
"""shell.html + bundle.json -> one self-contained page.

The art goes into the CSS as data URIs and the records go into a JSON script
tag. Keeping them apart is what lets the stylesheet name a texture by role
(`__SLOT__`) instead of the page having to rewrite its own CSS at runtime.
"""
import json
import os

from .. import settings as S

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(S.ROOT, 'cache', 'browser')


def main():
    shell = open(os.path.join(HERE, 'shell.html')).read()
    b = json.load(open(os.path.join(OUT, 'bundle.json')))
    chrome = b['chrome']

    for token, value in [
        ('__ATLAS__', b['atlas']),
        ('__BORDER__', chrome['border']),
        ('__BORDER_SLICE__', str(chrome['borderSlice'])),
        ('__ORN_TOP__', chrome['ornTop']),
        ('__ORN_BOT__', chrome['ornBot']),
        ('__SLOT__', chrome['slot']),
        ('__DIVIDER__', chrome['divider']),
    ]:
        if token not in shell:
            raise SystemExit(f'{token} is not in the shell -- a renamed token '
                             f'would otherwise ship as a broken url()')
        shell = shell.replace(token, value)

    data = {k: b[k] for k in ('items', 'frames', 'sheet')}
    # `</` cannot appear raw inside a script element; < is the same string
    # to JSON.parse and cannot close the tag.
    payload = json.dumps(data, separators=(',', ':')).replace('</', '<\\u002f')
    shell = shell.replace('__BUNDLE__', payload)

    path = os.path.join(OUT, 'archive.html')
    open(path, 'w').write(shell)
    print(f'{os.path.getsize(path)/1e6:.2f} MB -> {path}')


if __name__ == '__main__':
    main()
