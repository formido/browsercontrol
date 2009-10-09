import os
import pkgutil
import sys

import w3testrunner.browsers
from w3testrunner.browsers.browser import Browser, BrowserException

# XXX maybe this belongs to browser.py?

class BrowsersManager(object):
    def __init__(self):
        self.browser_classes = self._discover_browser_classes()

    def _discover_browser_classes(self):
        browsers_package_dir = os.path.dirname(w3testrunner.browsers.__file__)
        modulenames = [modname for importer, modname, ispkg in
                          pkgutil.walk_packages([browsers_package_dir],
                              w3testrunner.browsers.__name__ + ".")]

        classes = []
        for modulename in modulenames:
            if not modulename in sys.modules:
                __import__(modulename)
            module = sys.modules[modulename]
            classes.extend([c for c in module.__dict__.itervalues() if
                            isinstance(c, type) and issubclass(c, Browser)])
        return classes

    def find_browser(self, browser_info):
        if not browser_info.name and not browser_info.path:
            raise BrowserException("BrowserInfo should contain at least name "
                                   "or path (%s)" % browser_info)

        matching_classes = self.browser_classes

        matching_classes = [c for c in matching_classes if not c.platform or
                            c.platform == browser_info.platform]

        if browser_info.name:
            matching_classes = [c for c in matching_classes if
                                c.name == browser_info.name]

        if browser_info.path:
            if not os.path.isfile(browser_info.path):
                raise BrowserException("Browser path %r is not a file. You "
                                       "should specify the full path to the "
                                       "browser executable" % browser_info.path)
            matching_classes = [c for c in matching_classes if
                                c.matches_path(browser_info)]

        if not matching_classes:
            raise BrowserException("Could find browser with info %s" %
                                   browser_info)
        if len(matching_classes) > 1:
            raise BrowserException("More than one browser matched for "
                                   "info %s (classes: %s)" % (browser_info,
                                                              matching_classes))

        browser_class = matching_classes[0]
        browser_info.name = browser_class.name

        if not browser_info.path:
            browser_info.path = browser_class.discover_path(browser_info)
        if not browser_info.path and not browser_class.nopath:
            raise BrowserException("Unable to find path for browser %s (%s)" % (
                                   browser_class.__name__, browser_info))

        return browser_class(browser_info)

browsers_manager = BrowsersManager()
