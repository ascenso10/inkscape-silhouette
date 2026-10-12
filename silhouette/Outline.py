# (c) 2026 - Automatic cut-contour generation for print & cut workflows.
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
"""
Pure numpy implementation of an automatic "cut contour" (offset outline)
around artwork, used by silhouette_outline.py.

Pipeline (all distances in mm, internally on a pixel grid of `res` px/mm):

1. Each design ("item") is rasterised into an ink mask (fills honour the
   nonzero / evenodd rule, strokes are thickened to their real width).
2. A truncated Euclidean distance field to the ink is computed per item.
3. Neighbouring items compete for the space between them: each pixel goes to
   the closest item (a Voronoi split), so designs packed tightly on a sheet
   still get one separate contour each, which never cross each other.
4. The contour at `offset` mm is traced with sub-pixel marching squares,
   holes are dropped (a sticker-style outer cut) and the polygon simplified.

No dependency besides numpy, which ships with Inkscape on every platform.
"""

import math
import numpy as np

__all__ = ["Shape", "RasterShape", "compute_outlines", "compute_cut_paths"]


class Shape:
    """One SVG path already flattened to polylines, in mm.

    polylines: list of (N, 2) float arrays
    closed:    list of bool, one per polyline
    fill:      bool - the shape has a visible fill
    evenodd:   bool - fill-rule is evenodd (default nonzero)
    stroke_mm: float - visible stroke width in mm (0 = no stroke)
    """

    def __init__(self, polylines, closed=None, fill=True, evenodd=False, stroke_mm=0.0):
        self.polylines = [np.asarray(p, dtype=float).reshape(-1, 2) for p in polylines]
        self.closed = list(closed) if closed is not None else [True] * len(self.polylines)
        self.fill = fill
        self.evenodd = evenodd
        self.stroke_mm = float(stroke_mm or 0.0)

    def bbox(self):
        pts = [p for p in self.polylines if len(p)]
        if not pts:
            return None
        a = np.vstack(pts)
        h = self.stroke_mm / 2.0
        return (a[:, 0].min() - h, a[:, 1].min() - h, a[:, 0].max() + h, a[:, 1].max() + h)


class RasterShape:
    """Ink given as a bitmap: mask (H, W) bool, and the SVG-style affine
    (a, b, c, d, e, f) mapping image pixel coordinates to mm."""

    def __init__(self, mask, affine):
        self.mask = np.asarray(mask, dtype=bool)
        self.affine = tuple(float(v) for v in affine)

    def bbox(self):
        a, b, c, d, e, f = self.affine
        h, w = self.mask.shape
        xs = [a * x + c * y + e for x, y in ((0, 0), (w, 0), (0, h), (w, h))]
        ys = [b * x + d * y + f for x, y in ((0, 0), (w, 0), (0, h), (w, h))]
        return (min(xs), min(ys), max(xs), max(ys))

    def rasterize(self, grid):
        out = np.zeros((grid.h, grid.w), dtype=bool)
        x0, y0, x1, y1 = self.bbox()
        c0 = max(int(np.floor((x0 - grid.x0) * grid.res)), 0)
        r0 = max(int(np.floor((y0 - grid.y0) * grid.res)), 0)
        c1 = min(int(np.ceil((x1 - grid.x0) * grid.res)) + 1, grid.w)
        r1 = min(int(np.ceil((y1 - grid.y0) * grid.res)) + 1, grid.h)
        if c1 <= c0 or r1 <= r0:
            return out
        a, b, c, d, e, f = self.affine
        det = a * d - b * c
        if det == 0:
            return out
        X = grid.x0 + (np.arange(c0, c1) + 0.5) / grid.res
        Y = grid.y0 + (np.arange(r0, r1) + 0.5) / grid.res
        X, Y = np.meshgrid(X - e, Y - f)
        u = (d * X - c * Y) / det
        v = (-b * X + a * Y) / det
        h, w = self.mask.shape
        ui, vi = np.floor(u).astype(int), np.floor(v).astype(int)
        ok = (ui >= 0) & (ui < w) & (vi >= 0) & (vi < h)
        sub = np.zeros(ui.shape, dtype=bool)
        sub[ok] = self.mask[vi[ok], ui[ok]]
        out[r0:r1, c0:c1] = sub
        return out


# ---------------------------------------------------------------- raster ----

class _Grid:
    """Pixel grid: pixel (row, col) has its centre at origin + ((col+.5)/res, (row+.5)/res)."""

    def __init__(self, x0, y0, w, h, res):
        self.x0, self.y0, self.w, self.h, self.res = x0, y0, int(w), int(h), float(res)

    def to_px(self, pts):
        return (pts[:, 0] - self.x0) * self.res, (pts[:, 1] - self.y0) * self.res

    def to_mm(self, cols, rows):
        return np.column_stack((self.x0 + cols / self.res, self.y0 + rows / self.res))

    def sub(self, r0, c0, h, w):
        return _Grid(self.x0 + c0 / self.res, self.y0 + r0 / self.res, w, h, self.res)


def _fill_mask(grid, polylines, evenodd):
    """Scanline fill of closed polygons via a winding-number accumulator."""
    H, W = grid.h, grid.w
    diff = np.zeros((H, W + 1), dtype=np.int32)
    for p in polylines:
        if len(p) < 3:
            continue
        X, Y = grid.to_px(p)
        x0, y0 = X, Y
        x1, y1 = np.roll(X, -1), np.roll(Y, -1)
        keep = y0 != y1
        x0, y0, x1, y1 = x0[keep], y0[keep], x1[keep], y1[keep]
        if not len(x0):
            continue
        ymin, ymax = np.minimum(y0, y1), np.maximum(y0, y1)
        rs = np.clip(np.ceil(ymin - 0.5), 0, H).astype(np.int64)
        re = np.clip(np.ceil(ymax - 0.5), 0, H).astype(np.int64)
        n = re - rs
        ok = n > 0
        if not ok.any():
            continue
        x0, y0, x1, y1, rs, n = x0[ok], y0[ok], x1[ok], y1[ok], rs[ok], n[ok]
        e = np.repeat(np.arange(len(n)), n)
        rows = rs[e] + (np.arange(n.sum()) - np.repeat(np.cumsum(n) - n, n))
        yc = rows + 0.5
        xc = x0[e] + (yc - y0[e]) * (x1[e] - x0[e]) / (y1[e] - y0[e])
        cols = np.clip(np.ceil(xc - 0.5), 0, W).astype(np.int64)
        d = np.where(y1[e] > y0[e], 1, -1).astype(np.int32)
        np.add.at(diff, (rows, cols), d)
    wind = np.cumsum(diff, axis=1)[:, :W]
    return (wind & 1).astype(bool) if evenodd else wind != 0


def _line_mask(grid, polylines, closed):
    """Pixels touched by the centre line of the polylines."""
    m = np.zeros((grid.h, grid.w), dtype=bool)
    for p, c in zip(polylines, closed):
        if len(p) < 1:
            continue
        if c and len(p) > 1:
            p = np.vstack((p, p[:1]))
        X, Y = grid.to_px(p)
        if len(p) == 1:
            xs, ys = X, Y
        else:
            seg = np.hypot(np.diff(X), np.diff(Y))
            k = np.maximum(np.ceil(seg / 0.5).astype(int), 1)
            e = np.repeat(np.arange(len(seg)), k)
            t = (np.arange(k.sum()) - np.repeat(np.cumsum(k) - k, k)) / k[e]
            xs = np.append(X[:-1][e] + t * np.diff(X)[e], X[-1])
            ys = np.append(Y[:-1][e] + t * np.diff(Y)[e], Y[-1])
        c_ = np.floor(xs).astype(int)
        r_ = np.floor(ys).astype(int)
        ok = (c_ >= 0) & (c_ < grid.w) & (r_ >= 0) & (r_ < grid.h)
        m[r_[ok], c_[ok]] = True
    return m


def _edt_sq(mask, R):
    """Exact squared Euclidean distance (px^2) to the nearest True pixel,
    for distances <= R; everything farther is +inf."""
    R = int(math.ceil(R))
    big = np.float32(np.inf)
    f = np.where(mask, np.float32(0), big)
    g = f.copy()
    for s in range(1, min(R, f.shape[0] - 1) + 1):
        s2 = np.float32(s * s)
        np.minimum(g[s:], f[:-s] + s2, out=g[s:])
        np.minimum(g[:-s], f[s:] + s2, out=g[:-s])
    h = g.copy()
    for s in range(1, min(R, g.shape[1] - 1) + 1):
        s2 = np.float32(s * s)
        np.minimum(h[:, s:], g[:, :-s] + s2, out=h[:, s:])
        np.minimum(h[:, :-s], g[:, s:] + s2, out=h[:, :-s])
    h[h > R * R] = big
    return h


def _ink_mask(grid, shapes):
    m = np.zeros((grid.h, grid.w), dtype=bool)
    for s in shapes:
        if isinstance(s, RasterShape):
            m |= s.rasterize(grid)
            continue
        closed_polys = [p for p, c in zip(s.polylines, s.closed) if len(p) >= 3]
        if s.fill and closed_polys:
            # SVG fills open subpaths as if closed, too
            m |= _fill_mask(grid, closed_polys, s.evenodd)
        hw = s.stroke_mm * grid.res / 2.0
        if hw > 0:
            line = _line_mask(grid, s.polylines, s.closed)
            if hw <= 0.75:
                m |= line
            else:
                m |= _edt_sq(line, hw + 1) <= hw * hw
    return m


# ------------------------------------------------------- marching squares ---

# For every 4-bit case (tl=1, tr=2, br=4, bl=8 inside) the cell edges joined
# by a contour segment.  Edges: 0=top 1=right 2=bottom 3=left.
_SEGS = {
    1: [(0, 3)], 2: [(0, 1)], 3: [(3, 1)], 4: [(1, 2)],
    6: [(0, 2)], 7: [(3, 2)], 8: [(3, 2)], 9: [(0, 2)],
    11: [(1, 2)], 12: [(3, 1)], 13: [(0, 1)], 14: [(0, 3)],
}
_SADDLE = {  # (centre inside, centre outside)
    5: ([(0, 1), (3, 2)], [(0, 3), (1, 2)]),
    10: ([(0, 3), (1, 2)], [(0, 1), (3, 2)]),
}


def _contours(f):
    """Closed iso-contours f == 0 of a 2-D field (inside: f < 0).  The field
    must be >= 0 on its border.  Returns a list of (N, 2) arrays (col, row)."""
    H, W = f.shape
    ins = f < 0
    tl, tr, br, bl = ins[:-1, :-1], ins[:-1, 1:], ins[1:, 1:], ins[1:, :-1]
    case = tl * 1 + tr * 2 + br * 4 + bl * 8
    ys, xs = np.nonzero((case != 0) & (case != 15))
    if not len(ys):
        return []
    cases = case[ys, xs]
    centre = (f[ys, xs] + f[ys, xs + 1] + f[ys + 1, xs] + f[ys + 1, xs + 1]) < 0

    nh = H * W

    def edge_id(y, x, e):
        if e == 0:
            return y * W + x                 # horizontal edge (y, x)-(y, x+1)
        if e == 2:
            return (y + 1) * W + x
        if e == 3:
            return nh + y * W + x            # vertical edge (y, x)-(y+1, x)
        return nh + y * W + x + 1

    a_list, b_list = [], []
    for y, x, c, cen in zip(ys.tolist(), xs.tolist(), cases.tolist(), centre.tolist()):
        segs = _SEGS.get(c)
        if segs is None:
            segs = _SADDLE[c][0 if cen else 1]
        for ea, eb in segs:
            a_list.append(edge_id(y, x, ea))
            b_list.append(edge_id(y, x, eb))

    # edge -> the (at most two) segments using it
    adj = {}
    for i, (a, b) in enumerate(zip(a_list, b_list)):
        adj.setdefault(a, []).append(i)
        adj.setdefault(b, []).append(i)

    def point(eid):
        if eid < nh:
            y, x = divmod(eid, W)
            v0, v1 = f[y, x], f[y, x + 1]
            return (x + v0 / (v0 - v1), y)
        y, x = divmod(eid - nh, W)
        v0, v1 = f[y, x], f[y + 1, x]
        return (x, y + v0 / (v0 - v1))

    used = np.zeros(len(a_list), dtype=bool)
    out = []
    for s0 in range(len(a_list)):
        if used[s0]:
            continue
        used[s0] = True
        start = a_list[s0]
        cur = b_list[s0]
        pts = [point(start)]
        while cur != start:
            pts.append(point(cur))
            nxt = None
            for s in adj[cur]:
                if not used[s]:
                    nxt = s
                    break
            if nxt is None:
                break                          # should not happen on a padded field
            used[nxt] = True
            cur = b_list[nxt] if a_list[nxt] == cur else a_list[nxt]
        if len(pts) >= 3:
            out.append(np.array(pts, dtype=float))
    return out


def _area(p):
    x, y = p[:, 0], p[:, 1]
    return 0.5 * float(np.dot(x, np.roll(y, -1)) - np.dot(np.roll(x, -1), y))


def _inside(pt, poly):
    x, y = pt
    xs, ys = poly[:, 0], poly[:, 1]
    xe, ye = np.roll(xs, -1), np.roll(ys, -1)
    cond = (ys > y) != (ye > y)
    with np.errstate(divide="ignore", invalid="ignore"):
        xi = xs + (y - ys) * (xe - xs) / (ye - ys)
    return int(np.count_nonzero(cond & (x < xi))) % 2 == 1


def _outer_only(polys):
    """Drop contours that lie inside another one (holes, islands in holes)."""
    order = sorted(range(len(polys)), key=lambda i: -abs(_area(polys[i])))
    kept = []
    for i in order:
        p = polys[i]
        if not any(_inside(p[0], polys[k]) for k in kept):
            kept.append(i)
    return [polys[i] for i in kept]


def _simplify(p, tol):
    """Douglas-Peucker on a closed polygon."""
    n = len(p)
    if n < 5 or tol <= 0:
        return p
    d0 = np.hypot(*(p - p[0]).T)
    j = int(np.argmax(d0))
    keep = np.zeros(n, dtype=bool)
    keep[0] = keep[j] = True
    ring = np.vstack((p, p[:1]))
    stack = [(0, j), (j, n)]
    while stack:
        a, b = stack.pop()
        if b - a < 2:
            continue
        A, B = ring[a], ring[b]
        seg = ring[a + 1:b]
        d = B - A
        L = math.hypot(*d)
        if L == 0:
            dist = np.hypot(*(seg - A).T)
        else:
            dist = np.abs(d[0] * (seg[:, 1] - A[1]) - d[1] * (seg[:, 0] - A[0])) / L
        k = int(np.argmax(dist))
        if dist[k] > tol:
            m = a + 1 + k
            keep[m % n] = True
            stack.append((a, m))
            stack.append((m, b))
    return p[keep]


def _count_parts(mask):
    """Number of separate outer outlines of a boolean mask."""
    if not mask.any():
        return 0
    f = np.pad(np.where(mask, -1.0, 1.0), 1, constant_values=1.0)
    return len(_outer_only(_contours(f)))


def _join_parts(ink, base_px, max_px, res):
    """If the region {distance to ink < base_px} has several separate parts,
    find the smallest extra radius rho (<= max_px) whose dilation joins them,
    and return the field of its morphological closing (negative inside,
    same shape as ink).  None when the region is already in one piece."""
    P = int(math.ceil(base_px + max_px)) + 3
    inkp = np.pad(ink, P, constant_values=False)
    d = np.sqrt(_edt_sq(inkp, base_px + max_px + 2))
    if _count_parts(d < base_px) <= 1:
        return None
    for mm in (0.25, 0.5, 1, 1.5, 2, 3, 4, 6, 8, 12, 16, 24, 32, 48):
        rho = mm * res
        if rho > max_px:
            break
        dil = d < base_px + rho
        if _count_parts(dil) == 1:
            dout = np.sqrt(_edt_sq(~dil, rho + 2))
            cl = np.where(np.isfinite(dout), rho - dout + 0.5, -1e3)
            return cl[P:-P, P:-P]
    return None


# ------------------------------------------------------------- main entry ---

def _bbox_union(bbs):
    bbs = [b for b in bbs if b is not None]
    if not bbs:
        return None
    a = np.array(bbs)
    return (a[:, 0].min(), a[:, 1].min(), a[:, 2].max(), a[:, 3].max())


def _split_islands(grid, ink, join_px):
    """Split one ink mask into separate designs.  Ink closer than join_px is
    one island; an island whose centre lies inside the convex hull of a bigger
    one (text inside a frame that is not closed, a detached detail...) is
    merged into it.  Returns a list of (rows, cols) pixel index arrays."""
    near = _edt_sq(ink, join_px / 2.0 + 1) <= (join_px / 2.0) ** 2 if join_px > 0 else ink
    f = np.pad(np.where(near, -1.0, 1.0), 1, constant_values=1.0)
    polys = [p - 1.0 for p in _outer_only(_contours(f))]     # undo the pad
    isl = []
    for p in polys:
        isl.append({"pts": p, "hull": _convex_hull(p), "area": abs(_area(p)),
                    "centre": p.mean(axis=0), "members": [p]})
    isl.sort(key=lambda g: g["area"])
    alive = [True] * len(isl)
    for i, g in enumerate(isl):
        cands = [j for j in range(i + 1, len(isl))
                 if alive[j] and isl[j]["area"] > g["area"] and _inside(g["centre"], isl[j]["hull"])]
        if not cands:
            continue
        j = min(cands, key=lambda j: float(np.min(np.hypot(*(isl[j]["pts"] - g["centre"]).T))))
        t = isl[j]
        t["members"] += g["members"]
        t["pts"] = np.vstack((t["pts"], g["pts"]))
        t["hull"] = _convex_hull(np.vstack((t["hull"], g["hull"])))
        alive[i] = False

    out = []
    for g, a in zip(isl, alive):
        if not a:
            continue
        allp = np.vstack(g["members"])
        c0 = max(int(np.floor(allp[:, 0].min())) - 1, 0)
        r0 = max(int(np.floor(allp[:, 1].min())) - 1, 0)
        c1 = min(int(np.ceil(allp[:, 0].max())) + 2, grid.w)
        r1 = min(int(np.ceil(allp[:, 1].max())) + 2, grid.h)
        sub = grid.sub(r0, c0, r1 - r0, c1 - c0)
        # contour coords are pixel indices; pixel k has its centre at k + .5
        polys_mm = [grid.to_mm(m[:, 0] + 0.5, m[:, 1] + 0.5) for m in g["members"]]
        m = _fill_mask(sub, polys_mm, False) & ink[r0:r1, c0:c1]
        rr, cc = np.nonzero(m)
        if len(rr):
            out.append((rr + r0, cc + c0))
    return out


def _convex_hull(p):
    """Monotone chain convex hull of an (N, 2) array."""
    pts = np.unique(p, axis=0)
    if len(pts) < 3:
        return pts

    def half(points):
        h = []
        for q in points:
            while len(h) >= 2 and ((h[-1][0] - h[-2][0]) * (q[1] - h[-2][1]) -
                                   (h[-1][1] - h[-2][1]) * (q[0] - h[-2][0])) <= 0:
                h.pop()
            h.append(tuple(q))
        return h

    lower = half(pts)
    upper = half(pts[::-1])
    return np.array(lower[:-1] + upper[:-1], dtype=float)


def _dense_outlines(items, offset_mm, res, gap_mm, islands, join_mm, min_area_mm2, merge_mm,
                    one_piece_mm=0.0):
    """Unsimplified closed contours (mm), one list per design."""
    offset_mm = max(float(offset_mm), 0.6 / res)
    merge_mm = max(float(merge_mm or 0.0), 0.0)
    reach_mm = offset_mm + merge_mm / 2.0
    R = reach_mm * res + 2.0                       # distance field reach (px)
    margin = reach_mm + 3.0 / res

    item_bbs = [_bbox_union([s.bbox() for s in it]) for it in items]
    full = _bbox_union(item_bbs)
    if full is None:
        return []
    gx0, gy0 = full[0] - margin, full[1] - margin
    GW = int(math.ceil((full[2] + margin - gx0) * res)) + 1
    GH = int(math.ceil((full[3] + margin - gy0) * res)) + 1
    grid = _Grid(gx0, gy0, GW, GH, res)

    # --- ink masks, as (r0, c0, mask) crops of the global grid ------------
    def crop_for(bb):
        c0 = max(int(math.floor((bb[0] - margin - gx0) * res)), 0)
        r0 = max(int(math.floor((bb[1] - margin - gy0) * res)), 0)
        c1 = min(int(math.ceil((bb[2] + margin - gx0) * res)) + 1, GW)
        r1 = min(int(math.ceil((bb[3] + margin - gy0) * res)) + 1, GH)
        return r0, c0, r1 - r0, c1 - c0

    inks = []
    if islands:
        total = _ink_mask(grid, [s for it in items for s in it])
        for rr, cc in _split_islands(grid, total, join_mm * res):
            r0 = max(rr.min() - int(R) - 2, 0)
            c0 = max(cc.min() - int(R) - 2, 0)
            r1 = min(rr.max() + int(R) + 3, GH)
            c1 = min(cc.max() + int(R) + 3, GW)
            m = np.zeros((r1 - r0, c1 - c0), dtype=bool)
            m[rr - r0, cc - c0] = True
            inks.append((r0, c0, m))
    else:
        for it, bb in zip(items, item_bbs):
            if bb is None:
                inks.append(None)
                continue
            r0, c0, h, w = crop_for(bb)
            inks.append((r0, c0, _ink_mask(grid.sub(r0, c0, h, w), it)))

    # --- distance fields + Voronoi ownership ------------------------------
    inf = np.float32(np.inf)
    best1 = np.full((GH, GW), inf, dtype=np.float32)
    best2 = np.full((GH, GW), inf, dtype=np.float32)
    owner = np.full((GH, GW), -1, dtype=np.int32)
    dists = []
    for i, ink in enumerate(inks):
        if ink is None or not ink[2].any():
            dists.append(None)
            continue
        r0, c0, m = ink
        d = _edt_sq(m, R)
        dists.append(d)
        sl = (slice(r0, r0 + m.shape[0]), slice(c0, c0 + m.shape[1]))
        b1, b2, ow = best1[sl], best2[sl], owner[sl]
        better = d < b1
        np.copyto(b2, np.where(better, b1, np.minimum(b2, d)))
        np.copyto(b1, np.where(better, d, b1))
        ow[better] = i

    # --- contours ----------------------------------------------------------
    half_gap = 0.0 if merge_mm > 0 else max(gap_mm, 0.0) * res / 2.0
    r_px = offset_mm * res
    closing = None
    if merge_mm > 0:
        # Morphological closing of the union of all cut regions by merge/2:
        # gaps narrower than merge_mm between neighbours (and narrow notches)
        # are filled with round ends, so both neighbours' cut lines fall on
        # the same dividing line instead of running side by side.
        s_px = merge_mm * res / 2.0
        dilated = np.sqrt(best1) < r_px + s_px
        dout = np.sqrt(_edt_sq(~dilated, s_px + 2))
        closing = np.where(np.isfinite(dout), s_px - dout + 0.5, -1e3)
    results = []
    for i, ink in enumerate(inks):
        d2 = dists[i] if ink is not None else None
        if d2 is None:
            results.append([])
            continue
        r0, c0, m = ink
        sl = (slice(r0, r0 + m.shape[0]), slice(c0, c0 + m.shape[1]))
        di = np.sqrt(d2)
        other = np.sqrt(np.where(owner[sl] == i, best2[sl], best1[sl]))
        with np.errstate(invalid="ignore"):
            voronoi = (di - other) / 2.0 + half_gap
        voronoi = np.where(np.isfinite(other), voronoi, -np.inf)
        body = di - r_px
        if closing is not None:
            body = np.minimum(body, closing[sl])
        if one_piece_mm > 0:
            # keep a design made of separate parts in one piece
            cl = _join_parts(m, r_px, one_piece_mm * res, res)
            if cl is not None:
                body = np.minimum(body, cl)
        fld = np.maximum(body, voronoi)
        fld = np.where(np.isfinite(fld), fld, 1e3).astype(np.float64)
        fld = np.pad(fld, 1, constant_values=1e3)
        polys = []
        for p in _outer_only(_contours(fld)):
            # contour coords are in padded-crop pixel-index space; pixel
            # index k has its centre at k + .5 in grid space
            mm = grid.to_mm(p[:, 0] - 1 + c0 + 0.5, p[:, 1] - 1 + r0 + 0.5)
            if abs(_area(mm)) < min_area_mm2:
                continue
            polys.append(mm)
        results.append(polys)
    return results


def compute_outlines(items, offset_mm=1.5, res=10.0, simplify_mm=0.03,
                     gap_mm=0.0, islands=False, join_mm=0.5, min_area_mm2=1.0, one_piece_mm=0.0):
    """Compute one closed cut contour per design.

    items:        list of designs; each design is a list of Shape
    offset_mm:    distance between the ink and the cut line
    res:          raster resolution in px/mm (10 = 0.1 mm)
    simplify_mm:  Douglas-Peucker tolerance of the output polygons
    gap_mm:       minimum distance between the cut lines of two neighbours
                  that are too close to get the full offset (0 = they share
                  the separating line)
    islands:      ignore the item grouping and split all ink into separate
                  designs automatically (ink closer than join_mm is one design)
    min_area_mm2: drop contours (e.g. specks) smaller than this
    one_piece_mm: a design made of separate parts gets one contour around all
                  of them, bridging gaps up to this size (0 = off)

    Returns a list (one entry per design) of lists of (N, 2) polygons in mm.
    """
    dense = _dense_outlines(items, offset_mm, res, gap_mm, islands, join_mm, min_area_mm2, 0.0, one_piece_mm)
    return [[_simplify(p, simplify_mm) for p in polys] for polys in dense]


def compute_cut_paths(items, offset_mm=1.5, res=10.0, simplify_mm=0.03,
                      islands=False, join_mm=0.5, min_area_mm2=1.0, merge_mm=1.0, one_piece_mm=0.0):
    """Like compute_outlines, but every stretch of line is cut only once.

    Neighbouring designs whose cut lines would run closer than merge_mm are
    given one common dividing line, and that line is emitted a single time:
    the first design keeps a closed contour, the following ones get open
    paths that end on the lines already cut.

    Returns a flat list of (points (N, 2) in mm, closed: bool).
    """
    dense = _dense_outlines(items, offset_mm, res, 0.0, islands, join_mm, min_area_mm2, merge_mm, one_piece_mm)
    tol = max(2.5 / res, 0.15)
    out = []
    for pts, closed in _dedupe([p for polys in dense for p in polys], tol):
        if closed:
            out.append((_simplify(pts, simplify_mm), True))
        else:
            out.append((_simplify_open(pts, simplify_mm), False))
    return out


def _nearest(P, refs, tol):
    """For every point of P: distance to and position of the closest point
    of the reference polylines (only those whose bbox is within reach)."""
    best_d = np.full(len(P), np.inf)
    best_p = P.copy()
    lo, hi = P.min(axis=0) - tol, P.max(axis=0) + tol
    for R in refs:
        if (R.max(axis=0) < lo).any() or (R.min(axis=0) > hi).any():
            continue
        for a in range(0, len(P), 512):
            chunk = P[a:a + 512]
            d = np.hypot(chunk[:, None, 0] - R[None, :, 0], chunk[:, None, 1] - R[None, :, 1])
            k = np.argmin(d, axis=1)
            dk = d[np.arange(len(chunk)), k]
            upd = dk < best_d[a:a + 512]
            best_d[a:a + 512][upd] = dk[upd]
            best_p[a:a + 512][upd] = R[k[upd]]
    return best_d, best_p


def _dedupe(polys, tol):
    """Remove the parts of each closed polygon that run along lines already
    emitted.  Returns [(points, closed)]."""
    emitted = []
    out = []
    for P in polys:
        if len(P) < 3:
            continue
        d, nearest = _nearest(P, emitted, tol)
        near = d < tol
        if not near.any():
            out.append((P, True))
            emitted.append(np.vstack((P, P[:1])))
            continue
        if near.all():
            continue
        # walk the ring starting on a shared point; every run of free points,
        # plus the shared point at each side (snapped onto the existing line),
        # becomes an open path
        s = int(np.argmax(near))
        P, near, nearest = np.roll(P, -s, axis=0), np.roll(near, -s), np.roll(nearest, -s, axis=0)
        n = len(P)
        k = 0
        while k < n:
            if near[k]:
                k += 1
                continue
            a = k
            while k < n and not near[k]:
                k += 1
            b = k % n                                   # shared point after the run
            piece = np.vstack((nearest[a - 1], P[a:k], nearest[b]))
            if np.hypot(*np.diff(piece, axis=0).T).sum() > tol:
                out.append((piece, False))
                emitted.append(piece)
    return out


def _simplify_open(p, tol):
    """Douglas-Peucker on an open polyline (end points kept)."""
    n = len(p)
    if n < 3 or tol <= 0:
        return p
    keep = np.zeros(n, dtype=bool)
    keep[0] = keep[-1] = True
    stack = [(0, n - 1)]
    while stack:
        a, b = stack.pop()
        if b - a < 2:
            continue
        A, B = p[a], p[b]
        seg = p[a + 1:b]
        d = B - A
        L = math.hypot(*d)
        if L == 0:
            dist = np.hypot(*(seg - A).T)
        else:
            dist = np.abs(d[0] * (seg[:, 1] - A[1]) - d[1] * (seg[:, 0] - A[0])) / L
        j = int(np.argmax(dist))
        if dist[j] > tol:
            m = a + 1 + j
            keep[m] = True
            stack.append((a, m))
            stack.append((m, b))
    return p[keep]
