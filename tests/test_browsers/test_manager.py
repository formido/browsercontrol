import logging
import os
import unittest

import w3testrunner.browsers.dummy
from w3testrunner.browsers.browser import BrowserInfo, Browser, BrowserException
from w3testrunner.browsers.dummy import DummyBrowser
from w3testrunner.browsers.manager import browsers_manager

class BrowsersManagerTest(unittest.TestCase):
    def test_find_browser_0(self):
        browser_info = BrowserInfo(name="dummy")
        browser = browsers_manager.find_browser(browser_info)
        self.assertEqual(type(browser),
                         w3testrunner.browsers.dummy.DummyBrowser)

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

if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG)
    unittest.main()
