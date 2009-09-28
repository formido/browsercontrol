import logging
import os
import unittest

import Image

from w3testrunner import imagecompare
from w3testrunner.imagecompare import ImageComparator, ImageCompareException

log = logging.getLogger(__name__)

class MockScreenShooter(object):
    def __init__(self):
        self.image_file = None
    def __call__(self):
        assert self.image_file
        image_path = os.path.join(os.path.dirname(__file__),
                                  "imagecompare_data", self.image_file)
        assert os.path.exists(image_path)
        return Image.open(image_path)

class TestImageComparator(unittest.TestCase):
    def setUp(self):
        # The screenshots used for tests were taken using a smaller
        # frame size.
        # TODO: recreate the test images with the right sizes and remove these
        # overrides.
        self.previous_frame_width = imagecompare.FRAME_WIDTH
        self.previous_frame_height = imagecompare.FRAME_HEIGHT
        self.previous_framelocator_width = imagecompare.FRAMELOCATOR_WIDTH
        imagecompare.FRAME_WIDTH = 500
        imagecompare.FRAME_HEIGHT = 300
        imagecompare.FRAMELOCATOR_WIDTH = (imagecompare.FRAME_WIDTH +
                                           2 * imagecompare.FRAME_BORDER)

    def tearDown(self):
        imagecompare.FRAME_WIDTH = self.previous_frame_width
        imagecompare.FRAME_HEIGHT = self.previous_frame_height
        imagecompare.FRAMELOCATOR_WIDTH = self.previous_framelocator_width

    def _reset_ic(self, ic):
        ic.reset()
        ic.frame_border = None

    def test_frame_border(self):
        logging.basicConfig(level=logging.DEBUG)
        mock_screen_shooter = MockScreenShooter()
        ic = ImageComparator()
        ic.screenshooter = mock_screen_shooter

        # framelocator_box: (19, 396, 520, 415)
        # frame_border: (19, 416, 520, 717)
        mock_screen_shooter.image_file = "frame_visible.png"
        ic.grab_image1()
        self._reset_ic(ic)

        mock_screen_shooter.image_file = "frame_visible_03.png"
        ic.grab_image1()
        self._reset_ic(ic)

        mock_screen_shooter.image_file = "framelocator_mismatch.png"
        self.assertRaises(ImageCompareException, lambda: ic.grab_image1())
        self._reset_ic(ic)

        mock_screen_shooter.image_file = "frame_bottom_border_mismatch.png"
        self.assertRaises(ImageCompareException, lambda: ic.grab_image1())
        self._reset_ic(ic)

        mock_screen_shooter.image_file = "frame_duplicated.png"
        self.assertRaises(ImageCompareException, lambda: ic.grab_image1())
        self._reset_ic(ic)

        mock_screen_shooter.image_file = "frame_offscreen.png"
        self.assertRaises(ImageCompareException, lambda: ic.grab_image1())
        self._reset_ic(ic)

    def test_comparison(self):
        mock_screen_shooter = MockScreenShooter()
        ic = ImageComparator()
        ic.screenshooter = mock_screen_shooter

        mock_screen_shooter.image_file = "frame_visible.png"
        ic.grab_image1()
        ic.grab_image2()
        pixeldiff = ic.compare_images()
        self.assertEqual(pixeldiff, 0.0)
        self._reset_ic(ic)

        mock_screen_shooter.image_file = "frame_visible.png"
        ic.grab_image1()
        mock_screen_shooter.image_file = "frame_visible_02.png"
        ic.grab_image2()
        pixel_diff = ic.compare_images()
        self.assertAlmostEqual(pixel_diff, 454.0, 0)
        self._reset_ic(ic)
