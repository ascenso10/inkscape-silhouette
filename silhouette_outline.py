#!/usr/bin/env python3
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
"""
Silhouette Cut Contour: generate a cut line (offset outline) around every
design on a print & cut sheet.

Each design gets its own closed contour at a given distance from the ink.
Designs packed close together share the space between them (each point goes
to the nearest design), so contours never overlap.  Holes are ignored, giving
a sticker / temporary-tattoo style outer cut.

The contours go to a separate layer that "Send to Silhouette" cuts, while the
artwork layers are tagged "(print)" so the artwork itself is not cut.
"""

import sys, os
sys.path.append(os.path.dirname(os.path.abspath(sys.argv[0])))
sys_platform = sys.platform.lower()
if sys_platform.startswith("win"):
    sys.path.append(r"C:\Program Files\Inkscape\share\inkscape\extensions")
elif sys_platform.startswith("darwin"):
    sys.path.append("/Applications/Inkscape.app/Contents/Resources/share/inkscape/extensions")
else:   # linux
    sys.path.append("/usr/share/inkscape/extensions")

import inkex
from inkex import EffectExtension, Boolean, Group, Layer, PathElement, ShapeElement
from gettext import gettext

from silhouette.Outline import compute_outlines, compute_cut_paths
from silhouette.InkShapes import ShapeReader, is_layer as _is_layer, hidden as _hidden, mm_per_uu

OUTPUT_LAYER_ID = "silhouette-cut-contour"
SKIP_LABEL_WORDS = ("regmark", "cuttingmat")


class SilhouetteOutline(EffectExtension):

    def add_arguments(self, pars):
        pars.add_argument("--tab", default="settings")
        pars.add_argument("--offset", type=float, default=1.5, help="distance between ink and cut line [mm]")
        pars.add_argument("--mode", default="objects", help="objects|islands: what counts as one design")
        pars.add_argument("--join", type=float, default=0.5, help="islands mode: ink closer than this is one design [mm]")
        pars.add_argument("--one_piece", type=Boolean, default=True, help="one contour around a design made of separate parts")
        pars.add_argument("--one_piece_max", type=float, default=25.0, help="largest gap bridged inside one design [mm]")
        pars.add_argument("--merge_cuts", type=Boolean, default=True, help="cut shared lines between neighbours only once")
        pars.add_argument("--merge", type=float, default=2.0, help="cut lines closer than this become one line [mm]")
        pars.add_argument("--gap", type=float, default=0.0, help="minimum distance between neighbouring cut lines [mm]")
        pars.add_argument("--resolution", type=float, default=10.0, help="raster resolution [px/mm]")
        pars.add_argument("--simplify", type=float, default=0.03, help="path simplification tolerance [mm]")
        pars.add_argument("--min_area", type=float, default=2.0, help="ignore contours smaller than this [mm^2]")
        pars.add_argument("--layer_name", default="Cut contour", help="name of the layer receiving the contours")
        pars.add_argument("--replace", type=Boolean, default=True, help="replace contours from a previous run")
        pars.add_argument("--mark_print", type=Boolean, default=True, help="add '(print)' to the artwork layer names")
        pars.add_argument("--color", default="#ff0000", help="stroke colour of the contours")

    # ------------------------------------------------------------ helpers --

    def is_output_layer(self, node):
        return node.get("id") == OUTPUT_LAYER_ID or (
            _is_layer(node) and (node.label or "") == self.options.layer_name)

    def skip_group(self, node):
        if self.is_output_layer(node):
            return True
        label = (node.label or "").lower() if isinstance(node, Group) else ""
        return any(w in label for w in SKIP_LABEL_WORDS)

    def collect_designs(self):
        """Returns [(element, top_level_layer_or_None)], one per design."""
        designs = []
        selection = list(self.svg.selection.values()) if len(self.svg.selection) else []

        def from_layer(layer, top):
            for child in layer:
                if not isinstance(child, ShapeElement) or _hidden(child):
                    continue
                if _is_layer(child):
                    if not self.skip_group(child):
                        from_layer(child, top)
                elif isinstance(child, Group) and self.skip_group(child):
                    continue
                else:
                    designs.append((child, top))

        if selection:
            for el in selection:
                if _is_layer(el):
                    if not self.skip_group(el):
                        from_layer(el, el)
                elif not (isinstance(el, Group) and self.skip_group(el)):
                    designs.append((el, el.getparent() if _is_layer(el.getparent()) else None))
        else:
            for child in self.svg:
                if not isinstance(child, ShapeElement) or _hidden(child):
                    continue
                if _is_layer(child):
                    if not self.skip_group(child):
                        from_layer(child, child)
                elif not (isinstance(child, Group) and self.skip_group(child)):
                    designs.append((child, None))
        return designs

    def warn_once(self, key, msg):
        if key not in self.warnings:
            self.warnings.add(key)
            inkex.errormsg(gettext(msg))

    def output_layer(self):
        for child in self.svg:
            if self.is_output_layer(child):
                if self.options.replace:
                    for c in list(child):
                        child.remove(c)
                return child
        layer = self.svg.add(Layer.new(self.options.layer_name))
        layer.set("id", OUTPUT_LAYER_ID)
        return layer

    # ------------------------------------------------------------- effect --

    def effect(self):
        self.warnings = set()
        opt = self.options
        mm = mm_per_uu(self.svg)
        try:
            base_dir = self.svg_path()
        except Exception:
            base_dir = None
        reader = ShapeReader(self.svg, base_dir, self.skip_group, self.warn_once)

        designs = self.collect_designs()
        items, tops = [], []
        for el, top in designs:
            shapes = reader.shapes_of(el)
            if shapes:
                items.append(shapes)
                tops.append(top)
        if not items:
            inkex.errormsg(gettext("Nothing to outline: select the designs, or make sure the artwork "
                                   "layers are visible and contain paths."))
            return

        common = dict(offset_mm=opt.offset, res=max(opt.resolution, 2.0), simplify_mm=opt.simplify,
                      islands=(opt.mode == "islands"), join_mm=opt.join, min_area_mm2=opt.min_area,
                      one_piece_mm=(opt.one_piece_max if opt.one_piece and opt.mode != "islands" else 0.0))
        multi = 0
        if opt.merge_cuts:
            # shared lines between neighbours are emitted once (open paths)
            paths = compute_cut_paths(items, merge_mm=opt.merge, **common)
        else:
            paths = []
            for polys in compute_outlines(items, gap_mm=opt.gap, **common):
                multi += len(polys) > 1
                paths += [(p, True) for p in polys]

        layer = self.output_layer()
        inv = -layer.transform if layer.get("transform") else None
        stroke_uu = 0.2 / mm
        for n, (p, closed) in enumerate(paths, 1):
            d = "M " + " L ".join("%.4f,%.4f" % (x / mm, y / mm) for x, y in p) + (" Z" if closed else "")
            el = PathElement()
            el.set("d", d)
            if inv is not None:
                el.path = el.path.transform(inv)
            el.style = {"fill": "none", "stroke": opt.color, "stroke-width": "%.4f" % stroke_uu}
            el.label = "cut %d" % n
            layer.append(el)

        if opt.mark_print:
            seen = set()
            for top in tops:
                if top is None or id(top) in seen or not _is_layer(top):
                    continue
                seen.add(id(top))
                label = top.label or top.get("id") or "Artwork"
                if "print" not in label.lower():
                    top.label = label + " (print)"
            if any(t is None for t in tops):
                inkex.errormsg(gettext(
                    "Note: some designs are not inside a layer. Move the artwork into a layer whose "
                    "name contains 'print', otherwise Send to Silhouette will cut the artwork too."))

        if multi:
            inkex.errormsg(gettext(
                "Note: %d design(s) produced more than one contour (parts further apart than the "
                "one-piece limit, or squeezed by neighbours). Group the parts (Ctrl+G) or increase the limit.") % multi)


if __name__ == "__main__":
    SilhouetteOutline().run()
