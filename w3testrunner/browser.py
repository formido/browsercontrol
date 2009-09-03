"""Browser management.

Classes to control a browser instance. Can be started, stopped and check the
running status.
"""

# XXX maybe split this in multiple files.

from __future__ import with_statement
import os
import os.path
import subprocess
import time
import platform
import sys
import logging
import random

try:
    from talos import ffprocess
except:
    sys.path.append(os.path.join(os.path.dirname(__file__), "..", "third_party"))
    from talos import ffprocess

log = logging.getLogger(__name__)

def new_browser_from_ua(url, ua, browsers_base_dir):
    id = (ua.branch.product.pk, ua.branch.name, ua.platform)
    classes = [c for c in globals().itervalues()
                if isinstance(c, type) and issubclass(c, Browser)
                and hasattr(c, "id") and c.id == id]
    if len(classes) != 1:
        if len(classes) == 0:
            msg = "No browser class found"
        else:
            msg = "More than one browser class found (count: %s)" % len(classes)
        raise BrowserException("%s. id: (%s). useragent: %s" % (msg, id, ua))
    browser_class = classes[0]
    log.debug("Found browser class: %s", browser_class)
    return browser_class(url, ua, browsers_base_dir)

class BrowserException(Exception):
    pass

class Browser(object):
    """Base Browser class"""
    CRASH_REPORTER_PROCESSES = ("crashreporter", "talkback", "dwwin")

    cmd = None
    process_name = None
    proc = None
    screen = None

    def __init__(self, url, ua, browsers_base_dir=""):
        self.url = url
        self.ua = ua
        self.browsers_base_dir = browsers_base_dir

    def get_browser_path(self):
        browser_dir = self.ua.path % {"BROWSERS_BASE_DIR": self.browsers_base_dir}
        assert browser_dir, "Path not set for ua %s" % self.ua
        log.debug("browser_dir %s", browser_dir)
        path = os.path.join(browser_dir, self.get_executable_path())
        log.debug("Browser executable: %s" % path)
        assert os.path.isfile(path), "No browser executable can be found at %s" % path
        return path

    def get_executable_path(self):
        """
        Returns the browser executable path, relative to this browser directory.
        """
        raise NotImplementedError()

    def get_browser_env(self):
        """
        Returns the environment that should be used when launching this browser.
        """
        return os.environ

    def launch(self):
        self.terminate()
        assert not self.is_alive(), "Didn't terminate correctly"
        self.reset_state()

        if not self.cmd:
            self.cmd = [self.get_browser_path()]

        url = "%s&skip_cache=%s" % (self.url, random.randint(1, 10**10))
        cmd = self.cmd + [url]
        log.debug("Launching %s ...", cmd)

        self.proc = subprocess.Popen(cmd, env=self.get_browser_env())

        log.debug("Waiting for browser launch...")
        time.sleep(2)

        tries = 25
        for i in range(tries):
            win_count = self._count_windows()
            if win_count == 1:
                log.debug("Found only one window, continuing")
                break
            log.debug("Couldn't find only one window (found %i). Retrying (%i/%i)...",
                      win_count, i, tries)
            time.sleep(3)
        else:
            raise BrowserException("Couldn't find only one window (found %i)" %
                                   win_count)

        self._maximize_and_move_front()

        log.debug("Waiting after maximization...")
        time.sleep(1)

        if not self.is_alive():
            raise BrowserException("Failed to launch browser")

    def _maximize_and_move_front(self):
        raise NotImplementedError()

    def ensure_single_window(self):
        """
        Check that there is only one active window for this browser.
        This is used to detect if the download or other windows were opened.
        It will raise a BrowserException if not only one window is active.
        """
        win_count = self._count_windows()
        if win_count != 1:
            raise BrowserException("Browser has not only one active window "
                                   "(count: %s)" % win_count)

    def _count_windows(self):
        raise NotImplementedError()

    def cleanup_processes(self):
        """
        Cleanup crash reporter process that could have appeared.
        WARNING: on Windows, refreshing the process list is expensive (0.5s).
        Throttle if you need to call it often.
        """
        # Refresh processes on Windows. For some reason, this is not done
        # in talos for TerminateAllProcesses.
        if sys.platform == "win32":
            win32pdh.EnumObjects(None, None, 0, 1)

        ffprocess.TerminateAllProcesses(*self.CRASH_REPORTER_PROCESSES)

    def reset_state(self):
        """
        Override this to reset the browser profile or clean stuff before a new
        launch
        """
        pass

    def is_alive(self):
        alive = ffprocess.ProcessesWithNameExist(self.process_name)
        log.debug("is_alive: %s", alive)
        return alive

    def may_have_crashed(self):
        """
        Returns true is there it is suspected that this browser crashed.
        That may be the case if a crash reporter process is running.
        """
        return ffprocess.ProcessesWithNameExist(*self.CRASH_REPORTER_PROCESSES)

    def terminate(self):
        if not self.process_name:
            raise BrowserException("No process_name defined")
        log.debug("Terminating process: '%s'", self.process_name)
        ffprocess.TerminateAllProcesses(self.process_name)
        # Crash reporter processes could still have some browser files opened
        # (dwwin on Windows for instance). Cleanup them when terminating.
        self.cleanup_processes()

        if self.proc:
            log.debug("Waiting for process to terminate...")
            self.proc.wait()
            log.debug("...done")

class DummyBrowser(Browser):
    """Extension of Browser that does nothing"""
    def launch(self):
        pass
    def is_alive(self):
        return True
    def terminate(self):
        pass

class FirefoxMixin(object):
    def set_cmd(self):
        version = self.id[1]
        self.cmd = [self.get_browser_path(), "-no-remote", "-P",
                    "testrunner_ff%s" % version]

class OperaMixin(object):
    # TODO: factorize cleaning of the session:
    def reset_state(self):
        """
        This modifies the profile setting to prevent the crash dialog from
        appearing. (The -nosession flag only existst for Linux, how sad)
        """

        ## TODO: should clean session to remove previous open tabs.

        #appdata = shell.SHGetFolderPath(0, shellcon.CSIDL_APPDATA, 0, 0)
        #inifile = os.path.join(appdata, "Opera", self.appdata_dir,
        #                       "profile", "opera6.ini")
        #inifile = os.path.expanduser("~/Library/Preferences/Opera Preferences/Opera 9 Preferences")
        #print len(open(inifile).read())
        if not os.path.exists(self.inipath):
            raise BrowserException("Opera inifile does not exist at %s" %
                                   self.inipath)

        log.debug("Opera ini file location: %s", self.inipath)
        content = open(self.inipath).read()
        content = content.replace("Run=1", "Run=0")
        open(self.inipath, "w").write(content)

#####################
# Linux browsers

class BrowserLin(Browser):
    def __init__(self, url, ua, browsers_base_dir=""):
        super(BrowserLin, self).__init__(url, ua, browsers_base_dir)
        if not self.process_name:
            self.process_name = os.path.basename(self.get_executable_path())

    def _call_wnck_delegate(self, cmd):
        thisdir = os.path.abspath(os.path.dirname(__file__))
        delegate_path = os.path.join(thisdir, "wnck_delegate.py")
        return subprocess.Popen([delegate_path, cmd, self.appname],
                                stdout=subprocess.PIPE).communicate()[0]

    def _maximize_and_move_front(self):
        pids = ffprocess.GetPidsByName(self.process_name)
        log.debug("pids %s", pids)

        # This is run in a separate process to avoid dealing with a gtk loop.
        cmd = os.path.join(os.path.dirname(__file__), "maximize_win.py")

        tries = 25
        for i in range(tries):
            try:
                self._call_wnck_delegate("maximize")
                break
            except subprocess.CalledProcessError:
                log.debug("Couldn't find window, retrying (%i/%i)...", i, tries)
                time.sleep(3)
        else:
            raise BrowserException("Couldn't find browser window")

    def _count_windows(self):
        return int(self._call_wnck_delegate("countwindows"))

class WebKitGtkLin(BrowserLin):
    id = ("WebKitGtk", "trunk", "lin")

class FirefoxLin(BrowserLin, FirefoxMixin):
    appname = "Firefox"
    process_name = "firefox-bin"
    def __init__(self, url, ua, browsers_base_dir=""):
        super(FirefoxLin, self).__init__(url, ua, browsers_base_dir)
        self.set_cmd()

    def get_executable_path(self):
        return "firefox"

class Firefox2Lin(FirefoxLin):
    id = ("Firefox", "2", "lin")
class Firefox3Lin(FirefoxLin):
    id = ("Firefox", "3", "lin")
class Firefox31Lin(FirefoxLin):
    id = ("Firefox", "3.1", "lin")
class FirefoxTrunkLin(FirefoxLin):
    id = ("Firefox", "trunk", "lin")

class OperaLin(BrowserLin):
    appname = "Opera"

    def get_executable_path(self):
        return "opera"

class Opera9Lin(OperaLin):
    id = ("Opera", "9", "lin")
    def __init__(self, url, ua, browsers_base_dir=""):
        super(Opera9Lin, self).__init__(url, ua, browsers_base_dir)
        self.cmd = [self.get_browser_path(), "-nosession"]

class IE6Wine(BrowserLin):
    id = ("IE_wine", "6", "win")
    process_name = "IEXPLORE.EXE"

#####################
# Windows browsers

if sys.platform == "win32":
    import win32ui, win32gui, win32con, win32process, win32api, pywintypes
    import win32pdhutil, win32pdh
    from win32com.shell import shellcon
    from win32com.shell import shell

class BrowserWin(Browser):
    def __init__(self, url, ua, browsers_base_dir=""):
        super(BrowserWin, self).__init__(url, ua, browsers_base_dir)
        if not self.cmd:
            self.cmd = [self.get_browser_path()]
        if not self.process_name and self.cmd:
            self.process_name = os.path.splitext(os.path.basename(self.cmd[0]))[0]

    def _get_pids(self, process_name):
        # refresh list of processes
        # XXX: is this required?
        win32pdh.EnumObjects(None, None, 0, 1)
        pids = win32pdhutil.FindPerformanceAttributesByName(process_name,
                                                            counter="ID Process")
        if len(pids) == 0:
            raise BrowserException("Didn't find any pid for process: %s" %
                                   process_name)
        return pids

    def _get_windows_by_pids(self, pids):
        windows = []
        win32gui.EnumWindows(lambda win, windows: windows.append(win), windows)

        return [w for w in windows if win32gui.IsWindowVisible(w) and
                win32process.GetWindowThreadProcessId(w)[1] in pids]

    def _maximize_and_move_front(self):
        pids = self._get_pids(self.process_name)
        log.debug("Found pids %s", pids)

        # XXX there should be only one window at this point, the following code
        # is not necessary any more.
        tries = 25
        for i in range(tries):
            windows = self._get_windows_by_pids(pids)
            if len(windows) == 1:
                w = windows[0]
                break
            # XXX Sometimes more that one window is found during startup.
            # Not sure what happens. Just retry until there is only one.
            #if len(windows) > 1:
            #    raise BrowserException("Found more than one window (count: %s)" %
            #                           len(windows))
            # XXX this can also happen if a test tiggers a popup window on startup.
            # this should be non fatal and trigger the single window failure.
            log.debug("Couldn't find only one window (found %i). Retrying (%i/%i)...",
                      len(windows), i, tries)
            time.sleep(3)
            # Pids could have changed, for instance with a Firefox EM restart.
            pids = self._get_pids(self.process_name)
        else:
            raise BrowserException("Couldn't find browser window for pids %s" %
                                   pids)

        log.debug("Found window handle %i", w)
        win32gui.ShowWindow(w, win32con.SW_MAXIMIZE)
        # If the window running this script has not the focus, the target window
        # can't be set to foreground.
        try:
            win32gui.SetForegroundWindow(w)
        except pywintypes.error, e:
            if not "TESTRUNNER_DISABLE_FOCUS_CHECK" in os.environ:
                raise BrowserException("SetForegroundWindow() failed, be sure "
                                       "the terminal running this script has "
                                       "focus (%s)" % e)

    def _count_windows(self):
        pids = self._get_pids(self.process_name)
        windows = self._get_windows_by_pids(pids)
        return len(windows)

class SafariWin(BrowserWin):
    def get_executable_path(self):
        return "Safari.exe"

    def reset_state(self):
        # delete browser cache
        # from browsershots, shotfactory/shotfactory04/gui/windows/safari.py
        appdata = shell.SHGetFolderPath(0, shellcon.CSIDL_LOCAL_APPDATA, 0, 0)
        def delete_if_exists(path):
            if not os.path.exists(path):
                return
            os.unlink(path)
        delete_if_exists(os.path.join(
            appdata, 'Apple Computer', 'Safari', 'Cache.db'))
        delete_if_exists(os.path.join(
            appdata, 'Apple Computer', 'Safari', 'icon.db'))

class Safari3Win(SafariWin):
    id = ("Safari", "3", "win")

class SafariTrunkWin(SafariWin):
    id = ("Safari", "trunk", "win")
    def get_browser_env(self):
        env = os.environ.copy()
        env["PATH"] = os.environ["PATH"]
        browser_dir = os.path.dirname(self.get_browser_path())
        with open(os.path.join(browser_dir, "additional_paths.txt")) as f:
            additional_paths = f.read().split(";")
        env["PATH"] += os.pathsep + os.pathsep.join(additional_paths)
        log.debug("Safari env: %s", env["PATH"])
        return env


class FirefoxWin(BrowserWin, FirefoxMixin):
    process_name = "firefox"
    def __init__(self, url, ua, browsers_base_dir=""):
        super(FirefoxWin, self).__init__(url, ua, browsers_base_dir)
        self.set_cmd()

    def get_executable_path(self):
        return "firefox.exe"

class Firefox2Win(FirefoxWin):
    id = ("Firefox", "2", "win")
class Firefox3Win(FirefoxWin):
    id = ("Firefox", "3", "win")
class Firefox31Win(FirefoxWin):
    id = ("Firefox", "3.1", "win")
class FirefoxTrunkWin(FirefoxWin):
    id = ("Firefox", "trunk", "win")

class OperaWin(OperaMixin, BrowserWin):
    def __init__(self, url, ua, browsers_base_dir=""):
        super(OperaWin, self).__init__(url, ua, browsers_base_dir)
        appdata = shell.SHGetFolderPath(0, shellcon.CSIDL_APPDATA, 0, 0)
        browser_path = self.get_browser_path()
        appdata_dir = browser_path.split(os.sep)[-2]
        self.inipath = os.path.join(appdata, "Opera", appdata_dir,
                                    "profile", "opera6.ini")
        log.debug("Opera ini file location: %s", self.inipath)

    #def reset_state(self):
    #    """
    #    This modifies the profile setting to prevent the crash dialog from
    #    appearing. (Opera Windows has no -nosession flag as on Linux, how sad)
    #    """
    #    appdata = shell.SHGetFolderPath(0, shellcon.CSIDL_APPDATA, 0, 0)
    #    inifile = os.path.join(appdata, "Opera", self.appdata_dir,
    #                           "profile", "opera6.ini")
    #    log.debug("Opera ini file location: %s", inifile)
    #    content = file(inifile).read()
    #    content = content.replace("Run=1", "Run=0")
    #    open(inifile, "w").write(content)

    def get_executable_path(self):
        return "opera.exe"

class Opera9Win(OperaWin):
    id = ("Opera", "9", "win")

class IE(BrowserWin):
    def get_executable_path(self):
        return "iexplore.exe"

class IE6(IE):
    id = ("IE", "6", "win")
class IE7(IE):
    id = ("IE", "7", "win")
class IE8(IE):
    id = ("IE", "8", "win")

class ChromeTrunkWin(BrowserWin):
    id = ("Chrome", "trunk", "win")

    def get_executable_path(self):
        return "chrome.exe"

#####################
# Mac browsers

class BrowserMac(Browser):
    def __init__(self, *args, **kwargs):
        Browser.__init__(self, *args, **kwargs)

        # The maximize code is inspired by the Browser Shots project.

        import appscript
        self.sysevents = appscript.app('System Events')
        if not self.sysevents.UI_elements_enabled():
            raise BrowserException(
                "Please enable access for assistive devices.\n"
                "in System Preferences -> Universal Access\n"
                "http://www.apple.com/applescript/uiscripting/01.html")

        # Apparently AppleScript can't retrieve the size of a single screen.
        # The following line will return the size of the virtual desktop
        # composed of all the monitors:
        # appscript.app("Finder").desktop.window.bounds()
        # So use PyObjC instead.
        import AppKit
        mainscreen = AppKit.NSScreen.screens()[0]
        frame = mainscreen.visibleFrame()
        self.desktopsize = (frame.size.width, frame.size.height)
        log.debug("Found Desktop size: (%s,%s) "  % self.desktopsize)

    def _maximize_and_move_front(self):
        process = self.sysevents.processes[self.process_name]
        process.frontmost.set(True)

        # XXX there should be only one window at this point, the following code
        # is not necessary any more.
        tries = 3
        for i in range(tries):
            windows = process.windows()
            if len(windows) == 1:
                win = windows[0]
                break
            log.debug("Couldn't find only one window (found %i) retrying (%i/%i)...",
                      len(windows), i, tries)
            time.sleep(2)
        else:
            raise BrowserException("Couldn't find browser window")

        win.position.set((0, 22))
        win.size.set(self.desktopsize)

    def _count_windows(self):
        process = self.sysevents.processes[self.process_name]
        windows = process.windows()
        return len(windows)

class FirefoxMac(BrowserMac, FirefoxMixin):
    process_name = "firefox-bin"
    def __init__(self, url, ua, browsers_base_dir=""):
        super(FirefoxMac, self).__init__(url, ua, browsers_base_dir)
        self.set_cmd()

    def get_executable_path(self):
        return os.path.join("Contents", "MacOS", "firefox")

class Firefox2Mac(FirefoxMac):
    id = ("Firefox", "2", "mac")
class Firefox3Mac(FirefoxMac):
    id = ("Firefox", "3", "mac")
class Firefox31Mac(FirefoxMac):
    id = ("Firefox", "3.1", "mac")
class FirefoxTrunkMac(FirefoxMac):
    id = ("Firefox", "trunk", "mac")

class SafariMac(BrowserMac):
    process_name = "Safari"

    def __init__(self, url, ua, browsers_base_dir=""):
        super(SafariMac, self).__init__(url, ua, browsers_base_dir)
        self.cmd = ["open", "-a", self.get_browser_path()]

    def get_executable_path(self):
        return os.path.join("Contents", "MacOS", "Safari")

class Safari3Mac(SafariMac):
    id = ("Safari", "3", "mac")

class SafariTrunkMac(SafariMac):
    id = ("Safari", "trunk", "mac")

    def get_executable_path(self):
        return os.path.join("Contents", "MacOS", "WebKit")

class OperaMac(OperaMixin, BrowserMac):
    # XXX this path matches the one in Program Files, so this is not generic.
    #appdata_dir = "Opera 9.5"
    process_name = "Opera"
    # XXX true for all versions???
    inipath = os.path.expanduser("~/Library/Preferences/Opera Preferences/Opera 9 Preferences")

    def reset_state(self):
        super(OperaMac, self).reset_state()
        # XXX maybe apply to windows to
        # XXX share path name with self.inipath
        sess_path = os.path.expanduser("~/Library/Preferences/Opera Preferences/Sessions/autosave.win")
        try:
            os.unlink(sess_path)
        except OSError:
            pass # ignore if it does not exist

    def __init__(self, url, ua, browsers_base_dir=""):
        super(OperaMac, self).__init__(url, ua, browsers_base_dir)
        self.cmd = ["open", "-a", self.get_browser_path()]

    def get_executable_path(self):
        return os.path.join("Contents", "MacOS", "Opera")

class Opera9Mac(OperaMac):
    id = ("Opera", "9", "mac")

#####################

def test_browsers():
    global session_id
    import random
    from django.conf import settings
    from browsertests.useragents.models import Useragent

    session_id = str(random.randint(0, 1e10))
    url = "http://localhost:8888/framerunner/framerunner.html?session_id=%s" % session_id

    if sys.platform in ("win32", "cygwin"):
        uas = [
            #("Firefox", "2", "win"),
            ("Firefox", "3", "win"),
            #("Firefox", "3.1", "win"),
            #("Firefox", "trunk", "win"),
            #("Opera", "9", "win"),
            #("IE", "6", "win"),
            #("IE", "7", "win"),
            #("Safari", "3", "win"),
            #("Safari", "trunk", "win"),
        ]
    elif sys.platform == "linux2":
        uas = [
            #("Firefox", "2", "lin"),
            ("Firefox", "3", "lin"),
            #("Firefox", "3.1", "lin"),
            #("Firefox", "trunk", "lin"),
            #("Opera", "9", "lin"),
        ]
    else:
        uas = [
        ]

    browsers_base_dir = getattr(settings, "BROWSERS_BASE_DIR", None)
    for ua in uas:
        ua = Useragent.objects.get_by_pbp(*ua)
        b = new_browser_from_ua(url, ua, browsers_base_dir)
        log.debug("Testing browser %s", b)
        assert not b.is_alive()
        b.launch()
        log.debug("Sleeping a few seconds...")
        time.sleep(6)
        log.debug("done.")
        assert b.is_alive()
        b.ensure_single_window()
        b.terminate()
        assert not b.is_alive()


if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG)
    # Should be launched with:
    # DJANGO_SETTINGS_MODULE=browsertests.bt_settings python -m browsertests.runner.browser
    test_browsers()
