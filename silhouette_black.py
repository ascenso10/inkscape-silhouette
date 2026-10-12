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
Silhouette Solid Black: convert the selected artwork (vectors in any colour,
gradients, bitmaps) to solid black for single-colour printing, e.g.
temporary tattoos.

When every colour is dark enough the vectors are simply recoloured, which is
exact.  Otherwise the artwork is composited as it looks, every point darker
than the threshold becomes black, lighter points become "no ink" (so white
details on top of dark ones become holes), and the result is traced into one
black path.  Doubtful results are reported.
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
from inkex import EffectExtension
from gettext import gettext

from silhouette.InkBlack import convert_to_black


class SilhouetteBlack(EffectExtension):

    def add_arguments(self, pars):
        pars.add_argument("--tab", default="settings")
        pars.add_argument("--mode", default="auto", help="auto|trace|recolor")
        pars.add_argument("--threshold", type=float, default=0.5, help="darkness from which a colour becomes black (0..1)")
        pars.add_argument("--resolution", type=float, default=20.0, help="trace resolution [px/mm]")

    def warn_once(self, key, msg):
        if key not in self.warnings:
            self.warnings.add(key)
            inkex.errormsg(gettext(msg))

    def effect(self):
        self.warnings = set()
        selection = list(self.svg.selection.values()) if len(self.svg.selection) else []
        if not selection:
            inkex.errormsg(gettext("Select the artwork to convert to solid black."))
            return
        try:
            base_dir = self.svg_path()
        except Exception:
            base_dir = None
        _, used, result = convert_to_black(self.svg, selection, self.options.mode, self.options.threshold,
                                           res_mm=self.options.resolution, base_dir=base_dir,
                                           warn=self.warn_once)
        if used == "none":
            inkex.errormsg(gettext("Nothing visible to convert."))
        elif result is not None:
            for w in result.warnings():
                inkex.errormsg(gettext("CHECK: ") + w)


if __name__ == "__main__":
    SilhouetteBlack().run()
