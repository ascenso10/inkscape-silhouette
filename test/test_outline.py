import os, sys, unittest
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from silhouette.Outline import Shape, compute_outlines, compute_cut_paths


def square(x, y, s):
    return np.array([[x, y], [x + s, y], [x + s, y + s], [x, y + s]], dtype=float)


class TestOutline(unittest.TestCase):

    def test_single_square_offset(self):
        out = compute_outlines([[Shape([square(0, 0, 10)])]], offset_mm=1.0)
        self.assertEqual(len(out), 1)
        self.assertEqual(len(out[0]), 1)
        p = out[0][0]
        np.testing.assert_allclose(p.min(axis=0), [-1, -1], atol=0.1)
        np.testing.assert_allclose(p.max(axis=0), [11, 11], atol=0.1)

    def test_holes_are_not_cut(self):
        ring = Shape([square(0, 0, 20), square(5, 5, 10)[::-1]], evenodd=True)
        out = compute_outlines([[ring]], offset_mm=1.0)
        self.assertEqual(len(out[0]), 1)

    def test_close_neighbours_get_separate_contours(self):
        # 1 mm apart with a 1.5 mm offset: the contours must meet half way
        a, b = Shape([square(0, 0, 10)]), Shape([square(11, 0, 10)])
        out = compute_outlines([[a], [b]], offset_mm=1.5)
        self.assertEqual([len(o) for o in out], [1, 1])
        self.assertLessEqual(out[0][0][:, 0].max(), 10.5 + 0.1)
        self.assertGreaterEqual(out[1][0][:, 0].min(), 10.5 - 0.1)

    def test_gap_between_neighbours(self):
        a, b = Shape([square(0, 0, 10)]), Shape([square(11, 0, 10)])
        out = compute_outlines([[a], [b]], offset_mm=1.5, gap_mm=0.4)
        self.assertGreaterEqual(out[1][0][:, 0].min() - out[0][0][:, 0].max(), 0.3)

    def test_islands_mode_splits_one_path(self):
        both = Shape([square(0, 0, 10), square(14, 0, 10)])
        out = compute_outlines([[both]], offset_mm=1.0, islands=True)
        self.assertEqual(len(out), 2)

    def test_islands_mode_keeps_details_inside_a_design(self):
        # an open frame (U shape) with a small detail inside belongs together
        frame = Shape([np.array([[0, 0], [2, 0], [2, 18], [18, 18], [18, 0], [20, 0],
                                 [20, 20], [0, 20]], dtype=float)])
        detail = Shape([square(8, 6, 3)])
        out = compute_outlines([[frame, detail]], offset_mm=1.0, islands=True)
        self.assertEqual(len(out), 1)

    def test_stroke_only_line(self):
        line = Shape([np.array([[0, 0], [0, 20]], dtype=float)], [False], fill=False, stroke_mm=2.0)
        p = compute_outlines([[line]], offset_mm=1.0)[0][0]
        np.testing.assert_allclose(p[:, 0].min(), -2.0, atol=0.15)
        np.testing.assert_allclose(p[:, 0].max(), 2.0, atol=0.15)

    @staticmethod
    def _length(paths):
        total = 0.0
        for p, closed in paths:
            q = np.vstack((p, p[:1])) if closed else p
            total += np.hypot(*np.diff(q, axis=0).T).sum()
        return total

    @staticmethod
    def _densify(p, closed, step=0.05):
        q = np.vstack((p, p[:1])) if closed else p
        out = [q[:1]]
        for a, b in zip(q[:-1], q[1:]):
            n = max(int(np.hypot(*(b - a)) / step), 1)
            out.append(a + (b - a) * np.linspace(0, 1, n + 1)[1:, None])
        return np.vstack(out)

    def test_merge_shared_line_is_cut_once(self):
        # squares 1 mm apart, offset 1.5: separate contours share x = 10.5
        a, b = Shape([square(0, 0, 10)]), Shape([square(11, 0, 10)])
        paths = compute_cut_paths([[a], [b]], offset_mm=1.5, merge_mm=0.5)
        self.assertEqual(sorted(c for _, c in paths), [False, True])
        separate = compute_outlines([[a], [b]], offset_mm=1.5)
        sep_len = self._length([(p, True) for o in separate for p in o])
        # the shared 10 mm (+ offsets) stretch is no longer cut twice
        self.assertLess(self._length(paths), sep_len - 10)

    def test_merge_close_parallel_lines(self):
        # 4 mm apart, offset 1: cut lines 2 mm apart -> merged with merge 3
        a, b = Shape([square(0, 0, 10)]), Shape([square(14, 0, 10)])
        self.assertEqual([c for _, c in compute_cut_paths([[a], [b]], offset_mm=1.0, merge_mm=1.0)],
                         [True, True])
        merged = compute_cut_paths([[a], [b]], offset_mm=1.0, merge_mm=3.0)
        self.assertEqual(sorted(c for _, c in merged), [False, True])
        pts = np.vstack([self._densify(p, c) for p, c in merged])
        # along the facing sides only the shared line at x = 12 is cut
        side = pts[(pts[:, 1] > 1) & (pts[:, 1] < 9)]
        mid = side[(side[:, 0] > 10.5) & (side[:, 0] < 13.5), 0]
        self.assertTrue(len(mid) > 0)
        np.testing.assert_allclose(mid, 12.0, atol=0.15)


if __name__ == "__main__":
    unittest.main()
