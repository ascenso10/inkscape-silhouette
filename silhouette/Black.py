# (c) 2026 - Convert artwork to solid black for single-colour printing.
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
"""
Solid black conversion (pure numpy).

Colour artwork is composited the way it looks (painter's order, fills,
strokes, opacity, bitmaps), every point darker than a threshold becomes
black and everything lighter becomes "no ink", and the result is traced to
black even-odd polygons.  Compositing first matters: a white shape lying on
a dark one must become a hole, which simply painting every shape black would
lose.

The conversion also reports what it changed, so doubtful cases can be sent
for review:
  lost      share of the visible coloured ink that became "no ink"
  merged    share of colour boundaries inside the ink that disappeared
            (areas only told apart by their colour became one black blob)
  coverage  share of the design's bounding box that is black
"""

import math
import numpy as np

from silhouette.Outline import (Shape, _Grid, _fill_mask, _line_mask, _edt_sq, _contours,
                                _simplify, _bbox_union)

__all__ = ["Paint", "PaintShape", "PaintImage", "composite", "to_black", "BlackResult"]

WHITE_LUM = 0.92          # lighter than this counts as paper / skin


class Paint:
    def __init__(self, rgb, alpha=1.0):
        self.rgb = np.asarray(rgb, dtype=np.float32).reshape(3)
        self.alpha = float(alpha)

    def darkness(self):
        return self.alpha * (1.0 - _lum(self.rgb))


class PaintShape:
    """Vector geometry (a silhouette.Outline.Shape, in mm) with its paints."""

    def __init__(self, shape, fill=None, stroke=None):
        self.shape, self.fill, self.stroke = shape, fill, stroke

    def bbox(self):
        return self.shape.bbox()


class PaintImage:
    """Bitmap: rgba (H, W, 4) floats, affine (a, b, c, d, e, f) pixel -> mm."""

    def __init__(self, rgba, affine):
        self.rgba = np.asarray(rgba, dtype=np.float32)
        self.affine = tuple(float(v) for v in affine)

    def bbox(self):
        a, b, c, d, e, f = self.affine
        h, w = self.rgba.shape[:2]
        pts = [(0, 0), (w, 0), (0, h), (w, h)]
        xs = [a * x + c * y + e for x, y in pts]
        ys = [b * x + d * y + f for x, y in pts]
        return (min(xs), min(ys), max(xs), max(ys))


def _lum(rgb):
    rgb = np.asarray(rgb)
    return 0.2126 * rgb[..., 0] + 0.7152 * rgb[..., 1] + 0.0722 * rgb[..., 2]


def _blend(canvas, mask, rgb, alpha):
    if alpha <= 0 or not mask.any():
        return
    canvas[mask] = canvas[mask] * (1.0 - alpha) + rgb * alpha


def _image_layer(grid, item):
    """rgba of the bitmap resampled on the grid (nearest), alpha 0 outside."""
    out = np.zeros((grid.h, grid.w, 4), dtype=np.float32)
    a, b, c, d, e, f = item.affine
    det = a * d - b * c
    if det == 0:
        return out
    X = grid.x0 + (np.arange(grid.w) + 0.5) / grid.res
    Y = grid.y0 + (np.arange(grid.h) + 0.5) / grid.res
    X, Y = np.meshgrid(X - e, Y - f)
    u = np.floor((d * X - c * Y) / det).astype(int)
    v = np.floor((-b * X + a * Y) / det).astype(int)
    h, w = item.rgba.shape[:2]
    ok = (u >= 0) & (u < w) & (v >= 0) & (v < h)
    out[ok] = item.rgba[v[ok], u[ok]]
    return out


def composite(items, res, margin_mm=1.0, max_px=6000):
    """Render the items (painter's order) on white.  Returns (grid, rgb)."""
    bb = _bbox_union([it.bbox() for it in items])
    if bb is None:
        return None, None
    span = max(bb[2] - bb[0], bb[3] - bb[1]) + 2 * margin_mm
    res = min(float(res), max_px / max(span, 1e-6))
    x0, y0 = bb[0] - margin_mm, bb[1] - margin_mm
    W = int(math.ceil((bb[2] - bb[0] + 2 * margin_mm) * res))
    H = int(math.ceil((bb[3] - bb[1] + 2 * margin_mm) * res))
    grid = _Grid(x0, y0, W, H, res)
    canvas = np.ones((H, W, 3), dtype=np.float32)
    for it in items:
        if isinstance(it, PaintImage):
            layer = _image_layer(grid, it)
            al = layer[..., 3:4]
            canvas[...] = canvas * (1.0 - al) + layer[..., :3] * al
            continue
        s = it.shape
        if it.fill is not None and it.fill.alpha > 0:
            polys = [p for p in s.polylines if len(p) >= 3]
            if polys:
                _blend(canvas, _fill_mask(grid, polys, s.evenodd), it.fill.rgb, it.fill.alpha)
        if it.stroke is not None and it.stroke.alpha > 0 and s.stroke_mm > 0:
            line = _line_mask(grid, s.polylines, s.closed)
            hw = s.stroke_mm * res / 2.0
            m = line if hw <= 0.75 else (_edt_sq(line, hw + 1) <= hw * hw)
            _blend(canvas, m, it.stroke.rgb, it.stroke.alpha)
    return grid, canvas


class BlackResult:
    def __init__(self, polygons, lost, merged, coverage, all_dark):
        self.polygons = polygons      # list of (N, 2) arrays in mm, even-odd fill
        self.lost = lost
        self.merged = merged
        self.coverage = coverage
        self.all_dark = all_dark      # every paint is dark: recolouring alone is exact

    def warnings(self, lost_max=0.15, merged_max=0.30, coverage_max=0.85):
        w = []
        if self.lost > lost_max:
            w.append("%d%% of the coloured artwork is too light and was dropped (lower the threshold to keep lighter colours)"
                     % round(100 * self.lost))
        if self.merged > merged_max:
            w.append("%d%% of the colour boundaries were lost: areas told apart only by colour became one black area"
                     % round(100 * self.merged))
        if self.coverage > coverage_max:
            w.append("the result is almost entirely black (%d%%): a coloured background may have become a block"
                     % round(100 * self.coverage))
        return w


def paints_all_dark(items, threshold):
    for it in items:
        if isinstance(it, PaintImage):
            return False
        for p in (it.fill, it.stroke if it.shape.stroke_mm > 0 else None):
            if p is not None and p.alpha > 0 and p.darkness() < threshold:
                return False
    return True


def to_black(items, res=20.0, threshold=0.5, min_area_mm2=0.02, simplify_mm=0.02):
    """Composite, threshold and trace.  Returns BlackResult (polygons in mm)."""
    grid, rgb = composite(items, res)
    if grid is None:
        return BlackResult([], 0.0, 0.0, 0.0, True)
    dark = 1.0 - _lum(rgb)
    black = dark >= threshold
    inked = dark > (1.0 - WHITE_LUM)

    n_ink = int(inked.sum())
    lost = float((inked & ~black).sum()) / n_ink if n_ink else 0.0

    # colour boundaries inside the ink that end up between two black pixels
    diff_x = np.abs(rgb[:, 1:] - rgb[:, :-1]).max(axis=2) > 0.2
    diff_y = np.abs(rgb[1:] - rgb[:-1]).max(axis=2) > 0.2
    ink_x = inked[:, 1:] & inked[:, :-1] & diff_x
    ink_y = inked[1:] & inked[:-1] & diff_y
    lost_x = ink_x & black[:, 1:] & black[:, :-1]
    lost_y = ink_y & black[1:] & black[:-1]
    n_edges = int(ink_x.sum() + ink_y.sum())
    merged = float(lost_x.sum() + lost_y.sum()) / n_edges if n_edges else 0.0

    ys, xs = np.nonzero(inked)
    if len(ys):
        box = (ys.max() - ys.min() + 1) * (xs.max() - xs.min() + 1)
        coverage = float(black.sum()) / box
    else:
        coverage = 0.0

    fld = np.pad(threshold - dark.astype(np.float64), 1, constant_values=1.0)
    min_px = min_area_mm2 * grid.res * grid.res
    polys = []
    for p in _contours(fld):
        mm = grid.to_mm(p[:, 0] - 0.5, p[:, 1] - 0.5)
        if abs(_area(p)) < min_px:
            continue
        polys.append(_simplify(mm, simplify_mm))
    return BlackResult(polys, lost, merged, coverage, paints_all_dark(items, threshold))


def _area(p):
    x, y = p[:, 0], p[:, 1]
    return 0.5 * float(np.dot(x, np.roll(y, -1)) - np.dot(np.roll(x, -1), y))
