#!/usr/bin/env python3
"""shell.html + palette.json -> one page, wearing the browser's chrome.

⚠️ THE CHROME COMES FROM THE ITEM BROWSER'S BUNDLE, not from this build. The
two pages share a frame and only one of them assembles it, so `browser.build`
has to have run. They used to share an output directory, which hid the
dependency; now each writes its own and the borrow is named.
"""
import json
import os

from .. import settings as S

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(S.ROOT, 'cache', 'palette')


def main():
    shell = open(os.path.join(HERE, 'shell.html')).read()
    b = json.load(open(os.path.join(OUT, 'palette.json')))
    # The frame and flourish come from the Archive prototype's bundle rather
    # than being re-extracted: two pages wearing the same skin must wear the
    # same bytes, or "the game's gold" means two things.
    browser_bundle = os.path.join(S.ROOT, 'cache', 'browser', 'bundle.json')
    if not os.path.isfile(browser_bundle):
        raise SystemExit(
            f'no {browser_bundle}: this page wears the item browser\'s frame, '
            f'so run `python3 -m allostrias.browser.build` first.')
    chrome = json.load(open(browser_bundle))['chrome']

    sheetvars = '\n'.join(f'  --s{i}:url("{a["uri"]}");' for i, a in enumerate(b['atlases']))
    for token, value in [
        ('__SHEETVARS__', sheetvars),
        ('__BORDER__', chrome['border']),
        ('__BORDER_SLICE__', str(chrome['borderSlice'])),
        ('__ORN_TOP__', chrome['ornTop']),
    ]:
        if token not in shell:
            raise SystemExit(f'{token} is not in the shell')
        shell = shell.replace(token, value)

    data = {k: b[k] for k in ('groups', 'frames', 'sections', 'nTextures')}
    data['sheets'] = [a['size'] for a in b['atlases']]
    payload = json.dumps(data, separators=(',', ':')).replace('</', '<\\u002f')
    shell = shell.replace('__BUNDLE__', payload)

    path = os.path.join(OUT, 'palette.html')
    open(path, 'w').write(shell)
    print(f'{os.path.getsize(path)/1e6:.2f} MB -> {path}')


if __name__ == '__main__':
    main()
