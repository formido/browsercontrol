import os
import subprocess
import logging
import Image, ImageChops, ImageStat
import StringIO
import time
import random
import sys
import tempfile

log = logging.getLogger(__name__)

class ImageCompareException(Exception):
    def __init__(self, message, error_image_path=None):
        super(ImageCompareException, self).__init__(message)
        self.error_image_path = error_image_path

# These values should match the HTML test runner configuration.
FRAME_HEIGHT = 300
FRAME_WIDTH = 500
FRAME_BORDER = 1
FRAME_BORDER_COLOR = (0, 255, 0)

FRAMELOCATOR_HEIGHT = 20
FRAMELOCATOR_WIDTH = FRAME_WIDTH + 2 * FRAME_BORDER
FRAMELOCATOR_COLOR = (0, 0, 255)

PAGE_BACKGROUND_COLOR = (255, 255, 255)

class ImageComparator(object):
    def __init__(self, results_path=None, small_height=False):
        if not results_path:
            results_path = tempfile.mkdtemp()
            log.info("Result images stored in %s", results_path)
        self.results_path = results_path
        self.image1 = None
        self.image2 = None
        self.frame_border = None
        self.screenshooter = None

    def _take_screenshot_linux2(self):
        log.debug("Taking screenshot")

        # There are several ways to take screenshots on Linux.
        # It turns out that xwd + xwdtopnm is the fastest one.
        #
        # Timing results (1920x1200 resolution), time in second per screen shot:
        # xwd + xwdtopnm: 0.25
        # scrot: 0.47
        # ImageMagick import: 2.93

        XWD, IMAGEMAGICK, SCROT = range(3)
        sc_tool = XWD

        # XXX: the xwd tool gets a garbled screenshot image when running on
        # vmware Xorg X server. Fall back to scrot in that case.
        if os.environ["DISPLAY"] in (":0", ":0.0"):
            sc_tool = SCROT

        if sc_tool == XWD:
            xwd_p = subprocess.Popen(["xwd", "-root"], stdout=subprocess.PIPE)
            output = subprocess.Popen(["xwdtopnm"], stdin=xwd_p.stdout,
                                      stdout=subprocess.PIPE).communicate()[0]
        elif sc_tool == IMAGEMAGICK:
            cmd = "import -window root png:-"
            output = subprocess.Popen(cmd, shell=True,
                                      stdout=subprocess.PIPE).communicate()[0]
        elif sc_tool == SCROT:
            oshandle, filename = tempfile.mkstemp(".png")
            assert not subprocess.call(["scrot", filename])
            image = Image.open(filename)
            os.close(oshandle)
            os.unlink(filename)
            return image
        else:
            assert False, "Unknown screenshot tool"

        try:
            return Image.open(StringIO.StringIO(output))
        except IOError, e:
            raise Exception("Can't grab screenshot (missing package?)"
                            "(exception: %s)" % e)

    def _take_screenshot_win32(self):
        import ImageGrab
        return ImageGrab.grab()

    def _take_screenshot_darwin(self):
        oshandle, filename = tempfile.mkstemp()
        assert not subprocess.call(['screencapture', filename])
        image = Image.open(filename)
        os.close(oshandle)
        os.unlink(filename)
        return image

    def _take_screenshot(self):
        method = "_take_screenshot_" + sys.platform
        if self.screenshooter:
            return self.screenshooter()
        if not hasattr(self, method):
            raise Exception("Screenshot taking not implemented on this platform")
        return getattr(self, method)()

    def _compare_images(self, image1, image2):
        imagediff = ImageChops.difference(image1, image2)
        s = sum(ImageStat.Stat(imagediff).sum)
        return (imagediff, s / (255.0 * 3.0))

    def _get_pixel(self, image, point):
        return image.getpixel(point)[:3]

    def _find_pixel(self, image, start_point, target_color,
                    advance_x, advance_y, max_advance):
        initial_color = self._get_pixel(image, start_point)
        advance = 0
        x, y = start_point
        while advance < max_advance:
            color = self._get_pixel(image, (x + advance_x, y + advance_y))
            if color == target_color:
                return (x, y)
            elif color != initial_color:
                return None
            x += advance_x
            y += advance_y
            advance += 1
        return None

    def _find_frame_border(self, image):
        for x in range(0, image.size[0] - 1, FRAMELOCATOR_WIDTH):
            for y in range(0, image.size[1] - 1, FRAMELOCATOR_HEIGHT):
                if self._get_pixel(image, (x, y)) == FRAMELOCATOR_COLOR:
                    framelocator_top = self._find_pixel(image, (x, y),
                                                        PAGE_BACKGROUND_COLOR,
                                                        0, -1,
                                                        FRAMELOCATOR_HEIGHT)
                    if not framelocator_top:
                        continue

                    framelocator_lefttop = \
                        self._find_pixel(image, framelocator_top,
                                         PAGE_BACKGROUND_COLOR,
                                         -1, 0,
                                         FRAMELOCATOR_WIDTH)
                    if not framelocator_lefttop:
                        continue

                    frame_left = framelocator_lefttop[0]
                    frame_top = framelocator_lefttop[1] + FRAMELOCATOR_HEIGHT
                    frame_border = (frame_left, frame_top,
                                    frame_left + FRAME_WIDTH + FRAME_BORDER,
                                    frame_top + FRAME_HEIGHT + FRAME_BORDER)
                    if self._is_frame_border_well_positionned(image,
                                                              frame_border):
                        return frame_border

        error_image_path = "error.png"
        if not os.path.isdir(self.results_path):
            os.makedirs(self.results_path)
        path = os.path.join(self.results_path, error_image_path)
        log.debug("Saving error images to %s", path)
        image.save(path)

        raise ImageCompareException("Frame border not found "
                                    "(is the browser window covered?)",
                                    error_image_path)

    def _is_frame_border_well_positionned(self, image, frame_border):
        framelocator_box = (frame_border[0], frame_border[1] - FRAMELOCATOR_HEIGHT,
                            frame_border[2], frame_border[1] - FRAME_BORDER)

        locator_image = Image.new("RGB", (FRAMELOCATOR_WIDTH, FRAMELOCATOR_HEIGHT), FRAMELOCATOR_COLOR)
        cropped_image = image.crop(framelocator_box)
        (_, pixel_diff) = self._compare_images(cropped_image, locator_image)
        if pixel_diff != 0:
            log.debug("Framelocator doesn't match")
            return False

        if (# left border
            not self._find_pixel(image, (frame_border[0], frame_border[1]),
                                 PAGE_BACKGROUND_COLOR,
                                 0, 1,
                                 FRAME_HEIGHT + 2 * FRAME_BORDER) or
            # top border
            not self._find_pixel(image, (frame_border[0], frame_border[1]),
                                 PAGE_BACKGROUND_COLOR,
                                 1, 0,
                                 FRAME_WIDTH + 2 * FRAME_BORDER) or
            # right border
            not self._find_pixel(image, (frame_border[2], frame_border[1]),
                                 PAGE_BACKGROUND_COLOR,
                                 0, 1,
                                 FRAME_HEIGHT + 2 * FRAME_BORDER) or
            # bottom border
            not self._find_pixel(image, (frame_border[0], frame_border[3]),
                                 PAGE_BACKGROUND_COLOR,
                                 1, 0,
                                 FRAME_WIDTH + 2 * FRAME_BORDER)):
            log.debug("Frame border mismatch")
            return False

        return True

    def _grab_image(self):
        image = self._take_screenshot()
        if image.mode != "RGB":
            image = image.convert("RGB")

        if (not self.frame_border or
            not self._is_frame_border_well_positionned(image, self.frame_border)):
            log.debug("Computing frame border")
            self.frame_border = self._find_frame_border(image)
            log.debug("Frame border is: %s", self.frame_border)
        else:
            log.debug("Using existing frame border")

        left, top, right, bottom = self.frame_border
        return image.crop((left + FRAME_BORDER,
                           top + FRAME_BORDER,
                           right - FRAME_BORDER,
                           bottom - FRAME_BORDER))

    def grab_image1(self):
        self.image1 = self._grab_image()

    def grab_image2(self):
        self.image2 = self._grab_image()

    def compare_images(self):
        assert self.image1
        assert self.image2

        (self.imagediff, pixel_diff) = self._compare_images(self.image1, self.image2)
        return pixel_diff

    def save_images(self):
        # Use a random value to prevent time collision
        path = "%s/%s" % (time.strftime("%Y-%m-%d"),
                          time.strftime("%H-%M-%S-") +
                          str(random.randint(0, 1e10)))
        save_path = os.path.join(self.results_path, path)
        os.makedirs(save_path)
        log.debug("Saving images to %s", save_path)

        imagenames = ["image1", "image2", "imagediff"]
        for imagename in imagenames:
            image = getattr(self, imagename, None)
            if image:
                image.save(os.path.join(save_path, imagename + ".png"))
        log.debug("Save done")

        return path

    def reset(self):
        self.image1 = None
        self.image2 = None
        self.imagediff = None

if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG)

    def test_timing():
        from timeit import Timer
        t = Timer("ic.take_screenshot()",
                  "from w3testrunner.imagecompare import ImageComparator;"
                  "ic = ImageComparator()")
        count = 5
        time = t.timeit(count)
        print "Mean time for screenshots: %s" % (time / count)

    test_timing()
