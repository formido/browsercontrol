import os
import sys
try:
    import simplejson as json
except ImportError:
    import json # Python >= 2.6

from w3testrunner.browsers.browser import BrowserLin, BrowserWin, BrowserMac

class ChromeMixin(object):
    name = "chrome"
    needs_temporary_profile_dir = True

    def initialize_profile(self):
        first_run_file = os.path.join(self.profile_dir, "First Run")
        with open(first_run_file, "w") as f:
            f.write("")

        preferences = {
            "browser": {
                "check_default_browser": False
            }
        }

        default_dir = os.path.join(self.profile_dir, "Default")
        os.mkdir(default_dir)
        preferences_file = os.path.join(default_dir, "Preferences")
        with open(preferences_file, "w") as p:
            p.write(json.dumps(preferences, indent=2))

    def prepare_launch(self):
        super(ChromeMixin, self).prepare_launch()
        self.cmd = [
            self.browser_info.path,
            # This makes the maximize code useless, but it shouldn't hurt to
            # maximize the window twice.
            "--start-maximized",
            "--user-data-dir=" + self.profile_dir,
        ]

if sys.platform == "win32":
    from win32com.shell import shellcon
    from win32com.shell import shell

class ChromeWin(ChromeMixin, BrowserWin):
    @classmethod
    def discover_path(cls, browser_info):
        appdata = shell.SHGetFolderPath(0, shellcon.CSIDL_LOCAL_APPDATA, 0, 0)
        default_path = os.path.join(appdata, "Google", "Chrome", "Application",
                                    "chrome.exe")
        if os.path.isfile(default_path):
            return default_path


class ChromeLin(ChromeMixin, BrowserLin):
    executable = "google-chrome"
    appname = "google-chrome"


class ChromeMac(ChromeMixin, BrowserMac):
    # TODO
    pass
