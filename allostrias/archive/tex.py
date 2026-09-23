"""Grim Dawn .tex -> PIL Image.

A .tex is a 12-byte header (`TEX\\x02`, version, payload length) followed by a
DDS whose 4-byte magic is `DDSR`, not the standard `DDS `. Inventory icons are
uncompressed 32bpp BGRA with no mipmaps; UI chrome is DXT-compressed and goes
through Pillow. Neither path guesses: an unrecognized pixel format raises.
"""
import io
import struct

from PIL import Image

_DDPF_FOURCC = 0x4
_DDPF_RGB = 0x40


def decode(data: bytes) -> Image.Image:
    if data[:4] != b'TEX\x02':
        raise ValueError('not a .tex')
    j = data.index(b'DDS')
    hdr = data[j:j + 128]
    if struct.unpack_from('<I', hdr, 4)[0] != 124:
        raise ValueError('not a 124-byte DDS header')
    height, width = struct.unpack_from('<2I', hdr, 12)
    pf_flags = struct.unpack_from('<I', hdr, 80)[0]
    fourcc = hdr[84:88]
    bpp = struct.unpack_from('<I', hdr, 88)[0]

    if pf_flags & _DDPF_FOURCC and fourcc.strip(b'\0'):
        # DXT/BC: Pillow's DDS plugin owns these, but only with the real magic.
        im = Image.open(io.BytesIO(b'DDS ' + data[j + 4:]))
        im.load()
        return im.convert('RGBA')

    if pf_flags & _DDPF_RGB and bpp in (32, 24):
        # The channel masks are all zero on these, so they cannot say the
        # order; it is BGR(A), matching every DXT-free texture in the set that
        # could be checked against its in-game appearance. 24bpp is the opaque
        # half (rules, fills, 1px borders) and carries no alpha at all.
        raw = 'BGRA' if bpp == 32 else 'BGR'
        mode = 'RGBA' if bpp == 32 else 'RGB'
        n = width * height * (bpp // 8)
        px = data[j + 128:j + 128 + n]
        if len(px) < n:
            raise ValueError(f'truncated {width}x{height}@{bpp}bpp payload')
        return Image.frombytes(mode, (width, height), px, 'raw', raw).convert('RGBA')

    raise ValueError(f'unsupported pixel format flags={pf_flags:#x} fourcc={fourcc!r} bpp={bpp}')
