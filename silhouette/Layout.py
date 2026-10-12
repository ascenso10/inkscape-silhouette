# (c) 2026 - Automatic sheet layout for print & cut.
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
"""
Repeat one design on a sheet as densely as possible (pure numpy).

The design is rasterised; its "footprint" (ink grown by half the minimum gap)
must not overlap the footprint of any other copy, and its cut footprint (ink
grown by the cut offset) must stay inside the usable area of the sheet
(inside the registration marks, away from the corner marks).

Candidate patterns are periodic lattices, tried with the design at 0 or 90
degrees, arranged in rows or in columns, with every copy the same way up or
every other row/column turned 180 degrees (which lets shapes interlock).
All pairwise overlaps of two copies are obtained at once from an FFT
correlation of their masks; the lattice phase on the sheet is then chosen to
fit the most copies.
"""

import math
import numpy as np

from silhouette.Outline import Shape, RasterShape, _Grid, _ink_mask, _edt_sq, _bbox_union, _join_parts

__all__ = ["Region", "Placement", "LayoutResult", "layout", "max_size_for", "transform_shapes"]


# ------------------------------------------------------------- helpers ----

def transform_shapes(shapes, m):
    """Apply the affine m = (a, b, c, d, e, f) (SVG matrix order) to shapes in mm."""
    a, b, c, d, e, f = m
    out = []
    for s in shapes:
        if isinstance(s, RasterShape):
            A, B, C, D, E, F = s.affine
            out.append(RasterShape(s.mask, (a * A + c * B, b * A + d * B, a * C + c * D, b * C + d * D,
                                            a * E + c * F + e, b * E + d * F + f)))
        else:
            polys = [np.column_stack((a * p[:, 0] + c * p[:, 1] + e, b * p[:, 0] + d * p[:, 1] + f))
                     for p in s.polylines]
            scale = math.sqrt(abs(a * d - b * c))
            out.append(Shape(polys, s.closed, s.fill, s.evenodd, s.stroke_mm * scale))
    return out


def _rot(angle):
    r = math.radians(angle)
    c, s = round(math.cos(r), 12), round(math.sin(r), 12)
    return (c, s, -s, c, 0.0, 0.0)


def _overlap_map(A, B):
    """M[dy + h - 1, dx + w - 1] is True when B placed at offset (dx, dy)
    from A overlaps it.  A and B have the same shape."""
    h, w = A.shape
    N = (2 * h, 2 * w)
    fa = np.fft.rfft2(A.astype(np.float32), s=N)
    fb = np.fft.rfft2(B.astype(np.float32), s=N)
    c = np.fft.irfft2(fa * np.conj(fb), s=N)
    c = np.roll(c, (h - 1, w - 1), axis=(0, 1))[:2 * h - 1, :2 * w - 1]
    return c > 0.5


class _Pair:
    """Overlap lookups between the two orientations of the design."""

    def __init__(self, F, G):
        self.h, self.w = F.shape
        self.M = {("F", "F"): _overlap_map(F, F), ("F", "G"): _overlap_map(F, G),
                  ("G", "F"): _overlap_map(G, F), ("G", "G"): _overlap_map(G, G)}

    def hits(self, t1, t2, dx, dy):
        """Vectorised: does a copy of type t2 at offset (dx, dy) from a copy
        of type t1 overlap it?"""
        dx, dy = np.asarray(dx), np.asarray(dy)
        inside = (np.abs(dx) < self.w) & (np.abs(dy) < self.h)
        out = np.zeros(np.broadcast(dx, dy).shape, dtype=bool)
        if inside.any():
            M = self.M[(t1, t2)]
            dxb, dyb = np.broadcast_to(dx, out.shape), np.broadcast_to(dy, out.shape)
            out[inside] = M[dyb[inside] + self.h - 1, dxb[inside] + self.w - 1]
        return out


# ------------------------------------------------------------ patterns ----

class _Pattern:
    """A periodic arrangement in mask-pixel units (x right, y down)."""

    def __init__(self, kind, ax, rows):
        # rows: list of (row_dx, row_dy, type) for one vertical period; the
        # period vector is the offset of the first row of the next period
        self.kind = kind
        self.ax = ax
        self.rows = rows[:-1]
        self.period = rows[-1][:2]

    def positions(self, nper, ncol):
        pts = []
        px, py = self.period
        for j in range(-nper, nper + 1):
            for (rx, ry, t) in self.rows:
                for k in range(-ncol, ncol + 1):
                    pts.append((j * px + rx + k * self.ax, j * py + ry, t))
        return pts

    def area_per_copy(self):
        return self.ax * self.period[1] / float(len(self.rows))


def _valid_pattern(pair, pat):
    pts = pat.positions(2, 3)
    xs = np.array([p[0] for p in pts]); ys = np.array([p[1] for p in pts]); ts = [p[2] for p in pts]
    for i in range(len(pts)):
        for t2 in ("F", "G"):
            idx = [j for j in range(len(pts)) if j != i and ts[j] == t2]
            if idx and pair.hits(ts[i], t2, xs[idx] - xs[i], ys[idx] - ys[i]).any():
                return False
    return True


def _min_dy(pair, t1, t2, bx, ax):
    """Smallest dy >= 1 so that a row of t2 copies (spacing ax, offset bx)
    does not touch a row of t1 copies.  Vectorised over bx."""
    h, w = pair.h, pair.w
    ks = np.arange(-(w // max(ax, 1)) - 2, w // max(ax, 1) + 3)
    res = np.full(len(bx), h, dtype=int)
    dys = np.arange(1, h)
    for i, b in enumerate(bx):
        xs = b + ks * ax
        xs = xs[np.abs(xs) < w]
        if not len(xs):
            res[i] = 1
            continue
        hit = pair.hits(t1, t2, xs[None, :], dys[:, None]).any(axis=1)
        free = np.nonzero(~hit)[0]
        res[i] = dys[free[0]] if len(free) else h
    return res


def _patterns(F, G, max_candidates=12):
    pair = _Pair(F, G)
    h, w = F.shape
    # horizontal period of a row (same orientation)
    ax = w
    for dx in range(1, w + 1):
        ks = np.arange(1, w // dx + 2) * dx
        if not pair.hits("F", "F", ks, np.zeros_like(ks)).any():
            ax = dx
            break
    found = []
    bx = np.arange(ax)
    # every copy the same way up
    by = _min_dy(pair, "F", "F", bx, ax)
    for i in np.argsort(ax * by, kind="stable")[:max_candidates]:
        p = _Pattern("same", ax, [(0, 0, "F"), (int(bx[i]), int(by[i]), "F")])
        if _valid_pattern(pair, p):
            found.append(p)
            break
    # every other row turned 180 degrees
    h1 = _min_dy(pair, "F", "G", bx, ax)
    h2 = _min_dy(pair, "G", "F", bx, ax)
    combos = sorted(((h1[a] + h2[b], a, b) for a in range(ax) for b in range(ax)))[:max_candidates * 4]
    for _, a, b in combos:
        p = _Pattern("alternate", ax, [(0, 0, "F"), (int(a), int(h1[a]), "G"),
                                        (int(a + b), int(h1[a] + h2[b]), "F")])
        if _valid_pattern(pair, p):
            found.append(p)
            break
    return found


# -------------------------------------------------------------- region ----

class Region:
    """Usable area of the sheet (mm): a rectangle minus square corner zones."""

    def __init__(self, page_w, page_h, rect, corners=()):
        self.page_w, self.page_h = float(page_w), float(page_h)
        self.rect = tuple(float(v) for v in rect)      # x0, y0, x1, y1
        self.corners = list(corners)                    # (x0, y0, x1, y1) forbidden boxes

    @classmethod
    def for_regmarks(cls, page_w, page_h, left=10.0, top=10.0, width=0.0, length=0.0,
                     mark_len=20.0, clearance=1.0, four_marks=False):
        """Inside the registration marks (the cutter only cuts there), minus
        the square zones of the corner marks."""
        x0, y0 = left, top
        x1 = left + (width or page_w - 2 * left)
        y1 = top + (length or page_h - 2 * top)
        z = mark_len + clearance
        corners = [(x0, y0, x0 + z, y0 + z), (x1 - z, y0, x1, y0 + z), (x0, y1 - z, x0 + z, y1)]
        if four_marks:
            corners.append((x1 - z, y1 - z, x1, y1))
        return cls(page_w, page_h, (x0, y0, x1, y1), corners)

    @classmethod
    def with_margin(cls, page_w, page_h, margin=5.0):
        return cls(page_w, page_h, (margin, margin, page_w - margin, page_h - margin))

    def mask(self, res):
        H, W = int(math.floor(self.page_h * res)), int(math.floor(self.page_w * res))
        ys = (np.arange(H) + 0.5) / res
        xs = (np.arange(W) + 0.5) / res
        X, Y = np.meshgrid(xs, ys)
        x0, y0, x1, y1 = self.rect
        ok = (X >= x0) & (X <= x1) & (Y >= y0) & (Y <= y1)
        for cx0, cy0, cx1, cy1 in self.corners:
            ok &= ~((X >= cx0) & (X <= cx1) & (Y >= cy0) & (Y <= cy1))
        return ok


# -------------------------------------------------------------- layout ----

class Placement:
    def __init__(self, x, y, angle):
        self.x, self.y, self.angle = x, y, angle      # design centre in mm, rotation in degrees

    def __repr__(self):
        return "Placement(%.2f, %.2f, %g)" % (self.x, self.y, self.angle)


class LayoutResult:
    def __init__(self, placements, capacity, description):
        self.placements = placements
        self.capacity = capacity
        self.description = description


def _valid_map(forbidden, M):
    """V[y, x] True when mask M with its top-left at (y - h, x - w) of the page
    lies entirely in allowed area (forbidden is padded by (h, w) already)."""
    h, w = M.shape
    S = forbidden.shape
    ff = np.fft.rfft2(forbidden.astype(np.float32), s=S)
    fm = np.fft.rfft2(M.astype(np.float32), s=S)
    c = np.fft.irfft2(ff * np.conj(fm), s=S)
    V = c < 0.5
    V[S[0] - h + 1:, :] = False
    V[:, S[1] - w + 1:] = False
    return V


def _masks(shapes, angle, res, ext, grow_px, one_piece_px=0.0):
    """Ink of the design rotated by angle, on a grid centred on the design
    centre (which is at the origin), grown by each value of grow_px."""
    rs = transform_shapes(shapes, _rot(angle))
    gw, gh = ext
    cols, rows = int(math.ceil(gw * res)), int(math.ceil(gh * res))
    cols += cols % 2
    rows += rows % 2
    grid = _Grid(-cols / (2.0 * res), -rows / (2.0 * res), cols, rows, res)
    ink = _ink_mask(grid, rs)
    out = []
    for g in grow_px:
        m = ink if g <= 0 else (_edt_sq(ink, g + 1) <= g * g)
        if one_piece_px > 0:
            cl = _join_parts(ink, max(g, 0.5), one_piece_px, res)
            if cl is not None:
                m = cl < 0
        out.append(m)
    return out


def layout(shapes, region, copies=0, gap_mm=3.0, cut_mm=1.5, res=None, allow_rotation=True,
           allow_alternate=True, one_piece_mm=25.0):
    """Find where to put the copies.  shapes: the design in mm (any position).
    copies: wanted number (0 = as many as fit).  Returns LayoutResult, whose
    placements give the position of the design's bounding-box centre.
    one_piece_mm: a design made of separate parts is treated as one piece
    (gaps up to this size are filled), so copies never slip between the parts
    of another copy."""
    bb = _bbox_union([s.bbox() for s in shapes])
    if bb is None:
        return LayoutResult([], 0, "empty design")
    cx, cy = (bb[0] + bb[2]) / 2.0, (bb[1] + bb[3]) / 2.0
    shapes = transform_shapes(shapes, (1, 0, 0, 1, -cx, -cy))
    dw, dh = bb[2] - bb[0], bb[3] - bb[1]
    if res is None:
        res = min(max(160.0 / max(dw, dh, 1e-6), 1.5), 8.0)
    pad = max(gap_mm / 2.0, cut_mm) + 3.0 / res
    gap_px = gap_mm * res / 2.0 + 0.5               # half gap each side, +0.5 px safety
    cut_px = cut_mm * res + 0.5

    allowed = region.mask(res)
    Hp, Wp = allowed.shape

    best = None
    angles = (0, 90) if allow_rotation else (0,)
    for angle in angles:
        ext = (dw + 2 * pad, dh + 2 * pad) if angle % 180 == 0 else (dh + 2 * pad, dw + 2 * pad)
        Fp, Fc = _masks(shapes, angle, res, ext, (gap_px, cut_px), one_piece_mm * res)
        # the grid is centred on the design: 180 degrees is a flip of both axes
        Gp, Gc = Fp[::-1, ::-1].copy(), Fc[::-1, ::-1].copy()
        h, w = Fp.shape
        forb = np.pad(~allowed, ((h, h), (w, w)), constant_values=True)
        V = {"F": _valid_map(forb, Fc), "G": _valid_map(forb, Gc)}
        for mode in ("rows", "cols"):
            if mode == "rows":
                pats = _patterns(Fp, Gp)
            else:
                pats = _patterns(Fp.T.copy(), Gp.T.copy())
            for pat in pats:
                if pat.kind == "alternate" and not allow_alternate:
                    continue
                cand = _fit(pat, mode, V, (Hp, Wp), (h, w), res)
                if cand is None:
                    continue
                count = len(cand[0])
                key = (count, -pat.area_per_copy())
                if best is None or key > best[0]:
                    best = (key, cand, angle, mode, pat, (h, w), V)
    if best is None or best[0][0] == 0:
        return LayoutResult([], 0, "the design does not fit in the usable area")

    (_, (pts, types), angle, mode, pat, (h, w), V) = best
    capacity = len(pts)
    n = capacity if copies <= 0 else min(copies, capacity)
    # take n copies as a compact block: try filling from each side, keep the
    # choice with the smallest bounding box
    best_sel = None
    for primary, sign in ((1, 1), (1, -1), (0, 1), (0, -1)):
        other = 1 - primary
        order = np.lexsort((pts[:, other], sign * pts[:, primary]))
        sel = order[:n]
        q = pts[sel]
        area = (np.ptp(q[:, 0]) + w) * (np.ptp(q[:, 1]) + h)
        if best_sel is None or area < best_sel[0] - 1e-9:
            best_sel = (area, sel)
    sel = best_sel[1]
    pts, types = pts[sel], [types[i] for i in sel]
    pts = _centre(pts, types, V, allowed, (h, w))

    placements = []
    for (x, y), t in zip(pts, types):
        # padded top-left (x, y) -> page px of the design centre
        px = x - w + w / 2.0
        py = y - h + h / 2.0
        placements.append(Placement(px / res, py / res, (angle + (180 if t == "G" else 0)) % 360))
    desc = "%s, %s, %s" % ("rotated 90°" if angle else "upright", "in " + mode,
                           "alternating 180°" if pat.kind == "alternate" else "all the same way")
    return LayoutResult(placements, capacity, desc)


def _fit(pat, mode, V, page_shape, mshape, res):
    """Best phase of the lattice on the page: returns (positions, types)."""
    Hp, Wp = page_shape
    h, w = mshape
    if mode == "rows":
        step_x, step_y = pat.ax, max(pat.period[1], 1)
    else:
        step_x, step_y = max(pat.period[1], 1), pat.ax
    nper = int(max(Hp, Wp) / max(min(pat.period[1], pat.ax), 1)) // max(len(pat.rows), 1) + 3
    ncol = int(max(Hp, Wp) / max(pat.ax, 1)) + 3
    raw = pat.positions(nper, ncol)
    P = np.array([(p[0], p[1]) for p in raw], dtype=int)
    if mode == "cols":
        P = P[:, ::-1]
    T = np.array([p[2] == "G" for p in raw])
    # keep only points near the page
    keep = (P[:, 0] > -2 * w - step_x) & (P[:, 0] < Wp + 2 * w + step_x) & \
           (P[:, 1] > -2 * h - step_y) & (P[:, 1] < Hp + 2 * h + step_y)
    P, T = P[keep], T[keep]
    VF, VG = V["F"], V["G"]
    S = VF.shape
    step = max(int(round(res)), 1)                 # 1 mm phase steps
    best = None
    for ty in range(0, step_y, step):
        for tx in range(0, step_x, step):
            Q = P + (tx + w, ty + h)               # to padded coordinates
            inb = (Q[:, 0] >= 0) & (Q[:, 0] < S[1]) & (Q[:, 1] >= 0) & (Q[:, 1] < S[0])
            ok = np.zeros(len(Q), dtype=bool)
            qi = Q[inb]
            ok[inb] = np.where(T[inb], VG[qi[:, 1], qi[:, 0]], VF[qi[:, 1], qi[:, 0]])
            c = int(ok.sum())
            if best is None or c > best[0]:
                best = (c, Q[ok], T[ok])
    if best is None:
        return None
    return best[1], ["G" if t else "F" for t in best[2]]


def _centre(pts, types, V, allowed, mshape):
    """Shift the chosen copies towards the middle of the usable area while
    they all stay valid."""
    if not len(pts):
        return pts
    h, w = mshape
    ys, xs = np.nonzero(allowed)
    target = np.array([(xs.min() + xs.max()) / 2.0 + w, (ys.min() + ys.max()) / 2.0 + h])
    mid = np.array([(pts[:, 0].min() + pts[:, 0].max() + w) / 2.0,
                    (pts[:, 1].min() + pts[:, 1].max() + h) / 2.0])
    shift = np.round(target - mid).astype(int)

    def ok(s):
        Q = pts + s
        S = V["F"].shape
        if (Q[:, 0] < 0).any() or (Q[:, 1] < 0).any() or (Q[:, 0] >= S[1]).any() or (Q[:, 1] >= S[0]).any():
            return False
        return all(V[t][q[1], q[0]] for q, t in zip(Q, types))

    for f in (1.0, 0.75, 0.5, 0.25, 0.0):
        for s in ((shift * f).astype(int), np.array([int(shift[0] * f), 0]), np.array([0, int(shift[1] * f)])):
            if ok(s):
                return pts + s
    return pts


def max_size_for(shapes, region, copies, size_of, lo=0.05, hi=1.0, **kw):
    """Largest scale factor (relative to the given shapes) at which `copies`
    fit; size_of(scale) only used for the caller's reporting.  Returns scale."""
    best = None
    for _ in range(9):
        mid = (lo + hi) / 2.0
        r = layout(transform_shapes(shapes, (mid, 0, 0, mid, 0, 0)), region, copies, **kw)
        if r.capacity >= copies:
            best, lo = mid, mid
        else:
            hi = mid
    return best
