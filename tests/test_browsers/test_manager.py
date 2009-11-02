import logging
import os
import unittest

import w3testrunner.browsers.dummy
from w3testrunner.browsers.browser import BrowserInfo, Browser, BrowserException
from w3testrunner.browsers.dummy import DummyBrowser
from w3testrunner.browsers.manager import browsers_manager
import w3testrunner.browsers.firefox
import w3testrunner.browsers.opera
import w3testrunner.browsers.safari
import w3testrunner.browsers.chrome
import w3testrunner.browsers.ie

log = logging.getLogger(__name__)

class BrowsersManagerTest(unittest.TestCase):
    def test_find_browser_dummy(self):
        browser_info = BrowserInfo(name="dummy")
        browser = browsers_manager.find_browser(browser_info)
        self.assertEqual(type(browser),
                         w3testrunner.browsers.dummy.DummyBrowser)

    def test_find_browser_mock(self):
        class MockBrowserWin(Browser):
            name = "mockbrowserwin"
            platform = "win"
            nopath = True

        class MockBrowserMac(Browser):
            name = "mockbrowsermac"
            platform = "mac"
            executable = "mockexecutable"
            nopath = True

        old_browser_classes = browsers_manager.browser_classes
        browsers_manager.browser_classes = [MockBrowserWin, MockBrowserMac]

        browser_info = BrowserInfo(name="nonexistent-browser")
        self.assertRaises(BrowserException, browsers_manager.find_browser,
                          browser_info)

        browser_info = BrowserInfo(name="mockbrowserwin", platform="win")
        browser = browsers_manager.find_browser(browser_info)
        self.assertEqual(type(browser), MockBrowserWin)

        browser_info = BrowserInfo(name="mockbrowsermac", platform="mac")
        browser = browsers_manager.find_browser(browser_info)
        self.assertEqual(type(browser), MockBrowserMac)

        browser_info = BrowserInfo(name="mockbrowsermac",
                                   path="/nonexistent-path/mockexecutable",
                                   platform="mac")
        self.assertRaises(BrowserException, browsers_manager.find_browser,
                          browser_info)

        browser_info = BrowserInfo(name="mockbrowsermac",
                                   path="/nonexistent-path/mockexecutable",
                                   platform="mac")
        self.assertRaises(BrowserException, browsers_manager.find_browser,
                          browser_info)

        mockexecutable = os.path.join(os.path.dirname(__file__),
                                      "mockexecutable")
        browser_info = BrowserInfo(name="mockbrowsermac", path=mockexecutable,
                                   platform="mac")
        browser = browsers_manager.find_browser(browser_info)
        self.assertEqual(type(browser), MockBrowserMac)

        browser_info = BrowserInfo(path=mockexecutable, platform="mac")
        browser = browsers_manager.find_browser(browser_info)
        self.assertEqual(type(browser), MockBrowserMac)

        browsers_manager.browser_classes = old_browser_classes

    def test_find_browser_system(self):
        browser_checks = [
            # Windows
            {
                "name": "firefox",
                "path": os.path.expandvars(r"%PROGRAMFILES%\Mozilla Firefox\firefox.exe"),
                "class": w3testrunner.browsers.firefox.FirefoxWin,
            },
            {
                "name": "opera",
                "path": os.path.expandvars(r"%PROGRAMFILES%\Opera\opera.exe"),
                "class": w3testrunner.browsers.opera.OperaWin,
            },
            {
                "name": "safari",
                "path": os.path.expandvars(r"%PROGRAMFILES%\Safari\Safari.exe"),
                "class": w3testrunner.browsers.safari.SafariWin,
            },
            {
                "name": "chrome",
                # XXX there's no LOCALAPPDATA on XP.
                "path": os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
                "class": w3testrunner.browsers.chrome.ChromeWin,
            },
            {
                "name": "ie",
                "path": os.path.expandvars(r"%PROGRAMFILES%\Internet Explorer\iexplore.exe"),
                "class": w3testrunner.browsers.ie.IE,
            },
            # Linux
            {
                "name": "firefox",
                "path": "/usr/bin/firefox",
                "class": w3testrunner.browsers.firefox.FirefoxLin,
            },
            {
                "name": "opera",
                "path": "/usr/bin/opera",
                "class": w3testrunner.browsers.opera.OperaLin,
            },
            {
                "name": "chrome",
                "path": "/usr/bin/google-chrome",
                "class": w3testrunner.browsers.chrome.ChromeLin,
            },
            # Mac
            {
                "name": "firefox",
                "path": "/Applications/Firefox.app/Contents/MacOS/firefox",
                "class": w3testrunner.browsers.firefox.FirefoxMac,
            },
            {
                "name": "opera",
                "path": "/Applications/Opera.app/Contents/MacOS/opera",
                "class": w3testrunner.browsers.opera.OperaMac,
            },
            {
                "name": "safari",
                "path": "/Applications/Safari.app/Contents/MacOS/Safari",
                "class": w3testrunner.browsers.safari.SafariMac,
            },
            {
                "name": "chrome",
                "path": "/Applications/Google Chrome.app/Contents/MacOS/"
                        "Google Chrome",
                "class": w3testrunner.browsers.chrome.ChromeMac,
            },
        ]

        for browser_check in browser_checks:
            if not os.path.exists(browser_check["path"]):
                log.debug("Skipping browser %s (path %r not found)",
                          browser_check["name"], browser_check["path"])
                continue

            def assert_browser_equals(browser, browser_check):
                self.assertEqual(type(browser), browser_check["class"])
                self.assertEqual(browser.browser_info.name,
                                 browser_check["name"])
                self.assertEqual(browser.browser_info.path.lower(),
                                 browser_check["path"].lower())

            # Find browser by name
            browser_info = BrowserInfo(name=browser_check["name"])
            browser = browsers_manager.find_browser(browser_info)
            assert_browser_equals(browser, browser_check)

            # Find browser by path
            browser_info = BrowserInfo(path=browser_check["path"])
            browser = browsers_manager.find_browser(browser_info)
            assert_browser_equals(browser, browser_check)

            # Find browser by name and path
            browser_info = BrowserInfo(name=browser_check["name"],
                                       path=browser_check["path"])
            browser = browsers_manager.find_browser(browser_info)
            assert_browser_equals(browser, browser_check)


if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG)
    unittest.main()
