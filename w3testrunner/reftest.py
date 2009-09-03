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

class ImageComparator(object):
    # Size of the reftest canvas, keep in sync with the html testrunner
    WIDTH = 800
    HEIGHT= 1000
    HEIGHT_SMALL = 500
    RED = (255, 0, 0)
    LIME = (0, 255, 0)

    def __init__(self, results_path=None, small_height=False):
        if not results_path:
            results_path = tempfile.mkdtemp()
            log.info("Reftest result images stored in %s", results_path)
        self.results_path = results_path
        self.img1 = None
        self.img2 = None
        self.crop_box = None
        if small_height:
            self.HEIGHT = self.HEIGHT_SMALL

    def take_screenshot_linux2(self):
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
            img = Image.open(filename)
            os.close(oshandle)
            os.unlink(filename)
            return img
        else:
            assert False, "Unknown screenshot tool"

        try:
            return Image.open(StringIO.StringIO(output))
        except IOError, e:
            raise Exception("Can't grab screenshot (missing package?)"
                            "(exception: %s)" % e)

    def take_screenshot_win32(self):
        import ImageGrab
        return ImageGrab.grab()

    def take_screenshot_darwin(self):
        oshandle, filename = tempfile.mkstemp()
        assert not subprocess.call(['screencapture', filename])
        img = Image.open(filename)
        os.close(oshandle)
        os.unlink(filename)
        return img

    def take_screenshot(self):
        method = "take_screenshot_" + sys.platform
        if not hasattr(self, method):
            raise Exception("Screenshot taking not implemented on this platform")
        return getattr(self, method)()

    def _save_temp_image(self, img):
        tempdir = tempfile.mkdtemp()
        imgpath = os.path.join(tempdir, "img.png")
        img.save(imgpath)
        return imgpath

    def _compute_crop_box(self, img):
        LEFT_SCAN_START_Y = 300
        TOP_SCAN_START_X = 300
        SCAN_LENGTH = 300
        SCAN_SAMECOLOR_LENGTH = 20

        # Locate boundaries:
        def find_border(pixels):
            scan = "".join([(img.getpixel(p)[:3] == self.RED and "R" or " ")
                             for p in pixels])
            return scan.index("R" * SCAN_SAMECOLOR_LENGTH)

        try:
            top = find_border([(TOP_SCAN_START_X, y)
                                for y in range(SCAN_LENGTH)])
            left = find_border([(x, LEFT_SCAN_START_Y)
                                 for x in range(SCAN_LENGTH)])
        except ValueError:
            # Save the image for debugging, and draw green lines to show where the crop was searched.
            import ImageDraw
            draw = ImageDraw.Draw(img)
            draw.line((TOP_SCAN_START_X, 0, TOP_SCAN_START_X, SCAN_LENGTH), fill="lime")
            draw.line((0, LEFT_SCAN_START_Y, SCAN_LENGTH, LEFT_SCAN_START_Y), fill="lime")
            del draw
            imgpath = self._save_temp_image(img)
            raise Exception("Can't find border on the Crop Box document. Image saved to %s." % imgpath)

        log.debug("Crop box position: left: %i top: %i", left, top)

        return (left, top, left + self.WIDTH, top + self.HEIGHT)

    def _compare_images(self, img1, img2):
        imgdiff = ImageChops.difference(img1, img2)
        s = sum(ImageStat.Stat(imgdiff).sum)
        return (imgdiff, s / (255.0 * 3.0))

    def init_crop_box(self):
        assert not self.crop_box
        assert not self.img1
        assert not self.img2

        img = self.take_screenshot()
        log.debug("Screenshot size: %s", img.size)

        self.crop_box = self._compute_crop_box(img)

        # checks size of the crop box to ensure it is all visible
        red_img = Image.new("RGB", (self.WIDTH, self.HEIGHT), self.RED)
        cropped_img = img.crop(self.crop_box)
        (_, pixel_diff) = self._compare_images(cropped_img, red_img)

        log.debug("crop box pixel_diff:%d size:%s", pixel_diff, cropped_img.size)
        if pixel_diff != 0:
            raise Exception("Cropped image is not entirely visible. Image saved to %s." %
                            self._save_temp_image(cropped_img))

        if cropped_img.size != red_img.size:
            raise Exception("Cropped image has incorrect size. Image saved to %s." %
                            self._save_temp_image(cropped_img))

    def _grab_image(self):
        """
        Take a screenshot and return a cropped image to the current crop_box.
        This checks if the crop border is visible. The success second return
        argument is False if the border is not correct and True otherwise.

        Returns (image, success)
        """
        assert self.crop_box
        img = self.take_screenshot()

        # Check that the border around the frame is placed correctly.
        # This can be useful to detect situations where a notification box has
        # moved the frame position, or a popup is obstructing the frame.
        left, top, right, bottom = self.crop_box
        left_border = (left - 1, top, left, bottom)
        top_border = (left, top - 1, right, top)
        right_border = (right, top, right + 1, bottom)
        bottom_border = (left, bottom, right, bottom + 1)

        for border in (left_border, top_border, right_border, bottom_border):
            cropped_border = img.crop(border)
            colors = cropped_border.getcolors()
            if len(colors) != 1 or colors[0][1][:3] != self.LIME:
                #log.info("Border: %s", border)
                #log.info("Colors: %s", colors)
                #log.info("Image data %s", list(cropped_border.getdata()))

                # Save the image for debugging, and draw an orange rectangle where
                # the border should have been.
                import ImageDraw
                draw = ImageDraw.Draw(img)
                cb = self.crop_box
                draw.rectangle((cb[0], cb[1], cb[2] - 1, cb[3] - 1), outline="orange")
                del draw

                # Crop the image with 20% more than the crop box on each side to
                # better see what's happening.
                cb = self.crop_box
                crop_width = cb[2] - cb[0]
                crop_height = cb[3] - cb[1]
                margin_horiz = int(crop_width * 0.2)
                margin_vert = int(crop_height * 0.2)
                enlarged_box = (cb[0] - margin_horiz, cb[1] - margin_vert,
                                cb[2] + margin_horiz, cb[3] + margin_vert)
                img = img.crop(enlarged_box)
                return (img, False)

        return (img.crop(self.crop_box), True)

    def grab_image1(self):
        assert self.crop_box
        assert not self.img1
        assert not self.img2
        (self.img1, success) = self._grab_image()
        return success

    def grab_image2(self):
        assert self.crop_box
        assert not self.img2
        (self.img2, success) = self._grab_image()
        return success

    def compare_images(self):
        assert self.img1
        assert self.img2

        (self.imgdiff, pixeldiff) = self._compare_images(self.img1, self.img2)
        return pixeldiff

    def save_images(self):
        # Use a random value to prevent time collision
        path = "%s/%s" % (time.strftime("%Y-%m-%d"),
                          time.strftime("%H-%M-%S-") +
                          str(random.randint(0, 1e10)))
        save_path = os.path.join(self.results_path, path)
        os.makedirs(save_path)
        log.debug("Saving images to %s", save_path)

        imagenames = ["img1", "img2", "imgdiff"]
        for imagename in imagenames:
            img = getattr(self, imagename, None)
            if img:
                img.save(os.path.join(save_path, imagename + ".png"))

        return path

    def reset(self):
        self.img1 = None
        self.img2 = None
        self.imgdiff = None

if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG)

    def test_timing():
        from timeit import Timer
        t = Timer("ic.take_screenshot()",
                  "from browsertests.runner.reftest import ImageComparator;"
                  "ic = ImageComparator()")
        count = 5
        time = t.timeit(count)
        print "Mean time for screenshots: %s" % (time / count)

    test_timing()
