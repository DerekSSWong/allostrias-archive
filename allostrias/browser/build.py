#!/usr/bin/env python3
"""Build the data + art bundle the item browser is written against.

  what exists         cache/catalogue.sqlite   which items there are
  what it says        the stat-line renderer   .dbr fields as tooltip prose
  what it looks like  resources/*.arc          icons and chrome, via archive/tex

Records come from `archive/records.py` -- the archives themselves, not gd-lib's
`.extracted/` tree, which this used to read.

⚠️ THE ONE REMAINING BORROW: the stat-line renderer is still gd-lib's
`item_stats`, imported from the game directory. It is the last thing in this
repo that needs another project present, and porting it is the open work. The
text it is fed now comes from `Records.text()`, which reproduces the
`.extracted` files byte for byte (tests/test_records.py), so the port can
happen without the input changing under it.
"""
import base64
import io
import json
import os
import sqlite3
import sys

from PIL import Image, ImageChops

from .. import settings as S
from ..archive.records import Records
from ..archive.textures import Textures

cfg = S.load()
RECORDS = Records(cfg.arz_paths)
DB = os.path.join(S.ROOT, 'cache', 'catalogue.sqlite')
# Build output, and it carries the icon atlas -- Crate's art, which cache/
# keeps out of a public repo.
OUT = os.path.join(S.ROOT, 'cache', 'browser')

# The stat-line renderer, still gd-lib's. Imported here and nowhere else, so
# there is exactly one line to delete when the port lands.
sys.path.insert(0, os.path.join(cfg.game, '.gdlib'))
import item_stats                                     # noqa: E402
TIERS = ('Legendary', 'Epic')


def png_b64(im: Image.Image, quantize: int = 0) -> str:
    """`quantize` trades colour depth for bytes, and only the atlas needs it:
    at 255 colours the icon sheet is 5x smaller and, checked against the
    original, indistinguishable. The chrome is a handful of kilobytes and keeps
    full depth, where banding on a smooth gold gradient would show."""
    if quantize:
        im = im.quantize(colors=quantize, method=Image.FASTOCTREE)
    b = io.BytesIO()
    im.save(b, 'PNG', optimize=True)
    return 'data:image/png;base64,' + base64.b64encode(b.getvalue()).decode()


# ---------------------------------------------------------------- items ----

def load_items(conn):
    rows = conn.execute(f"""
        select i.id, coalesce(i.display_name, i.name) nm, i.path, i.slot, i.family,
               i.classification, i.level_req, i.is_mi, i.style, s.name set_name,
               (select txt from item_stat where item_id=i.id and field='bitmap') icon
        from item i
        left join item_set s on s.path = i.set_path
        where i.is_equipment = 1
          and i.classification in ({','.join('?' * len(TIERS))})
          and coalesce(i.display_name, i.name) is not null
        """, TIERS).fetchall()
    items = []
    for r in rows:
        txt = RECORDS.text(r['path'])
        if txt is None:
            continue
        lines = item_stats.process_stats(txt)
        skill = item_stats.resolve_item_skill(txt)
        base = item_stats.base_weapon_damage(txt) + item_stats.base_armor(txt)
        if not (lines or skill or base):
            continue                      # a record with nothing to print
        items.append({
            'n': r['nm'], 'sl': r['slot'], 'fam': r['family'], 'c': r['classification'],
            'lv': r['level_req'], 'mi': bool(r['is_mi']), 'st': r['style'],
            'set': r['set_name'], 'icon': r['icon'],
            'base': base, 'lines': lines, 'skill': skill,
            'path': r['path'],
        })
    return items


# ---------------------------------------------------------------- atlas ----

def build_atlas(items, tx):
    """Every distinct icon on one sheet, shelf-packed by height.

    One sheet rather than one data URI per icon: the icons share a palette and
    a compressor window, and 1700 separate base64 blobs cost several times what
    the sheet does for the same pixels.
    """
    want = sorted({i['icon'] for i in items if i['icon']})
    got = {}
    for path in want:
        im = tx.get(path)
        if im is None:
            continue                      # absent from every archive layer
        got[path] = im

    order = sorted(got, key=lambda p: (-got[p].height, -got[p].width))
    SHEET_W = 1024
    x = y = shelf = 0
    place = {}
    for p in order:
        im = got[p]
        if x + im.width > SHEET_W:
            x, y, shelf = 0, y + shelf, 0
        place[p] = (x, y)
        x += im.width
        shelf = max(shelf, im.height)
    sheet = Image.new('RGBA', (SHEET_W, y + shelf), (0, 0, 0, 0))
    for p, (px, py) in place.items():
        sheet.paste(got[p], (px, py))
    frames = {p: [x_, y_, got[p].width, got[p].height] for p, (x_, y_) in place.items()}
    return sheet, frames


# --------------------------------------------------------------- chrome ----

def nine_slice(im, corner, rail_xy, strip=8):
    """A (2*corner+strip) square sheet laid out for CSS border-image.

    Sampled from a real frame rather than redrawn: corners come from the
    frame's own corners, edges from a stretch of rail chosen to be free of the
    centred ornament, which border-image would smear.
    """
    W, H = im.size
    rx, ry = rail_xy
    C, R = corner, strip
    s = Image.new('RGBA', (C * 2 + R, C * 2 + R), (0, 0, 0, 0))
    s.paste(im.crop((0, 0, C, C)), (0, 0))
    s.paste(im.crop((W - C, 0, W, C)), (C + R, 0))
    s.paste(im.crop((0, H - C, C, H)), (0, C + R))
    s.paste(im.crop((W - C, H - C, W, H)), (C + R, C + R))
    s.paste(im.crop((rx, 0, rx + R, C)), (C, 0))
    s.paste(im.crop((rx, H - C, rx + R, H)), (C, C + R))
    s.paste(im.crop((0, ry, C, ry + R)), (0, C))
    s.paste(im.crop((W - C, ry, W, ry + R)), (C + R, C))
    s.paste(im.crop((rx, ry, rx + R, ry + R)), (C, C))
    return s


def build_chrome(ui):
    out = {}

    # Panel border: the main menu's 8-piece set, which is already a clean
    # 9-slice with a flat rail -- unlike the prompt frame, whose stepped arch
    # and centred ornament cannot survive being stretched.
    p = {k: ui.get(f'mainmenu/border_{k}.tex') for k in
         ('lt', 'ct', 'rt', 'lm', 'rm', 'lb', 'cb', 'rb')}
    C = p['lt'].width
    R = 8
    s = Image.new('RGBA', (C * 2 + R, C * 2 + R), (0, 0, 0, 0))
    s.paste(p['lt'], (0, 0))
    s.paste(p['rt'], (C + R, 0))
    s.paste(p['lb'], (0, C + R))
    s.paste(p['rb'], (C + R, C + R))
    s.paste(p['ct'].crop((400, 0, 400 + R, C)), (C, 0))
    s.paste(p['cb'].crop((400, 0, 400 + R, C)), (C, C + R))
    s.paste(p['lm'].crop((0, 400, C, 400 + R)), (0, C))
    s.paste(p['rm'].crop((0, 400, C, 400 + R)), (C + R, C))
    out['border'] = png_b64(s)
    out['borderSlice'] = C

    # The prompt frame's centred flourishes, cropped to the ornament alone --
    # a taller crop drags in the frame's own inner band, which reads as a bar
    # floating under the masthead.
    frame = ui.get('generic/promptbox/prompt_windowbackgroundimage.tex')
    out['ornTop'] = png_b64(frame.crop((92, 0, 254, 25)))
    out['ornBot'] = png_b64(frame.crop((92, frame.height - 25, 254, frame.height)))

    # The inventory tile ships as a near-white gradient because the game
    # multiplies it by the slot's own tint at draw time. Baking that tint here
    # keeps the CSS honest: one background, no overlay pretending to be one.
    slot = ui.get('character/itembackground.tex')
    tint = Image.new('RGB', slot.size, (58, 50, 39))
    out['slot'] = png_b64(Image.merge('RGBA', (
        *ImageChops.multiply(slot.convert('RGB'), tint).split(), slot.split()[3])))
    out['slotLegendary'] = png_b64(ui.get('character/itembackgroundlegendary.tex'))
    out['divider'] = png_b64(ui.get('generic/listboxdivider.tex'))
    for state in ('up', 'over', 'down'):
        out['btn' + state.title()] = png_b64(ui.get(f'generic/buttonthin01_{state}.tex'))
    return out


def main():
    os.makedirs(OUT, exist_ok=True)
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    items = load_items(conn)
    print(f'items {len(items)}')

    tx = Textures('Items.arc')
    sheet, frames = build_atlas(items, tx)
    print(f'atlas {sheet.size} icons {len(frames)}')
    sheet.save(os.path.join(OUT, 'atlas.png'), optimize=True)
    atlas_uri = png_b64(sheet, quantize=255)
    print(f'atlas b64 {len(atlas_uri)/1e6:.2f} MB')

    ui = Textures('UI.arc')
    chrome = build_chrome(ui)
    print('chrome b64 %.2f MB' % (sum(len(v) for v in chrome.values() if isinstance(v, str)) / 1e6))

    bundle = {'items': items, 'frames': frames, 'atlas': atlas_uri,
              'sheet': list(sheet.size), 'chrome': chrome}
    path = os.path.join(OUT, 'bundle.json')
    with open(path, 'w') as f:
        json.dump(bundle, f, separators=(',', ':'))
    print(f'bundle {os.path.getsize(path)/1e6:.2f} MB -> {path}')


if __name__ == '__main__':
    main()
