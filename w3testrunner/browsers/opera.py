import logging
import os
import sys

from w3testrunner.browsers.browser import BrowserException, BrowserLin, \
                                          BrowserWin, BrowserMac

log = logging.getLogger(__name__)

class OperaMixin(object):
    name = "opera"

    def prepare_launch(self):
        super(OperaMixin, self).prepare_launch()

        # XXX in opera version < 10, the .ini file was in profile\opera6.ini.
        # This will only work for Opera 10 (and maybe later).
        pref_file = os.path.join(self.profile_path, "operaprefs.ini")
        if not os.path.exists(pref_file):
            raise BrowserException("Opera pref file does not exist at %r.\n"
                                   "You should run Opera once in order to "
                                   "create the profile folder." % pref_file)

        log.debug("Opera pref file location: %s", pref_file)
        content = open(pref_file).read()
        content = content.replace("Run=1", "Run=0")
        content = content.replace("Show Default Browser Dialog=1",
                                  "Show Default Browser Dialog=0")
        open(pref_file, "w").write(content)

        # Delete the saved list of open tabs. Otherwise there will be
        # more than one tab with the testrunner and that's bad.
        for f in (
            # win, lin
            os.path.join(self.profile_path, "sessions", "autosave.win"),
            # mac
            os.path.join(self.profile_path, "Sessions", "autosave.win")
            ):
            log.debug("Maybe removing file %s", f)
            if os.path.exists(f):
                log.debug("Removing session file %s", f)
                os.unlink(f)


if sys.platform == "win32":
    from win32com.shell import shellcon
    from win32com.shell import shell

class OperaWin(OperaMixin, BrowserWin):
    def __init__(self, browser_info):
        super(OperaWin, self).__init__(browser_info)

        appdata = shell.SHGetFolderPath(0, shellcon.CSIDL_APPDATA, 0, 0)
        browser_path = self.browser_info.path
        appdata_dir = browser_path.split(os.sep)[-2]
        self.profile_path = os.path.join(appdata, "Opera", appdata_dir)
        log.debug("Opera profile location: %s", self.profile_path)

class OperaLin(OperaMixin, BrowserLin):
    appname = "Opera"

    def __init__(self, browser_info):
        super(OperaLin, self).__init__(browser_info)

        self.profile_path = os.path.expanduser("~/.opera")

class OperaMac(OperaMixin, BrowserMac):
    process_name = "Opera"
    directory = "Opera"
    executable = "Opera"

    def __init__(self, browser_info):
        super(OperaMac, self).__init__(browser_info)
        self.cmd = ["open", "-a", browser_info.path]

        self.profile_path = os.path.expanduser(
                                "~/Library/Preferences/Opera Preferences")
