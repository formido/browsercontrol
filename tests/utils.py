"""Test utility functions shared by several tests."""

import logging
import os
import unittest

from w3testrunner.browsers.manager import browsers_manager
from w3testrunner.browsers.browser import BrowserInfo, BrowserException

log = logging.getLogger(__name__)

class WTRTestCase(unittest.TestCase):
    def assertTestsEquals(self, actual_tests, expected_tests):
        # XXX sort by id until deterministic test ordering is implemented in
        # the test loader.
        actual_tests = sorted(actual_tests, key=lambda t: t["id"])
        expected_tests = sorted(expected_tests, key=lambda t: t["id"])

        self.assertEqual(len(actual_tests), len(expected_tests))

        for actual, expected in zip(actual_tests, expected_tests):
            # Remove keys on the actual test that are not in the expected one.
            actual_filtered = dict([(k, v) for (k, v) in actual.iteritems() if
                                    k in expected.keys()])
            self.assertEqual(actual_filtered, expected)

def browser_names_to_test():
    if not "WTR_BROWSER_NAMES_TO_TEST" in os.environ:
        log.info("Only testing dummy browser because the "
                 "WTR_BROWSER_NAMES_TO_TEST environment variable is not set")
        return ["dummy"]

    all_browser_names = set(bc.name for bc in browsers_manager.browser_classes)

    browser_names = os.environ["WTR_BROWSER_NAMES_TO_TEST"]
    if browser_names == "all":
        browser_names = all_browser_names
    else:
        browser_names = set(browser_names.split(","))

        unknown_browser_names = browser_names - all_browser_names
        if unknown_browser_names:
            raise Exception("Browsers: %r are not available. Possible names are: "
                            "%r" % (unknown_browser_names, all_browser_names))
    browser_names |= set(["dummy"])

    def is_browser_available(browser_name):
        try:
            browsers_manager.find_browser(BrowserInfo(name=browser_name))
        except BrowserException, e:
            return False
        return True

    return sorted(bn for bn in browser_names if is_browser_available(bn))
