import os
import sys

from w3testrunner.browsers.browser import BrowserWin

# Windows

if sys.platform == "win32":
    from win32com.shell import shellcon
    from win32com.shell import shell

class ChromeWin(BrowserWin):
    name = "chrome"

    @classmethod
    def discover_path(cls, browser_info):
        appdata = shell.SHGetFolderPath(0, shellcon.CSIDL_LOCAL_APPDATA, 0, 0)
        default_path = os.path.join(appdata, "Google", "Chrome", "Application",
                                    "chrome.exe")
        if os.path.isfile(default_path):
            return default_path
