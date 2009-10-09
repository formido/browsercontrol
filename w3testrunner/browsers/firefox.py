import os

from w3testrunner.browsers.browser import BrowserLin, BrowserWin, BrowserMac

class FirefoxMixin(object):
    name = "firefox"

    def set_cmd(self):
        # TODO this requires a testrunner profile to exist.
        # It should create a temporary profile directory instead.
        self.cmd = [self.browser_info.path, "-no-remote", "-P", "testrunner"]

class FirefoxWin(FirefoxMixin, BrowserWin):
    process_name = "firefox"

    def __init__(self, browser_info):
        super(FirefoxWin, self).__init__(browser_info)
        self.set_cmd()

class FirefoxLin(FirefoxMixin, BrowserLin):
    executable = "firefox"
    appname = "Firefox"
    process_name = "firefox"

    def __init__(self, browser_info):
        super(FirefoxLin, self).__init__(browser_info)
        self.set_cmd()

        assert browser_info.path.endswith(self.process_name)

        # Official Firefox builds launch the firefox-bin process from the
        # firefox scripts.
        official_executable = os.path.join(os.path.dirname(browser_info.path),
                                           "firefox-bin")
        if os.path.isfile(official_executable):
            self.process_name = "firefox-bin"

class FirefoxMac(FirefoxMixin, BrowserMac):
    process_name = "firefox-bin"

    def __init__(self, url, ua, browsers_base_dir=""):
        super(FirefoxMac, self).__init__(url, ua, browsers_base_dir)
        self.set_cmd()


