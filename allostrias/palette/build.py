#!/usr/bin/env python3
"""Every UI texture Grim Dawn ships, grouped into design elements, on one sheet.

The palette shows EVERY texture rather than a curated selection -- a reference
sheet you cannot find something in is worse than no reference sheet. What makes
that browsable is group.py: the 4,139 files collapse to ~2,480 elements because
the filenames already say which four files are one button and which eight are
one frame.

Nine-slice groups get a synthesised extra tile -- the frame ASSEMBLED -- because
eight corner and edge fragments shown separately do not read as a frame, which
is the one thing someone looking for a frame needs to see.
"""
import base64
import io
import json
import os
import sys

from PIL import Image

from .group import group, NINE, CORNERS, EDGES
from .. import settings as S
from ..archive.textures import Textures

# The gd-lib path this used to add was never used -- no module was imported
# from it -- so it went with the move rather than being carried along.
OUT = os.path.join(S.ROOT, 'cache', 'palette')
CAP = 128            # longest side of a thumbnail; nothing is ever upscaled
SHEET_W = 1000

# Top-level namespace -> (section, human name). Order is the order the page
# reads in, and it leads with the windows this palette was asked for.
SECTIONS = [
    ('Character, inventory & stats', ['character']),
    ('Skills, masteries & devotion', ['skills']),
    ('Frames, buttons & shared controls', ['generic', 'styles']),
    ('Heads-up display', ['hud']),
    ('Vendors, crafting & storage', ['inventor', 'caravan', 'vendors', 'altarwindow',
                                     'cauldron', 'transmuter', 'stackwindow', 'tradewindow',
                                     'ascensionwindow']),
    ('Menus & front end', ['mainmenu', 'optionsmenu', 'loading', 'titlescreen']),
    ('World, quests & map', ['quest', 'conversationwindow', 'riftgatemap', 'mapaerial',
                             'shrine', 'inworld', 'achievements']),
    ('Everything else', []),          # catch-all, filled below
]


def png_b64(im, quantize=0):
    if quantize:
        im = im.quantize(colors=quantize, method=Image.FASTOCTREE)
    b = io.BytesIO()
    im.save(b, 'PNG', optimize=True)
    return 'data:image/png;base64,' + base64.b64encode(b.getvalue()).decode()


def thumb(im):
    w, h = im.size
    s = min(CAP / w, CAP / h, 1.0)
    return im if s == 1.0 else im.resize((max(1, int(w * s)), max(1, int(h * s))), Image.LANCZOS)


def assemble(parts):
    """A wordy or two-letter 9-slice painted at a readable size.

    Not a border-image: this is a flat composite, so a frame whose rail carries
    a centred ornament shows the ornament stretched -- which is exactly what
    border-image would also do to it, and worth seeing before choosing it.
    """
    def pick(*names):
        for n in names:
            if n in parts:
                return parts[n]
        return None
    lt = pick('lt', 'cornerupperleft', 'cornerlefttop')
    rt = pick('rt', 'cornerupperright', 'cornerrighttop')
    lb = pick('lb', 'cornerbottomleft', 'cornerleftbottom')
    rb = pick('rb', 'cornerbottomright', 'cornerrightbottom')
    ct = pick('ct', 'edgetop', 'bordertop')
    cb = pick('cb', 'edgebottom', 'borderbottom')
    lm = pick('lm', 'edgeleft', 'borderleft')
    rm = pick('rm', 'edgeright', 'borderright')
    if not all((lt, rt, lb, rb, ct, cb, lm, rm)):
        return None
    cw, chh = lt.size
    W, H = 260, 92
    if W < 2 * cw or H < 2 * chh:
        return None
    o = Image.new('RGBA', (W, H), (0, 0, 0, 0))
    fill = parts.get('filler')
    if fill:
        o.alpha_composite(fill.resize((W - 2 * cw, H - 2 * chh)), (cw, chh))
    o.alpha_composite(ct.resize((W - 2 * cw, chh)), (cw, 0))
    o.alpha_composite(cb.resize((W - 2 * cw, cb.height)), (cw, H - cb.height))
    o.alpha_composite(lm.resize((lm.width, H - 2 * chh)), (0, chh))
    o.alpha_composite(rm.resize((rm.width, H - 2 * chh)), (W - rm.width, chh))
    o.alpha_composite(lt, (0, 0)); o.alpha_composite(rt, (W - rt.width, 0))
    o.alpha_composite(lb, (0, H - lb.height)); o.alpha_composite(rb, (W - rb.width, H - rb.height))
    return o


def section_of(path):
    top = path.split('/')[0]
    for i, (_name, keys) in enumerate(SECTIONS):
        if top in keys:
            return i
    return len(SECTIONS) - 1


def main():
    os.makedirs(OUT, exist_ok=True)
    tx = Textures('UI.arc')
    paths = [n for n in sorted(tx.where) if n.endswith('.tex')]
    groups = group(paths)
    print(f'{len(paths)} textures -> {len(groups)} groups')

    tiles = []        # every image that goes on the sheet
    out_groups = []
    for g in groups:
        members, imgs = [], {}
        for p, label, mask in g['members']:
            try:
                im = tx.get(p)
            except Exception as e:
                print(f'  skip {p}: {e}')
                continue
            if im is None:
                continue
            imgs[label] = im
            members.append({'p': p, 'l': label, 'm': mask,
                            'w': im.width, 'h': im.height,
                            't': len(tiles)})
            tiles.append(thumb(im))
        if not members:
            continue
        entry = {'k': g['kind'], 'key': g['key'], 'sec': section_of(g['key']),
                 'mem': members}
        if g['kind'] == 'nine':
            built = assemble(imgs)
            if built is not None:
                entry['asm'] = len(tiles)
                tiles.append(built)
        out_groups.append(entry)

    # ONE PALETTE PER SHEET, and that is the whole reason there is more than
    # one sheet. A single 255-colour palette shared across all 4,148 tiles
    # posterises the devotion nebulae into blotches -- checked side by side --
    # because it has to cover gold chrome, flat grey slots and saturated skill
    # art at once. Split under a pixel budget, in group order so each sheet
    # stays stylistically local, and each gets 255 colours of its own; the
    # same devotion art then quantises invisibly. Costs ~1.8 MB over one
    # sheet, which is the right trade for art that is legible.
    BUDGET = 1_500_000
    seq = []
    for g in sorted(out_groups, key=lambda g: (g['sec'], g['key'])):
        seq += [m['t'] for m in g['mem']]
        if 'asm' in g:
            seq.append(g['asm'])
    seen = set(seq)
    seq += [i for i in range(len(tiles)) if i not in seen]

    batches, cur, area = [], [], 0
    for i in seq:
        a = tiles[i].width * tiles[i].height
        if area + a > BUDGET and cur:
            batches.append(cur); cur, area = [], 0
        cur.append(i); area += a
    if cur:
        batches.append(cur)

    frames = [None] * len(tiles)
    atlases = []
    for n, idx in enumerate(batches):
        order = sorted(idx, key=lambda i: (-tiles[i].height, -tiles[i].width))
        x = y = shelf = 0
        pos = {}
        for i in order:
            im = tiles[i]
            if x + im.width > SHEET_W:
                x, y, shelf = 0, y + shelf, 0
            pos[i] = (x, y)
            x += im.width
            shelf = max(shelf, im.height)
        s = Image.new('RGBA', (SHEET_W, y + shelf), (0, 0, 0, 0))
        for i, (px, py) in pos.items():
            s.paste(tiles[i], (px, py))
            frames[i] = [n, px, py, tiles[i].width, tiles[i].height]
        atlases.append({'uri': png_b64(s, quantize=255), 'size': list(s.size)})
        print(f'  sheet {n}: {s.size}  {len(idx)} tiles')

    assert all(f is not None for f in frames), 'a tile was packed onto no sheet'
    total = sum(len(a['uri']) for a in atlases)
    print(f'{len(atlases)} sheets, b64 {total/1e6:.2f} MB')

    bundle = {'groups': out_groups, 'frames': frames, 'atlases': atlases,
              'sections': [s[0] for s in SECTIONS], 'nTextures': len(paths)}
    path = os.path.join(OUT, 'palette.json')
    json.dump(bundle, open(path, 'w'), separators=(',', ':'))
    print(f'bundle {os.path.getsize(path)/1e6:.2f} MB')


if __name__ == '__main__':
    main()
