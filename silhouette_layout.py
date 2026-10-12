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
Silhouette Sheet Layout: first step of the print & cut pipeline.

Takes the selected design (a customer's logo, vector or bitmap), converts it
to solid black (tattoos are printed in black only), scales it to the wanted
size, mirrors it (temporary tattoo paper) and repeats it on the sheet as densely as possible inside the
usable area of the registration marks.  The copies are clones of one master
kept in <defs>, placed in a "Print" layer.

Pipeline: Sheet Layout -> Regmarks -> Cut Contour -> Send to Silhouette
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

import re
import inkex
from inkex import EffectExtension, Boolean, Group, Layer, PathElement, Use, Image, TextElement, Transform
from inkex.units import convert_unit
from gettext import gettext

from silhouette.InkShapes import ShapeReader, is_layer, mm_per_uu, image_href, compose
from silhouette.Outline import _bbox_union
from silhouette.InkBlack import convert_to_black
from silhouette.Layout import layout, max_size_for, Region, transform_shapes

MASTER_ID = "tattoo-master"
NOTES_RE = re.compile(r"Left\s*=\s*([-+0-9.eE]+)\s*mm.*?Top\s*=\s*([-+0-9.eE]+)\s*mm.*?"
                      r"X\s*=\s*([-+0-9.eE]+)\s*mm.*?Y\s*=\s*([-+0-9.eE]+)\s*mm", re.DOTALL)


class SilhouetteLayout(EffectExtension):

    def add_arguments(self, pars):
        pars.add_argument("--tab", default="design")
        pars.add_argument("--size", type=float, default=50.0, help="size of one tattoo [mm]")
        pars.add_argument("--size_axis", default="width", help="width|height|longest")
        pars.add_argument("--copies", type=int, default=0, help="number of copies (0 = fill the sheet)")
        pars.add_argument("--mirror", type=Boolean, default=True, help="mirror the design (tattoo paper)")
        pars.add_argument("--black", default="auto", help="solid black conversion: auto|trace|recolor|off")
        pars.add_argument("--threshold", type=float, default=0.5, help="darkness from which a colour becomes black (0..1)")
        pars.add_argument("--gap", type=float, default=3.0, help="minimum distance between two copies [mm]")
        pars.add_argument("--cut_offset", type=float, default=1.5, help="cut line distance, kept inside the usable area [mm]")
        pars.add_argument("--rotate", type=Boolean, default=True, help="allow turning the design 90 degrees")
        pars.add_argument("--one_piece", type=Boolean, default=True, help="treat a design made of separate parts as one piece")
        pars.add_argument("--alternate", type=Boolean, default=True, help="allow every other row/column turned 180 degrees")
        pars.add_argument("--area", default="regmarks", help="regmarks|margin")
        pars.add_argument("--reg_left", type=float, default=15.88)
        pars.add_argument("--reg_top", type=float, default=15.88)
        pars.add_argument("--mark_len", type=float, default=20.0)
        pars.add_argument("--mark_clear", type=float, default=1.0)
        pars.add_argument("--quad", type=Boolean, default=False)
        pars.add_argument("--margin", type=float, default=5.0)
        pars.add_argument("--layer_name", default="Print")
        pars.add_argument("--replace", type=Boolean, default=True)

    # ------------------------------------------------------------ helpers --

    def warn_once(self, key, msg):
        if key not in self.warnings:
            self.warnings.add(key)
            inkex.errormsg(gettext(msg))

    def page_mm(self, mm):
        vb = self.svg.get_viewbox()
        if vb and vb[2] and vb[3]:
            return vb[0] * mm, vb[1] * mm, vb[2] * mm, vb[3] * mm
        return 0.0, 0.0, convert_unit(self.svg.viewport_width, "mm"), convert_unit(self.svg.viewport_height, "mm")

    def document_regmarks(self):
        """(left, top, width, length) in mm from marks drawn by the Regmarks extension."""
        for g in self.svg.iter():
            if not isinstance(g, Group) or "regmark" not in (g.label or "").lower():
                continue
            notes = " ".join("".join(t.itertext()) for t in g.iter() if isinstance(t, TextElement))
            m = NOTES_RE.search(notes)
            if m:
                ml = re.search(r"mark length\s*=\s*([0-9.]+)\s*mm", notes)
                return tuple(float(v) for v in m.groups()) + (float(ml.group(1)) if ml else 0.0,)
        return None

    def region(self, page_w, page_h):
        o = self.options
        if o.area == "margin":
            return Region.with_margin(page_w, page_h, o.margin), "margin %.1f mm" % o.margin
        doc = self.document_regmarks()
        mark_len = o.mark_len
        if doc:
            left, top, width, length, doc_len = doc
            mark_len = doc_len or mark_len
            src = "registration marks found in the document"
        else:
            left, top, width, length = o.reg_left, o.reg_top, 0.0, 0.0
            src = "registration marks at %.1f / %.1f mm" % (left, top)
        return Region.for_regmarks(page_w, page_h, left, top, width, length,
                                   mark_len, o.mark_clear, o.quad), src

    def print_layer(self):
        for child in self.svg:
            if is_layer(child) and (child.label or "") == self.options.layer_name:
                if self.options.replace:
                    for c in list(child):
                        if isinstance(c, Use) and c.href is not None and \
                                (c.href.get("id") or "").startswith(MASTER_ID):
                            master = c.href
                            if master.getparent() is not None:
                                master.getparent().remove(master)
                        child.remove(c)
                return child
        return self.svg.add(Layer.new(self.options.layer_name))

    # ------------------------------------------------------------- effect --

    def effect(self):
        self.warnings = set()
        o = self.options
        selection = list(self.svg.selection.values()) if len(self.svg.selection) else []
        if not selection:
            inkex.errormsg(gettext("Select the design (logo) to repeat on the sheet."))
            return
        try:
            base_dir = self.svg_path()
        except Exception:
            base_dir = None
        mm = mm_per_uu(self.svg)

        # 1. solid black conversion (all tattoos are printed in black)
        report = []
        if o.black != "off":
            reader = ShapeReader(self.svg, base_dir, warn=self.warn_once)
            pre = []
            for el in selection:
                reader.shapes_of(el, out=pre)
            pbb = _bbox_union([s.bbox() for s in pre])
            if pbb is not None:
                pdw, pdh = pbb[2] - pbb[0], pbb[3] - pbb[1]
                pref = {"width": pdw, "height": pdh}.get(o.size_axis, max(pdw, pdh))
                scale = o.size / pref if pref > 0 else 1.0
                try:
                    selection, used, res = convert_to_black(
                        self.svg, selection, o.black, o.threshold, res_mm=20.0 * scale,
                        base_dir=base_dir, warn=self.warn_once)
                except Exception as e:
                    inkex.errormsg(gettext("Could not convert to solid black: %s") % e)
                    return
                if used == "trace" and res is not None:
                    report += res.warnings()

        # 2. geometry of the design (mm, document space)
        reader = ShapeReader(self.svg, base_dir, warn=self.warn_once)
        shapes = []
        for el in selection:
            reader.shapes_of(el, out=shapes)
        bb = _bbox_union([s.bbox() for s in shapes])
        if bb is None:
            inkex.errormsg(gettext("The selection has no visible paths or images."))
            return
        dw, dh = bb[2] - bb[0], bb[3] - bb[1]
        ref = {"width": dw, "height": dh}.get(o.size_axis, max(dw, dh))
        if ref <= 0 or o.size <= 0:
            inkex.errormsg(gettext("Invalid size."))
            return
        s = o.size / ref
        sx = -s if o.mirror else s
        cx, cy = (bb[0] + bb[2]) / 2.0, (bb[1] + bb[3]) / 2.0
        design = transform_shapes(shapes, (sx, 0, 0, s, -sx * cx, -s * cy))

        # 3. layout
        px0, py0, page_w, page_h = self.page_mm(mm)
        region, region_desc = self.region(page_w, page_h)
        kw = dict(gap_mm=o.gap, cut_mm=o.cut_offset, allow_rotation=o.rotate, allow_alternate=o.alternate,
                  one_piece_mm=25.0 if o.one_piece else 0.0)
        result = layout(design, region, o.copies, **kw)
        if not result.placements:
            inkex.errormsg(gettext("The design does not fit in the usable area (%s) at %.1f mm.")
                           % (region_desc, o.size))
            return

        # 4. master in <defs> + clones in the print layer
        master = Group()
        master.set("id", self.svg.get_unique_id(MASTER_ID))
        master.label = "Tattoo master"
        k = 1.0 / mm                                    # mm -> user units
        master.transform = Transform((sx, 0, 0, s, -sx * cx * k, -s * cy * k))
        for el in selection:
            parent = el.getparent()
            holder = Group()
            try:
                holder.transform = parent.composed_transform()
            except AttributeError:
                pass
            parent.remove(el)
            holder.append(el)
            master.append(holder)
        self.svg.defs.append(master)

        layer = self.print_layer()
        for i, pl in enumerate(result.placements, 1):
            use = Use()
            use.set("xlink:href", "#" + master.get("id"))
            use.transform = (Transform(translate=((pl.x + px0) * k, (pl.y + py0) * k))
                             @ Transform(rotate=pl.angle))
            use.label = "tattoo %d" % i
            layer.append(use)

        # 5. report
        n = len(result.placements)
        msg = gettext("%d copies of %.1f mm placed (%s; %s). Room for %d at this size.") % (
            n, o.size, result.description, region_desc, result.capacity)
        if o.copies > result.capacity:
            best = max_size_for(design, region, o.copies, None, lo=0.05, hi=1.0, **kw)
            if best:
                msg += " " + gettext("For %d copies the size must be at most %.1f mm.") % (o.copies, o.size * best)
            else:
                msg += " " + gettext("%d copies do not fit even much smaller.") % o.copies
        for w in report:
            msg += "\n" + gettext("CHECK: ") + w
        inkex.errormsg(msg)


if __name__ == "__main__":
    SilhouetteLayout().run()
