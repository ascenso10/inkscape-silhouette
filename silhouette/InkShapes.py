# (c) 2026 - Read SVG elements as geometry for the print & cut helpers.
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
"""
Turn inkex elements into silhouette.Outline shapes (in mm, document space):
paths and basic shapes become flattened polylines with their fill / stroke,
<image> elements become bitmap ink masks.  Shared by silhouette_outline.py
and silhouette_layout.py.
"""

import math
import numpy as np

import inkex
from inkex import (Group, PathElement, Use, ShapeElement, Rectangle, Circle, Ellipse, Line,
                   Polyline, Polygon, TextElement, Image, Transform)
from inkex.units import parse_unit, convert_unit

from silhouette.Outline import Shape, RasterShape
from silhouette.Raster import load_image, ink_mask, image_placement

SHAPE_TYPES = (PathElement, Rectangle, Circle, Ellipse, Line, Polyline, Polygon)


def is_layer(node):
    return isinstance(node, Group) and node.get("inkscape:groupmode") == "layer"


def style_get(node, key, default=None):
    try:
        style = node.specified_style()          # inkex >= 1.2, honours inheritance and CSS
    except AttributeError:
        style = node.style
    val = style.get(key)
    if val is None:
        val = node.get(key, default)
    return val if val is not None else default


def hidden(node):
    get = lambda attr, default: node.style.get(attr, node.get(attr, default))
    if get("display", "inline") == "none":
        return True
    if get("visibility", "visible") in ("hidden", "collapse"):
        return True
    try:
        return not float(get("opacity", 1.0))
    except ValueError:
        return False


def mm_per_uu(svg):
    try:
        return svg._base_scale("mm")
    except AttributeError:
        return 1.0 / svg.unittouu("1mm")


def image_href(node):
    return node.get("xlink:href") or node.get("href") or node.get("{http://www.w3.org/1999/xlink}href")


class ShapeReader:
    """Collects Shape / RasterShape objects below elements."""

    def __init__(self, svg, base_dir=None, skip_group=None, warn=None):
        self.svg = svg
        self.mm = mm_per_uu(svg)
        self.base_dir = base_dir
        self.skip_group = skip_group or (lambda node: False)
        self.warn = warn or (lambda key, msg: inkex.errormsg(msg))

    def shapes_of(self, node, parent_transform=None, out=None):
        if out is None:
            out = []
        if not isinstance(node, ShapeElement) or hidden(node):
            return out
        tr = node.composed_transform() if parent_transform is None else parent_transform @ node.transform

        if isinstance(node, Group):
            if self.skip_group(node):
                return out
            for child in node:
                self.shapes_of(child, tr, out)
        elif isinstance(node, Use):
            ref = node.href
            if ref is not None:
                x = float(node.get("x", 0.0) or 0.0)
                y = float(node.get("y", 0.0) or 0.0)
                self.shapes_of(ref, tr @ Transform(translate=(x, y)), out)
        elif isinstance(node, SHAPE_TYPES):
            s = self.shape_from_element(node, tr)
            if s is not None:
                out.append(s)
        elif isinstance(node, Image):
            s = self.shape_from_image(node, tr)
            if s is not None:
                out.append(s)
        elif isinstance(node, TextElement):
            self.warn("text", "Warning: text is ignored; convert it to a path first (Path > Object to Path).")
        return out

    def shape_from_image(self, node, tr):
        try:
            rgba = load_image(image_href(node), self.base_dir)
        except Exception as e:
            self.warn("image", "Warning: could not read a bitmap image (%s)." % e)
            return None
        h, w = rgba.shape[:2]
        x, y = float(node.get("x", 0) or 0), float(node.get("y", 0) or 0)
        width = float(node.get("width", w) or w)
        height = float(node.get("height", h) or h)
        p = image_placement(x, y, width, height, w, h, node.get("preserveAspectRatio"))
        m = compose((tr.a, tr.b, tr.c, tr.d, tr.e, tr.f), p)
        k = self.mm
        return RasterShape(ink_mask(rgba), tuple(v * k for v in m))

    def shape_from_element(self, node, tr):
        mm = self.mm
        path_el = node if isinstance(node, PathElement) else node.to_path_element()
        csp = path_el.path.transform(tr).to_superpath()
        step = 0.1 / mm      # flatten curves to ~0.1 mm chords (user units)
        polylines, closed = [], []
        for sp in csp:
            if not sp:
                continue
            pts = [sp[0][1]]
            for a, b in zip(sp[:-1], sp[1:]):
                p0, p1, p2, p3 = (np.array(a[1]), np.array(a[2]), np.array(b[0]), np.array(b[1]))
                L = (np.linalg.norm(p1 - p0) + np.linalg.norm(p2 - p1) + np.linalg.norm(p3 - p2))
                straight = np.allclose(p1, p0) and np.allclose(p2, p3)
                n = 1 if straight else max(int(math.ceil(L / step)), 1)
                for t in np.linspace(0.0, 1.0, n + 1)[1:]:
                    u = 1.0 - t
                    pts.append(u ** 3 * p0 + 3 * u * u * t * p1 + 3 * u * t * t * p2 + t ** 3 * p3)
            arr = np.array(pts, dtype=float) * mm
            if len(arr) == 0:
                continue
            is_closed = len(arr) > 2 and np.allclose(arr[0], arr[-1], atol=1e-6)
            polylines.append(arr)
            closed.append(is_closed)
        if not polylines:
            return None

        fill = style_get(node, "fill", "#000000")
        fill_on = str(fill).strip().lower() not in ("none", "transparent")
        try:
            fill_on = fill_on and float(style_get(node, "fill-opacity", 1.0)) > 0
        except (TypeError, ValueError):
            pass
        evenodd = str(style_get(node, "fill-rule", "nonzero")).strip() == "evenodd"

        stroke_mm = 0.0
        stroke = style_get(node, "stroke", "none")
        if str(stroke).strip().lower() not in ("none", "transparent", ""):
            raw = str(style_get(node, "stroke-width", "1")).strip()
            try:
                value, unit = parse_unit(raw) or (1.0, "")
            except Exception:
                value, unit = 1.0, ""
            if unit in ("", "px"):
                sw = float(value)                         # user units
            elif unit == "%":
                sw = 1.0
            else:
                sw = convert_unit(raw, "mm") / mm         # absolute unit -> user units
            scale = math.sqrt(abs(tr.a * tr.d - tr.b * tr.c)) or 1.0
            stroke_mm = sw * scale * mm
        return Shape(polylines, closed, fill=fill_on, evenodd=evenodd, stroke_mm=stroke_mm)


def compose(m1, m2):
    """SVG matrices: result applies m2 first, then m1."""
    a, b, c, d, e, f = m1
    A, B, C, D, E, F = m2
    return (a * A + c * B, b * A + d * B, a * C + c * D, b * C + d * D,
            a * E + c * F + e, b * E + d * F + f)
