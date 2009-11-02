import logging
import urllib2

from w3testrunner.browsers.browser import Browser

log = logging.getLogger(__name__)

class DummyBrowser(Browser):
    """Extension of Browser that does nothing."""

    name = "dummy"
    nopath = True

    def __init__(self, browser_info):
        super(DummyBrowser, self).__init__(browser_info)
        self.alive = False

    def launch(self):
        self.alive = True

        # Simulate a browser fetching the runner url.
        try:
            urllib2.urlopen(self.RUNNER_URL).read()
        except urllib2.URLError, e:
            log.debug("Error connecting to runner url: %s", e)

    def is_alive(self):
        return self.alive

    def terminate(self):
        self.alive = False
