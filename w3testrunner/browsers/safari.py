import os
import sys

from w3testrunner.browsers.browser import BrowserWin, BrowserMac

class SafariMixin(object):
    name = "safari"

if sys.platform == "win32":
    from win32com.shell import shellcon
    from win32com.shell import shell

class SafariWin(SafariMixin, BrowserWin):
    executable = "Safari.exe"

    def prepare_launch(self):
        super(SafariWin, self).prepare_launch()

        # delete browser cache
        appdata = shell.SHGetFolderPath(0, shellcon.CSIDL_LOCAL_APPDATA, 0, 0)
        def delete_if_exists(path):
            if not os.path.exists(path):
                return
            os.unlink(path)
        delete_if_exists(os.path.join(
            appdata, 'Apple Computer', 'Safari', 'Cache.db'))
        delete_if_exists(os.path.join(
            appdata, 'Apple Computer', 'Safari', 'icon.db'))

class SafariMac(SafariMixin, BrowserMac):
    process_name = "Safari"
    directory = "Safari"
    executable = "Safari"

    def __init__(self, browser_info):
        super(SafariMac, self).__init__(browser_info)
        self.cmd = ["open", "-a", browser_info.path]
