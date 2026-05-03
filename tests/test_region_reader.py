import os
import tempfile
import unittest

from core.region_reader import RegionReader
from utils.path_utils import safe_filename


class TestRegionReader(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.mkdtemp()
        self._test_file = os.path.join(self._tmp, "test_regions.txt")

    def tearDown(self):
        import shutil
        shutil.rmtree(self._tmp)

    def _write(self, content: str):
        with open(self._test_file, "w", encoding="utf-8") as f:
            f.write(content)

    def test_basic(self):
        self._write("温州市\n杭州市\n宁波市\n")
        reader = RegionReader()
        regions = reader.load(self._test_file)
        self.assertEqual(len(regions), 3)
        self.assertEqual(regions[0].clean_name, "温州市")

    def test_skip_empty(self):
        self._write("温州市\n\n杭州市\n  \n宁波市\n")
        reader = RegionReader()
        regions = reader.load(self._test_file)
        self.assertEqual(len(regions), 3)

    def test_dedupe(self):
        self._write("温州市\n杭州市\n温州市\n")
        reader = RegionReader()
        regions = reader.load(self._test_file)
        self.assertEqual(len(regions), 2)

    def test_strip_whitespace(self):
        self._write(" 温州市 \n 杭州市\n")
        reader = RegionReader()
        regions = reader.load(self._test_file)
        self.assertEqual(regions[0].clean_name, "温州市")


class TestSafeFilename(unittest.TestCase):
    def test_illegal_chars(self):
        self.assertEqual(safe_filename("温州/龙港市"), "温州_龙港市")
        self.assertEqual(safe_filename("杭州:萧山区"), "杭州_萧山区")
        self.assertEqual(safe_filename("宁波*北仑区"), "宁波_北仑区")
        self.assertEqual(safe_filename('宁波"江北区'), "宁波_江北区")

    def test_no_change(self):
        self.assertEqual(safe_filename("温州市"), "温州市")


if __name__ == "__main__":
    unittest.main()
