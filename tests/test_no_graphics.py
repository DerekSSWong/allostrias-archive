"""No game graphics in tracked files.

The repo is public; Crate's art is not ours to redistribute. The same rule
that keeps the catalogue out of git -- it is Crate's data, derived from the
archives on the user's own install -- applies to every icon, texture and font
the game ships. Anything graphical the archive needs is extracted from the
player's own .arc files at run time and lands in cache/, which is ignored.

Nothing is committed today, so this is a tripwire rather than a cleanup. It
sniffs CONTENT first, because a file's extension is chosen by whoever added it
and a texture committed as `frame.dat` would pass an extension list. The
extension net catches the text formats (SVG) and empty placeholders that have
no magic to sniff.
"""
import os
import re
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from allostrias import settings as S               # noqa: E402

# Leading bytes that identify a raster image, a container the game uses, or a
# font. DDSR is Grim Dawn's own variant of the DDS header -- the .tex files
# carry it instead of the standard 'DDS ' magic, and a sniffer that only knows
# the standard one would wave every game texture through.
MAGIC = {
    b'\x89PNG\r\n\x1a\n': 'PNG',
    b'\xff\xd8\xff': 'JPEG',
    b'GIF87a': 'GIF',
    b'GIF89a': 'GIF',
    b'BM': 'BMP',
    b'DDS ': 'DDS texture',
    b'DDSR': 'DDS texture (Grim Dawn .tex)',
    b'RIFF': 'RIFF container (WebP)',
    b'\x00\x00\x01\x00': 'ICO',
    b'\x00\x01\x00\x00': 'TrueType font',
    b'OTTO': 'OpenType font',
    b'wOFF': 'WOFF font',
    b'wOF2': 'WOFF2 font',
    b'ARC\x00': 'Grim Dawn .arc archive',
}
# Formats with no usable magic: text (SVG) and whatever an empty placeholder
# would be. Extension is the only signal these have.
EXTENSIONS = {'.png', '.jpg', '.jpeg', '.gif', '.bmp', '.webp', '.ico',
              '.svg', '.dds', '.tex', '.tga', '.psd', '.ttf', '.otf',
              '.woff', '.woff2', '.fnt', '.arc'}

tracked = subprocess.run(['git', 'ls-files'], cwd=S.ROOT,
                         capture_output=True, text=True, check=True)
files = [f for f in tracked.stdout.splitlines() if f]
assert files, 'git ls-files returned nothing; is this a repo?'

found = []
for relpath in files:
    ext = os.path.splitext(relpath)[1].lower()
    if ext in EXTENSIONS:
        found.append(f'{relpath}: {ext} is a graphics format')
        continue
    try:
        with open(os.path.join(S.ROOT, relpath), 'rb') as fh:
            head = fh.read(16)
    except (IsADirectoryError, PermissionError, FileNotFoundError):
        continue
    for magic, what in MAGIC.items():
        if head.startswith(magic):
            found.append(f'{relpath}: content is {what}')
            break

# ---- and art that is not a file ------------------------------------------
# Sniffing bytes and extensions catches a committed .png. It does NOT catch the
# way this repo would actually leak art: the sheet's shell.html carries
# `__ATLAS__` and the build substitutes a base64 icon sheet into it, so one
# careless commit of a BUILT page would put every icon in git inside a tracked
# .html that opens as text. That is the likely accident here, not a stray PNG.
DATA_URI = re.compile(r'data:image/[a-z+]{2,10};base64,[A-Za-z0-9+/=]{256,}')
FONT_URI = re.compile(r'data:(?:font|application/(?:x-)?font)[^;]*;base64,'
                      r'[A-Za-z0-9+/=]{256,}')
for relpath in files:
    if os.path.splitext(relpath)[1].lower() not in (
            '.html', '.htm', '.js', '.css', '.md', '.json', '.py', '.svg'):
        continue
    try:
        text = open(os.path.join(S.ROOT, relpath), encoding='utf-8',
                    errors='replace').read()
    except (IsADirectoryError, PermissionError, FileNotFoundError):
        continue
    for pattern, what in ((DATA_URI, 'an embedded base64 image'),
                          (FONT_URI, 'an embedded base64 font')):
        n = len(pattern.findall(text))
        if n:
            found.append(f'{relpath}: {what} x{n} -- game art belongs in '
                         f'cache/, substituted at build time')

print(f'{len(files)} tracked files sniffed against {len(MAGIC)} magic '
      f'signatures, {len(EXTENSIONS)} extensions and 2 data-URI patterns')
for hit in found[:10]:
    print(f'  GRAPHICS {hit}')
assert not found, f'{len(found)} tracked file(s) are game graphics'

# The other half of the rule: graphics the archive extracts at run time go to
# cache/, and must not become committable by landing there. check-ignore is
# asked about a path that does not exist, which is the point -- the ignore has
# to cover the file BEFORE anything writes it.
for relpath in ('cache/icons/itemfx_blade.png', 'cache/fonts/gd.ttf'):
    result = subprocess.run(['git', 'check-ignore', '-q', relpath], cwd=S.ROOT)
    assert result.returncode == 0, (
        f'{relpath} is NOT gitignored; extracted graphics could be committed')
print('  extracted graphics under cache/ are gitignored')

print('\nNO GRAPHICS')
