#!/usr/bin/env python3
"""Serve the character sheet locally, with a working Refresh button.

    python3 -m allostrias.sheet.serve [port]   # default 8765

WHY THIS EXISTS RATHER THAN A BUTTON ON THE PUBLISHED ARTIFACT: an artifact is
a static page on claude.ai inside a sandbox whose CSP blocks fetch/XHR to every
origin, localhost included. It cannot run Python, cannot read
cache/profile.sqlite, and cannot re-read a save. A button
there could only ever pretend. Served from here, the same page can just ask.

The page carries the button either way and feature-detects: it probes /alive at
load and reveals the button only if something answers. On the published
artifact that probe is refused and the button stays hidden, so one HTML file is
correct in both places.
"""
import json
import os
import sys
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

from . import assemble
from . import build
from ..affixes import build as affix_build
from .. import settings as S
from ..db import character

BUNDLE = os.path.join(S.ROOT, 'cache', 'sheet')


def refresh():
    """Re-read the saves into profile.sqlite, then rebuild the page's bundle.

    Two steps and they are not the same one. `character.refresh` is the
    archive's own: it re-reads every player.gdc into the character_* tables,
    which are a MIRROR and are refilled wholesale, so a character deleted in
    game leaves the database here. The rebuild that follows is this page's,
    turning those tables plus the catalogue into what the sheet renders.
    """
    t0 = time.time()
    cfg = S.load()
    counts = character.refresh(cfg)
    build.main()
    assemble.main()
    b = json.load(open(os.path.join(BUNDLE, 'sheet.json')))
    return {
        'ok': True,
        'seconds': round(time.time() - t0, 2),
        'unreadable': counts.get('unreadable', 0),
        'characters': b['characters'],
        'frames': b['frames'],
        'sheetSize': b['sheetSize'],
        'atlas': b['atlas'],
    }


class Handler(BaseHTTPRequestHandler):
    def _send(self, code, body, ctype):
        data = body if isinstance(body, bytes) else body.encode()
        self.send_response(code)
        self.send_header('Content-Type', ctype)
        self.send_header('Content-Length', str(len(data)))
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path.startswith('/alive'):
            return self._send(200, json.dumps({'ok': True}), 'application/json')
        if self.path in ('/', '/index.html'):
            p = os.path.join(BUNDLE, 'character_sheet.html')
            if not os.path.exists(p):
                return self._send(503, 'Run build.py and assemble.py first.',
                                  'text/plain')
            return self._send(200, open(p, 'rb').read(), 'text/html; charset=utf-8')
        self._send(404, 'no', 'text/plain')

    def do_POST(self):
        if not self.path.startswith('/refresh'):
            return self._send(404, 'no', 'text/plain')
        try:
            out = refresh()
        except Exception as e:
            # The page shows this. A refresh that fails silently would leave
            # stale numbers looking fresh, which is the whole risk here.
            return self._send(500, json.dumps({'ok': False, 'error': f'{type(e).__name__}: {e}'}),
                              'application/json')
        self._send(200, json.dumps(out), 'application/json')

    def log_message(self, fmt, *args):
        sys.stderr.write('  %s\n' % (fmt % args))


def main():
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8765
    print(f'building once before serving…')
    # The affix corpus reads only the catalogue, so a save refresh never moves
    # it: built once here, not on every Refresh.
    affix_build.main()
    print(f"  {refresh()['seconds']}s")
    print(f'http://localhost:{port}')
    HTTPServer(('127.0.0.1', port), Handler).serve_forever()


if __name__ == '__main__':
    main()
