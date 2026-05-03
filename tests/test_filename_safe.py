import unittest
from utils.validators import sanitize_filename, is_safe_filename, validate_gif_file, validate_video_file


class TestFilenameValidation(unittest.TestCase):
    def test_sanitize(self):
        self.assertEqual(sanitize_filename("温州/龙港市"), "温州_龙港市")
        self.assertEqual(sanitize_filename("杭州:萧山区"), "杭州_萧山区")
        self.assertEqual(sanitize_filename("宁波*北仑区"), "宁波_北仑区")
        self.assertEqual(sanitize_filename("温州|瓯海区"), "温州_瓯海区")
        self.assertEqual(sanitize_filename('温州"瓯海区'), "温州_瓯海区")

    def test_is_safe(self):
        self.assertTrue(is_safe_filename("温州市"))
        self.assertFalse(is_safe_filename("温州/龙港市"))

    def test_validate_gif(self):
        ok, msg = validate_gif_file("")
        self.assertFalse(ok)

    def test_validate_video(self):
        ok, msg = validate_video_file("")
        self.assertFalse(ok)


if __name__ == "__main__":
    unittest.main()
