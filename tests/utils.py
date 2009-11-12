"""Test utility functions shared by several tests."""

import logging
import os

from w3testrunner.browsers.manager import browsers_manager
from w3testrunner.browsers.browser import BrowserInfo, BrowserException

log = logging.getLogger(__name__)

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
