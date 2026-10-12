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
Silhouette Calibration Sheet: measure the offset between printer and cutter,
for cutting printed sheets WITHOUT registration marks (when the cutter's mark
sensor is unreliable).

At five places on the page it prints a small target with two millimetre
scales (0.5 mm ticks), and puts a cut line across each scale at the nominal
position.  After printing, placing the sheet in the corner of the mat grid
and cutting with registration marks switched off, the cut lines show directly
on the scales how far the cutter is from the print, horizontally and
vertically.  The negative of the average reading goes into Send to
Silhouette as X-Offset / Y-Offset.
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
from inkex import EffectExtension, Layer, PathElement, TextElement, Transform
from gettext import gettext

PRINT_LAYER_ID = "silhouette-calibration-print"
CUT_LAYER_ID = "silhouette-calibration-cut"

TICK = 0.5          # mm between ticks
HALF_RANGE = 3.0    # scale goes from -3 to +3 mm
LINE = 0.12         # printed line width [mm]


class SilhouetteCalibration(EffectExtension):

    def add_arguments(self, pars):
        pars.add_argument("--tab", default="settings")
        pars.add_argument("--inset", type=float, default=25.0, help="distance of the targets from the page edges [mm]")
        pars.add_argument("--max_width", type=float, default=195.0,
                          help="keep targets within this width from the left edge [mm] (0 = page width)")

    def page_mm(self):
        vb = self.svg.get_viewbox()
        mm = self.svg.viewport_to_unit("1mm")
        if vb and vb[2] and vb[3]:
            return vb[2] / mm, vb[3] / mm, mm
        return self.svg.to_dimensional(self.svg.viewport_width, "mm"), \
            self.svg.to_dimensional(self.svg.viewport_height, "mm"), mm

    @staticmethod
    def path(d, width=LINE):
        el = PathElement()
        el.set("d", d)
        el.style = {"fill": "none", "stroke": "#000000", "stroke-width": "%g" % width}
        return el

    @staticmethod
    def text(s, x, y, size=1.6, anchor="middle"):
        t = TextElement(s, x="%g" % x, y="%g" % y)
        t.style = {"font-size": "%gpx" % size, "font-family": "sans-serif", "text-anchor": anchor,
                   "fill": "#000000"}
        return t

    def target(self, prn, cut, x, y, label):
        # printed reference cross
        prn.append(self.path("M %g,%g H %g M %g,%g V %g" % (x - 2, y, x + 2, x, y - 2, y + 2)))
        prn.append(self.text(label, x - 3, y - 3, 2.0, "end"))
        n = int(round(HALF_RANGE / TICK))
        # horizontal scale below the cross (reads the X offset)
        y0 = y + 4
        d = []
        for k in range(-n, n + 1):
            tx = x + k * TICK
            h = 2.0 if k % 2 == 0 else 1.0
            d.append("M %g,%g V %g" % (tx, y0, y0 + h))
        d.append("M %g,%g H %g" % (x - HALF_RANGE, y0, x + HALF_RANGE))
        prn.append(self.path(" ".join(d), 0.08))
        for v in (-2, 0, 2):
            prn.append(self.text("%+d" % v if v else "0", x + v, y0 + 3.6, 1.2))
        # vertical scale right of the cross (reads the Y offset)
        x0 = x + 4
        d = []
        for k in range(-n, n + 1):
            ty = y + k * TICK
            w = 2.0 if k % 2 == 0 else 1.0
            d.append("M %g,%g H %g" % (x0, ty, x0 + w))
        d.append("M %g,%g V %g" % (x0, y - HALF_RANGE, y + HALF_RANGE))
        prn.append(self.path(" ".join(d), 0.08))
        for k in range(-n, n + 1, 2):
            v = k * TICK
            prn.append(self.text("%+d" % v if v else "0", x0 + 3.0, y + v + 0.45, 1.2, "start"))
        # cut lines at the nominal positions, crossing the scales
        cut.append(self.path("M %g,%g V %g" % (x, y0 - 1, y0 + 6), 0.2))
        cut.append(self.path("M %g,%g H %g" % (x0 - 1, y, x0 + 6), 0.2))

    def effect(self):
        o = self.options
        w, h, mm = self.page_mm()
        for lid in (PRINT_LAYER_ID, CUT_LAYER_ID):
            old = self.svg.getElementById(lid)
            if old is not None:
                old.getparent().remove(old)
        right = (o.max_width or w) - o.inset - 10
        pts = [(o.inset, o.inset, "A"), (right, o.inset, "B"), ((o.inset + right) / 2, h / 2, "C"),
               (o.inset, h - o.inset - 10, "D"), (right, h - o.inset - 10, "E")]

        prn = Layer.new("Calibration (print)")
        prn.set("id", PRINT_LAYER_ID)
        prn.transform = Transform(scale=mm)
        cut = Layer.new("Calibration cut")
        cut.set("id", CUT_LAYER_ID)
        cut.transform = Transform(scale=mm)
        for x, y, label in pts:
            self.target(prn, cut, x, y, label)

        lines = [
            "Calibration without registration marks:",
            "1. Hide the 'Calibration cut' layer and print at 100% (actual size).",
            "2. Put the sheet exactly in the top-left corner of the mat grid.",
            "3. Send to Silhouette with registration marks OFF and X/Y-Offset 0.",
            "4. At each target read where the cut crosses the scales (+ = cut right / below the print).",
            "5. Enter MINUS the average reading as X-Offset and Y-Offset in Send to Silhouette.",
            "Different readings at A..E mean the sheet was placed crooked: place it again and repeat.",
        ]
        for i, line in enumerate(lines):
            prn.append(self.text(line, o.inset, h / 2 + 18 + i * 3.2, 2.2, "start"))

        self.svg.append(prn)
        self.svg.append(cut)


if __name__ == "__main__":
    SilhouetteCalibration().run()
