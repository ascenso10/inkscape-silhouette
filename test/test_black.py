import os, sys, unittest
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from silhouette.Outline import Shape, compute_outlines
from silhouette.Black import Paint, PaintShape, PaintImage, to_black, paints_all_dark
from silhouette.Layout import layout, Region


def rect(x, y, w, h):
    return np.array([[x, y], [x + w, y], [x + w, y + h], [x, y + h]], dtype=float)


def area(polys):
    tot = 0.0
    for p in polys:
        x, y = p[:, 0], p[:, 1]
        tot += 0.5 * (np.dot(x, np.roll(y, -1)) - np.dot(np.roll(x, -1), y))
    return abs(tot)


BLACK, WHITE = Paint((0, 0, 0)), Paint((1, 1, 1))


class TestBlack(unittest.TestCase):

    def test_white_on_dark_becomes_a_hole(self):
        r = to_black([PaintShape(Shape([rect(0, 0, 20, 20)]), Paint((0.1, 0.4, 0.1))),
                      PaintShape(Shape([rect(5, 5, 10, 10)]), WHITE)])
        self.assertEqual(len(r.polygons), 2)                 # outer + hole
        # even-odd area: 400 - 100
        outer = max(r.polygons, key=lambda p: area([p]))
        inner = min(r.polygons, key=lambda p: area([p]))
        self.assertAlmostEqual(area([outer]) - area([inner]), 300, delta=3)
        self.assertFalse(r.all_dark)

    def test_light_colour_is_dropped_and_reported(self):
        r = to_black([PaintShape(Shape([rect(0, 0, 10, 10)]), BLACK),
                      PaintShape(Shape([rect(20, 0, 10, 10)]), Paint((1, 0.92, 0.2)))])
        self.assertEqual(len(r.polygons), 1)
        self.assertGreater(r.lost, 0.4)
        self.assertTrue(any("too light" in w for w in r.warnings()))

    def test_lower_threshold_keeps_light_colour(self):
        r = to_black([PaintShape(Shape([rect(20, 0, 10, 10)]), Paint((1, 0.92, 0.2)))], threshold=0.1)
        self.assertEqual(len(r.polygons), 1)

    def test_colour_only_boundaries_are_reported(self):
        r = to_black([PaintShape(Shape([rect(0, 0, 20, 20)]), Paint((0.8, 0, 0))),
                      PaintShape(Shape([rect(20, 0, 20, 20)]), Paint((0, 0, 0.6)))])
        self.assertGreater(r.merged, 0.9)

    def test_dark_vectors_can_just_be_recoloured(self):
        items = [PaintShape(Shape([rect(0, 0, 10, 10)]), Paint((0.2, 0.1, 0.5))),
                 PaintShape(Shape([rect(0, 0, 5, 5)]), Paint((0.7, 0.0, 0.0)))]
        self.assertTrue(paints_all_dark(items, 0.5))
        self.assertFalse(paints_all_dark(items + [PaintShape(Shape([rect(0, 0, 1, 1)]), WHITE)], 0.5))

    def test_bitmap(self):
        rgba = np.ones((10, 10, 4), dtype=np.float32)
        rgba[2:8, 2:8, :3] = 0.1                              # dark square on white, 1 px = 1 mm
        r = to_black([PaintImage(rgba, (1, 0, 0, 1, 0, 0))])
        self.assertEqual(len(r.polygons), 1)
        self.assertAlmostEqual(area(r.polygons), 36, delta=2)


class TestOnePiece(unittest.TestCase):

    def design(self):
        # two parts 6 mm apart
        return [Shape([rect(0, 0, 10, 20), rect(16, 0, 10, 20)])]

    def test_contour_around_separate_parts(self):
        self.assertEqual(len(compute_outlines([self.design()], offset_mm=1.0)[0]), 2)
        self.assertEqual(len(compute_outlines([self.design()], offset_mm=1.0, one_piece_mm=10)[0]), 1)

    def test_copies_do_not_slip_between_parts(self):
        # a 4 mm wide part fits in the 6 mm gap unless the design is kept in one piece
        thin = [Shape([rect(0, 0, 10, 20), rect(16, 0, 10, 20)])]
        r = layout(thin, Region.with_margin(210, 297, 5), 0, gap_mm=0.5, cut_mm=0.5, one_piece_mm=20)
        for i, a in enumerate(r.placements):
            for b in r.placements[i + 1:]:
                ax, ay = (26, 20) if a.angle % 180 == 0 else (20, 26)
                bx, by = (26, 20) if b.angle % 180 == 0 else (20, 26)
                sep_x = abs(a.x - b.x) - (ax + bx) / 2
                sep_y = abs(a.y - b.y) - (ay + by) / 2
                self.assertGreater(max(sep_x, sep_y), -0.6, (a, b))


if __name__ == "__main__":
    unittest.main()
