from __future__ import with_statement
import logging
import os
import random
import subprocess
import sys
import time

try:
    from talos import ffprocess
except ImportError:
    sys.path.append(os.path.join(os.path.dirname(__file__), "..",
                                 "third_party"))
    from talos import ffprocess

log = logging.getLogger(__name__)

class BrowserException(Exception):
    pass

class BrowserInfo(object):
    """Encapsulate information to locate and launch a browser."""

    def __init__(self, name=None, path=None, platform=None):
        self.name = name
        self.path = path
        self.platform = platform
        if not self.platform:
            self.platform = self._guess_platform()

    def _guess_platform(self):
        if sys.platform in ("win32", "cygwin"):
            return "win"
        elif sys.platform == "linux2":
            return "lin"
        else:
            return "mac"

    def __str__(self):
        return "<BrowserInfo: %s>" % self.__dict__

class Browser(object):
    """Base Browser class."""

    CRASH_REPORTER_PROCESSES = ("crashreporter", "talkback", "dwwin")
    RUNNER_URL = "http://localhost:8888/"

    # Name used to identify this browser class.
    name = None
    # Platform supporting this browser. Can be None/"win"/"lin"/"mac".
    platform = None
    # Name of the process (if different from name).
    process_name = None
    # Usual directory name containing the browser executable, or bundle name
    # on Mac.
    directory = None
    # Name of the browser executable (without .exe on Windows, only needed if
    # different from name).
    executable = None
    # True for special kind of browsers that don't need an executable path.
    nopath = False
    # Command to launch the browser. Filled automatially if None.
    cmd = None

    proc = None
    screen = None

    def __init__(self, browser_info):
        self.browser_info = browser_info

        assert self.name
        attrs = self._compute_attributes()
        self.process_name = attrs.process_name
        self.directory = attrs.directory
        self.executable = attrs.executable

    @classmethod
    def _compute_attributes(cls):
        """A few class method need access to some attributes that are computed
        dynamically. This method returns an object with such attributes."""
        class Attrs(object):
            name = cls.name
            process_name = cls.process_name
            directory = cls.directory
            executable = cls.executable
        attrs = Attrs()
        if not attrs.process_name:
            attrs.process_name = attrs.name
        if not attrs.directory:
            attrs.directory = attrs.name
        if not attrs.executable:
            attrs.executable = attrs.name
        return attrs

    @classmethod
    def matches_path(cls, browser_info):
        assert browser_info.path
        assert os.path.isfile(browser_info.path)

        head, tail = os.path.split(browser_info.path)
        return tail == cls._compute_attributes().executable

    @classmethod
    def discover_path(cls, browser_info):
        """
        Return the path to the browser executable (usually the default install
        location) or None if it can't be found.
        """
        return None

    def get_browser_env(self):
        """
        Return the environment that should be used when launching this browser.
        """
        return os.environ

    def launch(self):
        self.terminate()
        assert not self.is_alive(), "Didn't terminate correctly"
        self.reset_state()

        if not self.cmd:
            self.cmd = [self.browser_info.path]

        url = "%s?skip_cache=%s" % (self.RUNNER_URL, random.randint(1, 10**10))
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
            log.debug("Couldn't find only one window (found %i). Retrying "
                      "(%i/%i)...", win_count, i, tries)
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
        launch.
        """
        pass

    def is_alive(self):
        alive = ffprocess.ProcessesWithNameExist(self.process_name)
        log.debug("is_alive: %s", alive)
        return alive

    def may_have_crashed(self):
        """
        Return True is it is suspected that this browser crashed.
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

if sys.platform == "win32":
    import win32ui, win32gui, win32con, win32process, win32api, pywintypes
    import win32pdhutil, win32pdh
    from win32com.shell import shellcon
    from win32com.shell import shell

class BrowserWin(Browser):
    platform = "win"

    def __init__(self, browser_info):
        super(BrowserWin, self).__init__(browser_info)

        if not self.executable.endswith(".exe"):
            self.executable += ".exe"

        if not self.cmd:
            self.cmd = [self.browser_info.path]

    @classmethod
    def discover_path(cls, browser_info):
        attrs = cls._compute_attributes()

        executable = attrs.executable
        if not executable.endswith(".exe"):
            executable += ".exe"

        default_path = os.path.join(os.environ["ProgramFiles"], attrs.directory,
                                    executable)
        print "Default path", default_path
        if not os.path.isfile(default_path):
            return None
        return default_path

    def _get_pids(self, process_name):
        # refresh list of processes
        # XXX: is this required?
        win32pdh.EnumObjects(None, None, 0, 1)
        pids = win32pdhutil.FindPerformanceAttributesByName(
                   process_name, counter="ID Process")
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
            #    raise BrowserException("Found more than one window "
            #                           "(count: %s)" % len(windows))
            # XXX this can also happen if a test tiggers a popup window on
            # startup. this should be non fatal and trigger the single window
            # failure.
            log.debug("Couldn't find only one window (found %i). "
                      "Retrying (%i/%i)...", len(windows), i, tries)
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

class BrowserLin(Browser):
    platform = "lin"

    def __init__(self, browser_info):
        super(BrowserLin, self).__init__(browser_info)

    @classmethod
    def discover_path(cls, browser_info):
        executable = cls._compute_attributes().executable

        for dirname in os.environ['PATH'].split(os.pathsep):
            full_path = os.path.join(dirname, executable)
            if os.path.exists(full_path):
                return full_path

        return None

    def _call_wnck_delegate(self, cmd):
        # This is run in a separate process to avoid dealing with a GTK loop.
        thisdir = os.path.abspath(os.path.dirname(__file__))
        delegate_path = os.path.join(thisdir, "tools", "wnck_delegate.py")
        return subprocess.Popen([delegate_path, cmd, self.appname],
                                stdout=subprocess.PIPE).communicate()[0]

    def _maximize_and_move_front(self):
        pids = ffprocess.GetPidsByName(self.process_name)
        log.debug("pids %s", pids)

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

class BrowserMac(Browser):
    platform = "mac"

    def __init__(self, *args, **kwargs):
        Browser.__init__(self, *args, **kwargs)

        # The maximize code is inspired by the Browser Shots project.

        import appscript
        self.sysevents = appscript.app("System Events")
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
            log.debug("Couldn't find only one window (found %i) retrying "
                      "(%i/%i)...", len(windows), i, tries)
            time.sleep(2)
        else:
            raise BrowserException("Couldn't find browser window")

        win.position.set((0, 22))
        win.size.set(self.desktopsize)

    def _count_windows(self):
        process = self.sysevents.processes[self.process_name]
        windows = process.windows()
        return len(windows)
