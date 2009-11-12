import base64
import logging
import os
import StringIO
import subprocess
import sys
import random
import tempfile
import time

import Image
import ImageChops
import ImageStat

log = logging.getLogger(__name__)

class ImageCompareException(Exception):
    def __init__(self, message, error_image):
        super(ImageCompareException, self).__init__(message)
        self.error_image = error_image

# These values should match the HTML test runner configuration.
FRAME_WIDTH = 800
# Note: Mozilla reftests use a height of 1000 pixels, but that would be too
# large for common screen configurations where the whole frame has to be
# visible.
FRAME_HEIGHT = 500
FRAME_BORDER = 1
FRAME_BORDER_COLOR = (0, 255, 0)

FRAMELOCATOR_WIDTH = FRAME_WIDTH + 2 * FRAME_BORDER
FRAMELOCATOR_HEIGHT = 20
FRAMELOCATOR_COLOR = (0, 0, 255)

PAGE_BACKGROUND_COLOR = (255, 255, 255)

class ImageComparator(object):
    def __init__(self):
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
            raise Exception("Can't grab screenshot (missing package?) "
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
            raise Exception("Screenshot taking not implemented "
                            "on this platform")
        return getattr(self, method)()

    def _compare_images(self, image1, image2):
        imagediff = ImageChops.difference(image1, image2)
        s = sum(ImageStat.Stat(imagediff).sum)
        return (imagediff, s / (255.0 * 3.0))

    def _get_pixel(self, image, point):
        return image.getpixel(point)[:3]

    def _find_pixel(self, image, start_point, start_color, target_color,
                    advance_x, advance_y, max_advance):
        """Advance from a point until a point of a given color is found.

        Starts from start_point and advance pixel by pixel (according to
        advance_x and advance_y) while the color matches start_color until
        a pixel with target_color is found. This pixel position is returned.
        If the target color is not found after max_advance iterations (not
        counting the color check of the start_point), None is returned.
        """
        advance = 0
        x, y = start_point
        while advance < max_advance:
            try:
                color = self._get_pixel(image, (x + advance_x, y + advance_y))
            except IndexError:
                return None
            if color == target_color:
                return (x, y)
            elif color != start_color:
                return None
            x += advance_x
            y += advance_y
            advance += 1
        return None

    def _find_frame_border(self, image):
        framelocators = set()
        for x in range(0, image.size[0] - 1, FRAMELOCATOR_WIDTH):
            for y in range(0, image.size[1] - 1, FRAMELOCATOR_HEIGHT):
                if self._get_pixel(image, (x, y)) == FRAMELOCATOR_COLOR:
                    framelocator_top = self._find_pixel(image, (x, y),
                                                        FRAMELOCATOR_COLOR,
                                                        PAGE_BACKGROUND_COLOR,
                                                        0, -1,
                                                        FRAMELOCATOR_HEIGHT)
                    if not framelocator_top:
                        continue

                    framelocator_lefttop = \
                        self._find_pixel(image, framelocator_top,
                                         FRAMELOCATOR_COLOR,
                                         PAGE_BACKGROUND_COLOR,
                                         -1, 0,
                                         FRAMELOCATOR_WIDTH)
                    if not framelocator_lefttop:
                        continue
                    framelocators.add(framelocator_lefttop)

        def framelocator_to_frame_border(framelocator_lefttop):
            frame_left = framelocator_lefttop[0]
            frame_top = framelocator_lefttop[1] + FRAMELOCATOR_HEIGHT
            frame_border = (frame_left, frame_top,
                            frame_left + FRAME_WIDTH + FRAME_BORDER,
                            frame_top + FRAME_HEIGHT + FRAME_BORDER)
            if not self._is_frame_border_well_positionned(image,
                                                          frame_border):
                return None
            return frame_border

        frame_borders = [framelocator_to_frame_border(fl) for fl in
                         framelocators]
        frame_borders = [fb for fb in frame_borders if fb]

        if not frame_borders:
            raise ImageCompareException("Frame border not found "
                                        "(is the browser window covered or not "
                                        "fully visible?)",
                                        self._to_data_url(image))
        if len(frame_borders) > 1:
            raise ImageCompareException("More than one frame border was found. "
                                        "Make sure to have only one browser "
                                        "open with the testrunner",
                                        self._to_data_url(image))
        return frame_borders[0]

    def _contains_rectangle(self, image, box, color):
        box_width = box[2] - box[0]
        box_height = box[3] - box[1]
        rectangle_image = Image.new("RGB", (box_width, box_height), color)
        cropped_image = image.crop(box)
        (_, pixel_diff) = self._compare_images(cropped_image, rectangle_image)
        return pixel_diff == 0

    def _is_frame_border_well_positionned(self, image, frame_border):
        framelocator_box = (frame_border[0],
                            frame_border[1] - FRAMELOCATOR_HEIGHT,
                            frame_border[2],
                            frame_border[1] - FRAME_BORDER)

        if not self._contains_rectangle(image, framelocator_box,
                                        FRAMELOCATOR_COLOR):
            log.debug("Framelocator doesn't match")
            return False

        left, top, right, bottom = frame_border

        # The frame corners on Firefox 3.5 Mac aren't exactly the same color
        # as the frame border (With a border color of (0, 255, 0) the corners
        # are (1, 255, 1)). To avoid mislocating the frame the corner colors
        # are not checked.
        CORNER_SIZE = FRAME_BORDER

        border_rectangles = [
            # left border
            (left, top + CORNER_SIZE, left + FRAME_BORDER, bottom-1),
            # right border
            (right, top + CORNER_SIZE, right + FRAME_BORDER, bottom-1),
            # top border
            (left+1, top, right - CORNER_SIZE, top + FRAME_BORDER),
            # bottom border
            (left+1, bottom, right - CORNER_SIZE, bottom + FRAME_BORDER),
        ]

        for border_rectangle in border_rectangles:
            if not self._contains_rectangle(image, border_rectangle,
                                            FRAME_BORDER_COLOR):
                return False
        return True

    def _to_data_url(self, image):
        output = StringIO.StringIO()
        image.save(output, "PNG")
        image_data = output.getvalue()
        output.close()
        return "data:image/png;base64," + base64.b64encode(image_data)

    def _grab_image(self):
        image = self._take_screenshot()
        if image.mode != "RGB":
            image = image.convert("RGB")

        if (not self.frame_border or
            not self._is_frame_border_well_positionned(image,
                                                       self.frame_border)):
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

        (self.imagediff, pixel_diff) = self._compare_images(self.image1,
                                                            self.image2)
        return pixel_diff

    def save_images(self):
        images = {}
        imagenames = ["image1", "image2", "imagediff"]
        for imagename in imagenames:
            image = getattr(self, imagename, None)
            if image:
                images[imagename] = self._to_data_url(image)
        return images

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
