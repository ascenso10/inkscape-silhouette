# (c) 2026 - Bitmap support for the print & cut helpers.
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
"""
Bitmap helpers shared by the cut-contour and the layout extensions:

* load_image():  decode an <image> href (data: URI or file) to RGBA floats.
                 Uses Pillow when available, otherwise a small built-in PNG
                 decoder (JPEG then needs Pillow).
* ink_mask():    which pixels carry ink. White counts as "no ink": temporary
                 tattoo paper prints no white, so white areas stay skin.
* trace():       monochrome vectorisation, returns polygons (even-odd fill).
"""

import base64
import os
import struct
import zlib
from urllib.parse import unquote, urlparse

import numpy as np

from silhouette.Outline import _contours, _simplify

__all__ = ["load_image", "ink_mask", "darkness", "trace", "image_placement"]


# ---------------------------------------------------------------- decode ----

def _read_href(href, base_dir):
    href = (href or "").strip()
    if href.startswith("data:"):
        head, _, data = href.partition(",")
        if ";base64" in head:
            return base64.b64decode(data)
        return unquote(data).encode("latin-1")
    path = href
    if href.startswith("file:"):
        path = unquote(urlparse(href).path)
        if os.name == "nt" and path.startswith("/") and len(path) > 2 and path[2] == ":":
            path = path[1:]
    if not os.path.isabs(path) and base_dir:
        path = os.path.join(base_dir, path)
    with open(path, "rb") as f:
        return f.read()


def _decode_with_pil(data):
    try:
        from PIL import Image as PILImage
    except ImportError:
        return None
    import io
    im = PILImage.open(io.BytesIO(data))
    im = im.convert("RGBA")
    return np.asarray(im, dtype=np.float32) / 255.0


def _paeth_row(raw, prev, bpp):
    out = bytearray(raw)
    for i in range(len(out)):
        a = out[i - bpp] if i >= bpp else 0
        b = prev[i]
        c = prev[i - bpp] if i >= bpp else 0
        p = a + b - c
        pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
        pred = a if (pa <= pb and pa <= pc) else (b if pb <= pc else c)
        out[i] = (out[i] + pred) & 0xFF
    return out


def _avg_row(raw, prev, bpp):
    out = bytearray(raw)
    for i in range(len(out)):
        a = out[i - bpp] if i >= bpp else 0
        out[i] = (out[i] + ((a + prev[i]) >> 1)) & 0xFF
    return out


def _decode_png(data):
    """Minimal PNG decoder: 8/16 bit, colour types 0, 2, 3, 4, 6, not interlaced."""
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError("not a PNG file")
    pos, idat, plte, trns = 8, [], None, None
    w = h = depth = ctype = interlace = None
    while pos < len(data):
        length, = struct.unpack(">I", data[pos:pos + 4])
        kind = data[pos + 4:pos + 8]
        body = data[pos + 8:pos + 8 + length]
        pos += 12 + length
        if kind == b"IHDR":
            w, h, depth, ctype, _, _, interlace = struct.unpack(">IIBBBBB", body)
        elif kind == b"PLTE":
            plte = np.frombuffer(body, dtype=np.uint8).reshape(-1, 3)
        elif kind == b"tRNS":
            trns = body
        elif kind == b"IDAT":
            idat.append(body)
        elif kind == b"IEND":
            break
    if interlace:
        raise ValueError("interlaced PNG needs Pillow")
    if depth not in (8, 16):
        raise ValueError("PNG bit depth %d needs Pillow" % depth)
    chans = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}[ctype]
    bpp = chans * depth // 8
    stride = w * bpp
    raw = zlib.decompress(b"".join(idat))
    rows = np.zeros((h, stride), dtype=np.uint8)
    prev = bytearray(stride)
    for y in range(h):
        f = raw[y * (stride + 1)]
        line = raw[y * (stride + 1) + 1:(y + 1) * (stride + 1)]
        if f == 0:
            cur = bytearray(line)
        elif f == 1:
            arr = np.frombuffer(line, dtype=np.uint8).reshape(-1, bpp).astype(np.int64)
            cur = bytearray((np.cumsum(arr, axis=0) & 0xFF).astype(np.uint8).tobytes())
        elif f == 2:
            cur = bytearray(((np.frombuffer(line, dtype=np.uint8).astype(np.int64)
                              + np.frombuffer(bytes(prev), dtype=np.uint8)) & 0xFF).astype(np.uint8).tobytes())
        elif f == 3:
            cur = _avg_row(line, prev, bpp)
        elif f == 4:
            cur = _paeth_row(line, prev, bpp)
        else:
            raise ValueError("bad PNG filter")
        rows[y] = np.frombuffer(bytes(cur), dtype=np.uint8)
        prev = cur
    if depth == 16:
        px = rows.reshape(h, w, chans, 2)[..., 0].astype(np.float32) / 255.0
    else:
        px = rows.reshape(h, w, chans).astype(np.float32) / 255.0
    rgba = np.ones((h, w, 4), dtype=np.float32)
    if ctype == 3:
        idx = rows.reshape(h, w).astype(int)
        rgba[..., :3] = plte[idx] / 255.0
        if trns is not None:
            alpha = np.ones(256, dtype=np.float32)
            t = np.frombuffer(trns, dtype=np.uint8)
            alpha[:len(t)] = t / 255.0
            rgba[..., 3] = alpha[idx]
    elif ctype == 0:
        rgba[..., :3] = px[..., :1]
    elif ctype == 4:
        rgba[..., :3] = px[..., :1]
        rgba[..., 3] = px[..., 1]
    elif ctype == 2:
        rgba[..., :3] = px
    else:
        rgba[...] = px
    return rgba


def load_image(href, base_dir=None):
    """Decode an <image> href to an (H, W, 4) float32 RGBA array in 0..1."""
    data = _read_href(href, base_dir)
    rgba = _decode_with_pil(data)
    if rgba is not None:
        return rgba
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return _decode_png(data)
    raise ValueError("This image format needs the Pillow library; use a PNG or an SVG instead.")


# ------------------------------------------------------------ analysis ----

def _luminance(rgba):
    return 0.2126 * rgba[..., 0] + 0.7152 * rgba[..., 1] + 0.0722 * rgba[..., 2]


def darkness(rgba):
    """0 (white / transparent) .. 1 (opaque black)."""
    return rgba[..., 3] * (1.0 - _luminance(rgba))


def ink_mask(rgba, white=0.92):
    """Pixels that print: opaque enough and not (near) white."""
    return (rgba[..., 3] > 0.5) & (_luminance(rgba) < white)


def trace(rgba, threshold=0.5, min_area_px=6.0, simplify_px=0.35):
    """Monochrome vectorisation.  Returns polygons in image pixel coordinates
    (x right, y down, pixel k spans [k, k+1]), to be filled with even-odd."""
    d = darkness(rgba).astype(np.float64)
    fld = np.pad(threshold - d, 1, constant_values=1.0)
    polys = []
    for p in _contours(fld):
        p = p - 0.5                          # padded index -> pixel-centre coordinates
        if abs(_area(p)) < min_area_px:
            continue
        polys.append(_simplify(p, simplify_px))
    return polys


def _area(p):
    x, y = p[:, 0], p[:, 1]
    return 0.5 * float(np.dot(x, np.roll(y, -1)) - np.dot(np.roll(x, -1), y))


def image_placement(x, y, width, height, img_w, img_h, par="xMidYMid meet"):
    """Affine (a, b, c, d, e, f) mapping image pixel coords to the element's
    user space, honouring preserveAspectRatio."""
    sx, sy = width / float(img_w), height / float(img_h)
    par = (par or "xMidYMid meet").strip()
    if par.startswith("none"):
        return (sx, 0.0, 0.0, sy, x, y)
    align, _, mode = par.partition(" ")
    s = max(sx, sy) if mode.strip() == "slice" else min(sx, sy)
    dw, dh = width - img_w * s, height - img_h * s
    fx = {"xMin": 0.0, "xMid": 0.5, "xMax": 1.0}.get(align[:4], 0.5)
    fy = {"YMin": 0.0, "YMid": 0.5, "YMax": 1.0}.get(align[4:8], 0.5)
    return (s, 0.0, 0.0, s, x + dw * fx, y + dh * fy)
