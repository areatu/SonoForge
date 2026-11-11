"""Optional authoring checks: run with Pillow and NumPy installed."""
import importlib.util
from pathlib import Path
import re
import unittest

SOURCE = Path(__file__).resolve().parents[1] / 'generate_clinical_media.py'
AVAILABLE = all(importlib.util.find_spec(name) is not None for name in ('PIL', 'numpy'))


@unittest.skipUnless(AVAILABLE, 'authoring dependencies Pillow / NumPy not installed')
class ClinicalPreviewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        spec = importlib.util.spec_from_file_location('clinical_media', SOURCE)
        cls.media = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.media)

    def test_frozen_ultrasound(self):
        self.assertEqual(self.media.ultrasound(0).tobytes(),
                         self.media.ultrasound(.4).tobytes())

    def test_open_contour_from_septal_annulus_via_apex_to_lateral_annulus(self):
        pts = self.media.LV_CONTOUR
        self.assertEqual(pts[0], self.media.reference_point(226, 239))
        self.assertEqual(pts[-1], self.media.reference_point(326, 207))
        apex = min(range(len(pts)), key=lambda i: pts[i][1])
        self.assertGreater(apex, 0)
        self.assertLess(apex, len(pts)-1)
        self.assertLess(pts[apex][1], self.media.reference_point(0, 70)[1])
        self.assertNotEqual(pts[0], pts[-1])

    def test_anatomy_has_transparent_cavities(self):
        image = self.media.a4c_schematic()
        self.assertEqual(image.mode, 'RGBA')
        for point in ((245,140), (151,150), (180,315), (295,300)):
            x,y = self.media.reference_point(*point)
            self.assertEqual(image.getpixel((round(x),round(y)))[3], 0)

    def test_caliper_intersects_both_walls_at_same_height(self):
        left,right = self.media.wall_intersections(140)
        self.assertLess(left,right)
        for x in (left,right):
            self.assertTrue(any(
                min(a[1],b[1]) <= 140 <= max(a[1],b[1])
                and min(a[0],b[0])-1e-6 <= x <= max(a[0],b[0])+1e-6
                for a,b in zip(self.media.REFERENCE_CONTOUR,self.media.REFERENCE_CONTOUR[1:])
            ))
        self.assertEqual(self.media.reference_point(left,140)[1],
                         self.media.reference_point(right,140)[1])

    def test_english_labels(self):
        self.assertIsNone(re.search('[А-Яа-яЁё]', SOURCE.read_text()))

    def test_all_gifs_decode(self):
        for name in self.media.NAMES:
            with self.subTest(name=name):
                with self.media.Image.open(self.media.OUT / f'{name}.gif') as image:
                    self.assertEqual(image.size, (800, 450))
                    self.assertEqual(image.n_frames, 36)
                    self.assertEqual(image.info['loop'], 0)
                    for i in range(image.n_frames):
                        image.seek(i)
                        image.load()
