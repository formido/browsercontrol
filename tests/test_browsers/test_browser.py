import BaseHTTPServer
import Queue
import logging
import os
import threading
import unittest
import urllib2

from w3testrunner.browsers.browser import BrowserInfo, Browser, BrowserException
from w3testrunner.browsers.manager import browsers_manager

log = logging.getLogger(__name__)

RUNNER_PORT = 8000
RUNNER_PATH = "/runner_path"
RUNNER_URL = "http://localhost:%s%s" % (RUNNER_PORT, RUNNER_PATH)

class HTTPHandler(BaseHTTPServer.BaseHTTPRequestHandler):
    def do_GET(self):
        """Serve a GET request."""
        self.send_response(200)
        self.end_headers()
        self.wfile.write("Dummy response")
        if self.path.startswith(RUNNER_PATH):
            # XXX should be atomic.
            self.server.request_count += 1

    def log_message(self, format, *args):
        pass


if True:
  class BrowserTest(unittest.TestCase):
    def _do_test_browser(self, browser):
        browser.terminate()
        self.assertFalse(browser.is_alive())
        self.assertEquals(self.httpd.request_count, 0)

        browser.launch()
        self.assertEquals(self.httpd.request_count, 1)
        self.assertTrue(browser.is_alive())

        browser.terminate()
        self.assertFalse(browser.is_alive())
        self.assertEquals(self.httpd.request_count, 1)
        self.httpd.request_count = 0

    def _get_browser_names(self):
        # Testing a system browser will kill the browser process if one is
        # already running.
        # Additionally, testing all system browsers can be slow.
        # That's why they will only be tested if an environment variable is set.
        if not "BT_TEST_SYSTEM_BROWSERS" in os.environ:
            log.info("Only testing dummy browser because the "
                     "BT_TEST_SYSTEM_BROWSERS environment variable is not set")
            return set(["dummy"])

        return set(bc.name for bc in browsers_manager.browser_classes)

    def _run_httpd(self):
        """Run a HTTP server that saves requests to self.requests."""
        self.httpd_running = True
        server_address = ('', RUNNER_PORT)
        self.httpd = BaseHTTPServer.HTTPServer(server_address, HTTPHandler)
        self.httpd.request_count = 0
        self.httpd_ready.set()
        while self.httpd_running:
            self.httpd.handle_request()
        self.shutdown_complete.set()

    def setUp(self):
        self.OLD_RUNNER_URL = Browser.RUNNER_URL
        Browser.RUNNER_URL = RUNNER_URL
        self.httpd_ready = threading.Event()
        threading.Thread(target=self._run_httpd).start()
        self.httpd_ready.wait()

    def tearDown(self):
        self.shutdown_complete = threading.Event()
        self.httpd_running = False

        # Dummy request to shut down the server.
        try:
            urllib2.urlopen(Browser.RUNNER_URL).read()
        except urllib2.URLError, e:
            pass

        self.shutdown_complete.wait()
        Browser.RUNNER_URL = self.OLD_RUNNER_URL

    def test_browsers(self):
        for browser_name in self._get_browser_names():
            log.info("**** Testing browser %s", browser_name)
            browser_info = BrowserInfo(name=browser_name)
            try:
                browser = browsers_manager.find_browser(browser_info)
            except BrowserException, e:
                log.info("Couldn't find browser %r (%s) skipping",
                         browser_name, e)
                continue
            self._do_test_browser(browser)


if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG)
    unittest.main()
