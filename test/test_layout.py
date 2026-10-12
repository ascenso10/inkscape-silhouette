import os, sys, struct, unittest, zlib
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from silhouette.Outline import Shape, RasterShape, compute_outlines
from silhouette.Layout import layout, Region, transform_shapes
from silhouette.Raster import _decode_png, trace, ink_mask


def rect(x, y, w, h):
    return np.array([[x, y], [x + w, y], [x + w, y + h], [x, y + h]], dtype=float)


def png_bytes(rgba_u8):
    h, w, _ = rgba_u8.shape
    raw = b"".join(b"\x00" + rgba_u8[y].tobytes() for y in range(h))

    def chunk(t, d):
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


def overlaps(result, w, h, gap):
    """Axis-aligned check for a rectangle design (0/90/180/270 degrees)."""
    boxes = []
    for p in result.placements:
        ww, hh = (w, h) if p.angle % 180 == 0 else (h, w)
        boxes.append((p.x - ww / 2, p.y - hh / 2, p.x + ww / 2, p.y + hh / 2))
    for i in range(len(boxes)):
        for j in range(i + 1, len(boxes)):
            a, b = boxes[i], boxes[j]
            dx = max(b[0] - a[2], a[0] - b[2])
            dy = max(b[1] - a[3], a[1] - b[3])
            if max(dx, dy) < gap - 0.6:
                return True
    return False


class TestLayout(unittest.TestCase):

    def test_rectangles_fill_a_page(self):
        design = [Shape([rect(0, 0, 40, 20)])]
        region = Region.with_margin(210, 297, 5)
        r = layout(design, region, 0, gap_mm=3, cut_mm=1.5)
        # 200 x 287 usable: 4 columns x 12 rows of 43 x 23 cells (or better)
        self.assertGreaterEqual(r.capacity, 4 * 12)
        self.assertFalse(overlaps(r, 40, 20, 3))
        for p in r.placements:
            ww, hh = (40, 20) if p.angle % 180 == 0 else (20, 40)
            self.assertGreaterEqual(p.x - ww / 2, 5 + 1.5 - 0.6)
            self.assertLessEqual(p.x + ww / 2, 205 - 1.5 + 0.6)

    def test_requested_copies(self):
        design = [Shape([rect(0, 0, 30, 30)])]
        r = layout(design, Region.with_margin(210, 297, 5), 5, gap_mm=2, cut_mm=1)
        self.assertEqual(len(r.placements), 5)
        self.assertGreater(r.capacity, 5)

    def test_regmark_corners_are_avoided(self):
        design = [Shape([rect(0, 0, 25, 25)])]
        region = Region.for_regmarks(210, 297, 10, 10, mark_len=20, clearance=1)
        r = layout(design, region, 0, gap_mm=2, cut_mm=1)
        for p in r.placements:
            for cx0, cy0, cx1, cy1 in region.corners:
                inside = (p.x + 13.5 > cx0 and p.x - 13.5 < cx1 and p.y + 13.5 > cy0 and p.y - 13.5 < cy1)
                self.assertFalse(inside, (p, (cx0, cy0, cx1, cy1)))

    def test_alternating_rows_interlock_triangles(self):
        tri = [Shape([np.array([[0, 30], [15, 0], [30, 30]], dtype=float)])]
        region = Region.with_margin(210, 297, 5)
        same = layout(tri, region, 0, gap_mm=2, cut_mm=1, allow_alternate=False)
        alt = layout(tri, region, 0, gap_mm=2, cut_mm=1)
        self.assertGreater(alt.capacity, same.capacity)
        self.assertTrue(any(p.angle % 360 in (90, 180, 270) for p in alt.placements))

    def test_too_big(self):
        r = layout([Shape([rect(0, 0, 300, 300)])], Region.with_margin(210, 297, 5), 1)
        self.assertEqual(r.capacity, 0)


class TestRaster(unittest.TestCase):

    def test_png_decoder_and_trace(self):
        img = np.zeros((40, 50, 4), dtype=np.uint8)
        img[10:30, 10:40] = (0, 0, 0, 255)          # black block on transparent
        img[15:25, 20:30] = (255, 255, 255, 255)    # white hole (no ink on tattoo paper)
        rgba = _decode_png(png_bytes(img))
        np.testing.assert_allclose(rgba * 255, img, atol=0.5)
        m = ink_mask(rgba)
        self.assertEqual(int(m.sum()), 20 * 30 - 10 * 10)
        polys = trace(rgba)
        self.assertEqual(len(polys), 2)              # outer + hole (even-odd)

    def test_raster_shape_outline(self):
        mask = np.zeros((20, 20), dtype=bool)
        mask[5:15, 5:15] = True
        # 1 px = 1 mm, image placed at (100, 50)
        s = RasterShape(mask, (1, 0, 0, 1, 100, 50))
        p = compute_outlines([[s]], offset_mm=1.0)[0][0]
        np.testing.assert_allclose(p.min(axis=0), [104, 54], atol=0.15)
        np.testing.assert_allclose(p.max(axis=0), [116, 66], atol=0.15)


if __name__ == "__main__":
    unittest.main()
