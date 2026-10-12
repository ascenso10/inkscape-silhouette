# (c) 2026 - Solid black conversion of Inkscape elements.
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
"""
Reads the colours of the selected elements (fills, strokes, opacity, gradients
as their average colour, bitmaps) and converts them to solid black, either by
recolouring the vectors (when every colour is dark enough, which is exact) or
by compositing and tracing (silhouette.Black.to_black).
Used by silhouette_black.py and silhouette_layout.py.
"""

import re
import numpy as np

import inkex
from inkex import Group, PathElement, Use, ShapeElement, Image, TextElement, Transform

from silhouette.InkShapes import ShapeReader, SHAPE_TYPES, style_get, hidden, image_href, compose
from silhouette.Raster import load_image, image_placement
from silhouette.Black import Paint, PaintShape, PaintImage, to_black, paints_all_dark

_NAMED = {
    "black": (0, 0, 0), "white": (255, 255, 255), "red": (255, 0, 0), "lime": (0, 255, 0),
    "green": (0, 128, 0), "blue": (0, 0, 255), "yellow": (255, 255, 0), "cyan": (0, 255, 255),
    "aqua": (0, 255, 255), "magenta": (255, 0, 255), "fuchsia": (255, 0, 255), "gray": (128, 128, 128),
    "grey": (128, 128, 128), "silver": (192, 192, 192), "maroon": (128, 0, 0), "olive": (128, 128, 0),
    "purple": (128, 0, 128), "teal": (0, 128, 128), "navy": (0, 0, 128), "orange": (255, 165, 0),
    "gold": (255, 215, 0), "pink": (255, 192, 203), "brown": (165, 42, 42),
}


def parse_color(value):
    """CSS colour -> (r, g, b) in 0..1, or None."""
    v = str(value or "").strip().lower()
    if not v or v in ("none", "transparent"):
        return None
    m = re.fullmatch(r"#([0-9a-f]{3}|[0-9a-f]{6})", v)
    if m:
        h = m.group(1)
        if len(h) == 3:
            h = "".join(c * 2 for c in h)
        return tuple(int(h[i:i + 2], 16) / 255.0 for i in (0, 2, 4))
    m = re.fullmatch(r"rgba?\(([^)]*)\)", v)
    if m:
        parts = [p.strip() for p in m.group(1).split(",")]
        out = []
        for p in parts[:3]:
            out.append(float(p[:-1]) / 100.0 if p.endswith("%") else float(p) / 255.0)
        return tuple(out)
    if v in _NAMED:
        return tuple(c / 255.0 for c in _NAMED[v])
    try:
        c = inkex.Color(v).to_rgb()
        return (c[0] / 255.0, c[1] / 255.0, c[2] / 255.0)
    except Exception:
        return (0.0, 0.0, 0.0)            # unknown: assume ink


def _float(v, default=1.0):
    try:
        return float(str(v).strip().rstrip("%")) / (100.0 if str(v).strip().endswith("%") else 1.0)
    except (TypeError, ValueError):
        return default


class PaintReader(ShapeReader):
    """Like ShapeReader, but keeps colours: returns PaintShape / PaintImage."""

    def paints_of(self, node, parent_transform=None, opacity=1.0, out=None):
        if out is None:
            out = []
        if not isinstance(node, ShapeElement) or hidden(node):
            return out
        tr = node.composed_transform() if parent_transform is None else parent_transform @ node.transform
        if parent_transform is None:
            # opacity of the ancestors
            for anc in node.iterancestors():
                if isinstance(anc, ShapeElement):
                    opacity *= _float(anc.style.get("opacity", 1.0))
        opacity *= _float(node.style.get("opacity", node.get("opacity", 1.0)))

        if isinstance(node, Group):
            if self.skip_group(node):
                return out
            for child in node:
                self.paints_of(child, tr, opacity, out)
        elif isinstance(node, Use):
            ref = node.href
            if ref is not None:
                x = float(node.get("x", 0.0) or 0.0)
                y = float(node.get("y", 0.0) or 0.0)
                self.paints_of(ref, tr @ Transform(translate=(x, y)), opacity, out)
        elif isinstance(node, SHAPE_TYPES):
            shape = self.shape_from_element(node, tr)
            if shape is not None:
                fill = self.paint(node, "fill", "#000000", opacity)
                stroke = self.paint(node, "stroke", "none", opacity)
                out.append(PaintShape(shape, fill, stroke))
        elif isinstance(node, Image):
            try:
                rgba = load_image(image_href(node), self.base_dir)
            except Exception as e:
                self.warn("image", "Warning: could not read a bitmap image (%s)." % e)
                return out
            h, w = rgba.shape[:2]
            x, y = float(node.get("x", 0) or 0), float(node.get("y", 0) or 0)
            p = image_placement(x, y, float(node.get("width", w) or w), float(node.get("height", h) or h),
                                w, h, node.get("preserveAspectRatio"))
            m = compose((tr.a, tr.b, tr.c, tr.d, tr.e, tr.f), p)
            rgba = rgba.copy()
            rgba[..., 3] *= opacity
            out.append(PaintImage(rgba, tuple(v * self.mm for v in m)))
        elif isinstance(node, TextElement):
            self.warn("text", "Warning: text is ignored; convert it to a path first (Path > Object to Path).")
        return out

    def paint(self, node, key, default, opacity):
        value = str(style_get(node, key, default) or default).strip()
        alpha = opacity * _float(style_get(node, key + "-opacity", 1.0))
        if value.startswith("url("):
            rgb, a = self.gradient_average(value)
            if rgb is None:
                return None
            return Paint(rgb, alpha * a)
        if value.lower() == "currentcolor":
            value = style_get(node, "color", "#000000")
        rgb = parse_color(value)
        return None if rgb is None else Paint(rgb, alpha)

    def gradient_average(self, value):
        m = re.match(r"url\(\s*#([^)\s]+)\s*\)", value)
        el = self.svg.getElementById(m.group(1)) if m else None
        seen = 0
        while el is not None and seen < 10:
            stops = [s for s in el if str(s.tag).endswith("stop")]
            if stops:
                cols, alphas = [], []
                for s in stops:
                    st = s.style if hasattr(s, "style") else {}
                    c = parse_color(st.get("stop-color", s.get("stop-color", "#000000")))
                    cols.append(c if c is not None else (1.0, 1.0, 1.0))
                    alphas.append(_float(st.get("stop-opacity", s.get("stop-opacity", 1.0))))
                return tuple(np.mean(np.array(cols), axis=0)), float(np.mean(alphas))
            href = el.get("xlink:href") or el.get("href")
            el = self.svg.getElementById(href[1:]) if href and href.startswith("#") else None
            seen += 1
        return None, 0.0


def _shape_elements(el):
    if isinstance(el, SHAPE_TYPES):
        yield el
    for d in el.iterdescendants():
        if isinstance(d, SHAPE_TYPES):
            yield d


def recolor_black(selection):
    """Make every visible paint solid black, keeping the vectors."""
    for el in selection:
        for g in [el] + list(el.iterdescendants()):
            if isinstance(g, (Group, Use)) and "opacity" in g.style:
                st = g.style
                st["opacity"] = "1"
                g.style = st
        for node in _shape_elements(el):
            st = node.style
            new = {}
            fill = style_get(node, "fill", "#000000")
            if str(fill).strip().lower() not in ("none", "transparent"):
                new["fill"] = "#000000"
                new["fill-opacity"] = "1"
            stroke = style_get(node, "stroke", "none")
            if str(stroke).strip().lower() not in ("none", "transparent", ""):
                new["stroke"] = "#000000"
                new["stroke-opacity"] = "1"
            if new:
                st.update(new)
                if "opacity" in st:
                    st["opacity"] = "1"
                node.style = st


def convert_to_black(svg, selection, mode="auto", threshold=0.5, res_mm=20.0, base_dir=None, warn=None):
    """Convert the selection to solid black.

    mode: 'auto' (recolour when every colour is dark, otherwise trace),
          'trace' (always composite + trace), 'recolor' (recolour only).
    Returns (new_selection, used_mode, BlackResult or None)."""
    reader = PaintReader(svg, base_dir, warn=warn)
    items = []
    for el in selection:
        reader.paints_of(el, out=items)
    if not items:
        return selection, "none", None
    if mode == "recolor" or (mode == "auto" and paints_all_dark(items, threshold)):
        recolor_black(selection)
        return selection, "recolor", None

    result = to_black(items, res=res_mm, threshold=threshold)
    mm = reader.mm
    first = selection[0]
    parent = first.getparent()
    path = PathElement()
    path.set("d", " ".join("M " + " L ".join("%.4f,%.4f" % (x / mm, y / mm) for x, y in p) + " Z"
                           for p in result.polygons))
    try:
        inv = -parent.composed_transform()
        path.transform = inv
    except AttributeError:
        pass
    path.style = {"fill": "#000000", "fill-rule": "evenodd", "stroke": "none"}
    path.label = "solid black"
    parent.insert(parent.index(first), path)
    for el in selection:
        el.getparent().remove(el)
    return [path], "trace", result
