import logging
import os
import unittest

from PIL import Image

from w3testrunner.imagecompare import ImageComparator, ImageCompareException

class MockScreenShooter(object):
    def __init__(self):
        self.image_file = None
    def __call__(self):
        assert self.image_file
        image_path = os.path.join(os.path.dirname(__file__),
                                  "testdata", self.image_file)
        assert os.path.exists(image_path)
        return Image.open(image_path)

class TestImageComparator(unittest.TestCase):
    def setUp(self):
        logging.basicConfig(level=logging.DEBUG)

    def test_frame_border(self):
        mock_screen_shooter = MockScreenShooter()
        ic = ImageComparator()
        ic.screenshooter = mock_screen_shooter

        # framelocator_box: (19, 396, 520, 415)
        # frame_border: (19, 416, 520, 717)
        if True:
            mock_screen_shooter.image_file = "frame_visible.png"
            ic.grab_image1()
            ic.reset()

        if True:
            mock_screen_shooter.image_file = "framelocator_mismatch.png"
            self.assertRaises(ImageCompareException, lambda: ic.grab_image1())
            ic.reset()

        if True:
            mock_screen_shooter.image_file = "frame_bottom_border_mismatch.png"
            self.assertRaises(ImageCompareException, lambda: ic.grab_image1())
            ic.reset()

    def test_comparison(self):
        mock_screen_shooter = MockScreenShooter()
        ic = ImageComparator()
        ic.screenshooter = mock_screen_shooter

        if True:
            mock_screen_shooter.image_file = "frame_visible.png"
            ic.grab_image1()
            ic.grab_image2()
            pixeldiff = ic.compare_images()
            self.assertEqual(pixeldiff, 0.0)
            ic.reset()

        mock_screen_shooter.image_file = "frame_visible.png"
        ic.grab_image1()
        mock_screen_shooter.image_file = "frame_visible_02.png"
        ic.grab_image2()
        pixel_diff = ic.compare_images()
        self.assertAlmostEqual(pixel_diff, 454.0, 0)
        ic.reset()

if __name__ == '__main__':
    logging.basicConfig(level=logging.DEBUG)
    unittest.main()
