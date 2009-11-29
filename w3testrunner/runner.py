from __future__ import with_statement

import optparse
import os
import logging
import platform
import signal
import sys
import threading
import time
import traceback

from w3testrunner.webapp import WebApp
from w3testrunner import teststores
from w3testrunner.browsers.browser import BrowserInfo, BrowserException
from w3testrunner.browsers.manager import browsers_manager

log = logging.getLogger(__name__)

# Keep this in sync with the statuses in
# w3testrunner/resources/testrunner/testrunner.jsrunner.py, order matters.
STATUSES = "INITIALIZING RUNNING FINISHED STOPPED ERROR"
STATUS_TO_NAME = {}
for value, name in enumerate(STATUSES.split()):
    locals()[name] = value
    STATUS_TO_NAME[value] = name

# from http://code.activestate.com/recipes/465057/
def synchronized(lock):
    """ Synchronization decorator. """

    def wrap(f):
        def newFunction(*args, **kw):
            lock.acquire()
            try:
                return f(*args, **kw)
            finally:
                lock.release()
        return newFunction
    return wrap

runner_lock = threading.RLock()

class Runner(object):
    def __init__(self, options, start_loop=True):
        self.options = options
        self.running = False
        self.last_test_store = None
        self.running_test = None
        self.hang_timer = None
        self.last_hung_testid = None
        self.start_loop = start_loop
        self.batch = False
        # TODO: rename to browsers when implementing multiple browser support.
        self.browser = None
        self.active_browser = None
        self.tests_finished_event = threading.Event()
        self.end_event = threading.Event()
        self.reset()
        self.webapp = WebApp(self)

        # Guard in an exception handler so that the webapp can shutdown if
        # there's an exception raised in _post_init().
        try:
            self._post_init()
        except:
            traceback.print_exc()

    def _post_init(self):
        if self.options.browser:
            # Batch mode is active if there's a browser to control.
            self.batch = True

            name = path = None
            if len(os.path.split(self.options.browser)) > 1:
                name = self.options.browser
            else:
                path = self.options.browser

            browser_info = BrowserInfo(name=name, path=path)
            self.browser = browsers_manager.find_browser(browser_info)
            log.info("Using browser: %s", self.browser)

        store_info = self._options_to_store_info(self.options)

        if self.batch:
            if not store_info:
                raise Exception("No tests to load. You should specify options "
                                "for test loading such as --tests-path or "
                                "--username and --token")
            self.test_store = self._create_store(store_info)
            threading.Thread(target=self._main_loop).start()
        else:
            if store_info:
                self.load_tests(store_info)

            log.info("The runner is started. You should now point your "
                     "browser to http://localhost:8888/")
            self.status = STOPPED

        self.running = True
        if not self.start_loop:
            return

        try:
            while self.running:
                time.sleep(1)
        except KeyboardInterrupt:
            # If not killed other thread will keep it running
            if hasattr(os, "kill"):
                os.kill(os.getpid(), signal.SIGKILL)
            sys.exit()
        log.info("End of main()")
        self.end_event.set()

    def _get_ua_string(self):
        if self.batch:
            if not self.active_browser:
                return None
            return self.active_browser.ua_string
        return self._ua_string

    def _set_ua_string(self, value):
        if self.batch:
            if not self.active_browser:
                assert not value
                return
            assert self.active_browser
            self.active_browser.ua_string = value
            return
        self._ua_string = value

    ua_string = property(_get_ua_string, _set_ua_string)

    def _options_to_store_info(self, options):
        store_infos = []
        for store_class in teststores.STORES:
            store_info = store_class.options_to_store_info(self.options)
            if store_info:
                store_infos.append(store_info)
        if len(store_infos) > 1:
            raise Exception("More than one store found for the specified "
                            "command line options.\n"
                            "There may be some conflicting parameters.")
        if len(store_infos) == 1:
            return store_infos[0]
        return None

    def _create_store(self, store_info):
        name = store_info["name"]
        store_classes = [sc for sc in teststores.STORES if sc.name == name]
        if len(store_classes) == 0:
            raise Exception("Can't find a store for name %s" % name)

        assert len(store_classes) == 1, "Duplicate stores?"
        return store_classes[0](self, store_info)

    def _main_loop(self):
        log.debug("in main_loop %s", self)

        try:
            # TODO: remove once multiple browser support is implemented.
            self.active_browser = self.browser
            # The browser is launched before the tests are loaded from the
            # store, so that we can get the useragent string and give it to
            # the store.
            self.browser.terminate()

            while True:
                log.info("Loading tests...")
                self.set_status(INITIALIZING, "Initializing browser.")
                self.active_browser.launch()

                with runner_lock:
                    found_tests = self._do_load_tests()

                self.set_status(RUNNING, "Running tests.", True)
                if not found_tests:
                    # TODO: wait a moment and try again to find tests?
                    log.info("No tests found, terminating")
                    break

                log.debug("Waiting for tests to finish...")
                self.tests_finished_event.wait()
                self.tests_finished_event.clear()
                log.debug("...Finished waiting for end of tests")

                self._do_save_tests()
                if self.status == ERROR:
                    break

                self.reset()
                if self.test_store.load_once:
                    break
        except Exception, e:
            self.set_status(ERROR, "Exception in _main_loop: %s" % e)
            if self.tests:
                self._do_save_tests()

        if self.status == ERROR:
            log.error("\n\nError encountered while running tests, "
                      "terminating.\n Status message: %s\n\n",
                      self.status_message)

        self.browser.cleanup()
        self.running = False
        self.webapp.running = False
        self.end_event.set()

    def _set_tests(self, tests):
        self.tests = tests
        self.testid_to_test = dict([(test["id"], test) for test in self.tests])
        self.finished_tests_count = 0
        self.status = STOPPED

    def _get_metadata(self):
        metadata = {}
        if self.active_browser:
            metadata["browser_info.platform"] = \
                self.active_browser.browser_info.platform
            metadata["browser_info.name"] = \
                self.active_browser.browser_info.name
            metadata["browser_info.path"] = \
                self.active_browser.browser_info.path
            metadata["ua_string"] = self.active_browser.ua_string

            metadata["system"] = platform.system()
            if platform.system() == "Windows":
                metadata["win32_ver"] = platform.win32_ver()
            elif platform.system() == "Darwin":
                metadata["mac_ver"] = platform.mac_ver()
            elif platform.system() == "Linux":
                metadata["linux_distribution"] = platform.linux_distribution()

        return metadata

    def _do_load_tests(self):
        tests = self.test_store.load(self._get_metadata())
        self.last_test_store = self.test_store

        self._set_tests(tests)
        return len(tests) > 0

    @synchronized(runner_lock)
    def _do_save_tests(self):
        self.test_store.save(self._get_metadata())

    def _stop_hang_timer(self):
        if not self.hang_timer:
            return
        self.hang_timer.cancel()
        self.hang_timer = None
        self.last_hung_testid = None

    def _ensure_status(self, *allowed_statuses):
        if self.status in allowed_statuses:
            return
        raise Exception("Unexpected status %r. Allowed statuses are: %r" % (
                        STATUS_TO_NAME[self.status],
                        [STATUS_TO_NAME[s] for s in allowed_statuses]))

    @synchronized(runner_lock)
    def reset(self):
        self._stop_hang_timer()
        self.status = STOPPED
        self.status_message = ""
        self._ua_string = None
        self.testid_to_test = {}
        if self.last_test_store:
            self.last_test_store.cleanup()
            self.last_test_store = None

        self.tests = []

    @synchronized(runner_lock)
    def clear_results(self):
        self._ensure_status(STOPPED, RUNNING, FINISHED)
        for test in self.tests:
            if "result" in test:
                del test["result"]

    @synchronized(runner_lock)
    def get_state(self):
        """Return a JSONifiable object representing the Runner state."""
        state = {
            "status": self.status,
            "status_message": self.status_message,
            "ua_string": self.ua_string,
            "batch": self.batch,
            "timeout": self.options.timeout,
        }
        state["tests"] = self.tests
        return state

    @synchronized(runner_lock)
    def load_tests(self, store_info):
        log.info("Loading tests using store_info: %s", store_info)
        self._ensure_status(STOPPED, FINISHED)
        self.reset()

        self.test_store = self._create_store(store_info)
        if not self.test_store:
            raise Exception("Can't find a store for store_info %s", store_info)

        self._do_load_tests()

    def _do_hang_timer_callback(self):
        self.hang_timer = None
        self._ensure_status(RUNNING)

        # XXX investigate how this sometimes happen.
        if not self.running_test:
            log.error("No running test when hang timer fired. "
                      "How did that happen?")
            return

        log.info("Detected hang while running test %s",
                 self.running_test["id"])
        self.last_hung_testid = self.running_test["id"]

        status = "timeout"
        status_message = "Timeout detected from server side"

        if self.browser and not self.browser.is_alive():
            log.debug("Detected browser crash")
            status = "crash"
            status_message = "Browser crash detected from server side"

        self.set_result(self.running_test["id"], {
            "status": status,
            "status_message": status_message,
        }, True)
        self.running_test = None

        if self.tests_finished_event.is_set():
            return

        if self.active_browser:
            self.set_status(INITIALIZING, "Initializing browser.")
            try:
                self.active_browser.launch()
                self.set_status(RUNNING, "Running after browser restart.", True)
            except BrowserException, e:
                self.set_status(ERROR, "Exception while restarting the "
                                       "browser: %s" % e)

    def _hang_timer_callback(self):
        try:
            self._do_hang_timer_callback()
        except Exception, e:
            self.set_status(ERROR, "Error in _hang_timer_callback: %s" % e)

    @synchronized(runner_lock)
    def set_status(self, status, message, allow_leaving_initializing=False):
        if (not allow_leaving_initializing and
            self.status == INITIALIZING and
            status != INITIALIZING and
            status != ERROR):
            raise Exception("Not allowed to leave INITIALIZING state.")

        if self.status == ERROR and status == ERROR:
            log.warn("Setting ERROR state twice. The message is ignored")
            return

        if self.status == ERROR:
            log.warn("Can't override ERROR status. reset() or load_tests() "
                     "should be called")
            return

        self.status = status
        self.status_message = message

        if status == ERROR:
            self._stop_hang_timer()
            self.tests_finished_event.set()

    def _get_test(self, testid):
        if not testid in self.testid_to_test:
            raise Exception("Test with identifier %s not found" % testid)
        return self.testid_to_test[testid]

    @synchronized(runner_lock)
    def test_started(self, testid):
        log.info("Test %s started", testid)
        self._ensure_status(RUNNING)
        test = self._get_test(testid)
        if "result" in test:
            raise Exception("Starting a test which already has a result "
                            "(test id: %s, existing result: %s)" % (
                            testid, test["result"]))
        self.running_test = test

        if self.options.timeout <= 0:
            return
        # How much to multiply the timeout duration to get the server side
        # waiting time. The intention is to have a timeout larger than
        # the timout used in the client-side harness to allow it to catch
        # hangs first.
        SERVER_HANG_TIMER_RATIO = 1.2
        self._stop_hang_timer()
        self.hang_timer = threading.Timer(self.options.timeout *
                                          SERVER_HANG_TIMER_RATIO,
                                          self._hang_timer_callback)
        self.hang_timer.start()

    def _ensure_running_test(self, testid):
        if not self.running_test:
            raise Exception("test_started wasn't called")
        if testid != self.running_test["id"]:
            raise Exception("test_started was called with a different "
                            "test id (old: %s, new: %s)" %
                            (self.running_test["id"], testid))

    @synchronized(runner_lock)
    def suspend_timer(self, testid, suspended):
        log.debug("suspend_timer testid: %s, suspended: %s", testid, suspended)
        self._ensure_status(RUNNING, STOPPED)
        test = self._get_test(testid)
        self._ensure_running_test(testid)

        if suspended:
            self._stop_hang_timer()
        else:
            self.test_started(testid)

    @synchronized(runner_lock)
    def set_result(self, testid, result, did_start_notify):
        log.info("Saving result for testid: %s", testid)
        self._ensure_status(RUNNING, STOPPED, FINISHED)

        self._stop_hang_timer()
        test = self._get_test(testid)

        if did_start_notify:
            # The last_hung_testid instance variable and this check are
            # used to ignore the rare case when a test finishes after a hang
            # was detected. It could happen if the tests used an alert() which
            # would freeze the client side timeout.
            if (not self.running_test and self.last_hung_testid and
                self.last_hung_testid == testid):
                log.info("Detecting a test which completed after a timout"
                         "was detected on the server side, ignoring the result")
                self.last_hung_testid = None
                return
            self._ensure_running_test(testid)
        self.running_test = None

        if not result:
            if not "result" in test:
                raise Exception("Test with id %s has no result to clear" %
                                testid)
            del test["result"]
            self.finished_tests_count -= 1
        else:
            if "result" in test:
                raise Exception("Overwriting an existing result for test id %s" %
                                testid)
            test["result"] = result
            self.finished_tests_count += 1

        if self.finished_tests_count == len(self.tests):
            log.info("All tests finished")
            self.tests_finished_event.set()

def main():
    parser = optparse.OptionParser(
        usage='%prog [OPTIONS]')
    parser.add_option('--browser',
        help="Name or absolute path to the browser to use for running the "
             "tests")
    parser.add_option("--nouacheck",
        action="store_true", default=False,
        help="Disable the same user agent check. Only use when debugging."),
    parser.add_option("--timeout",
        action="store", type="int", default=10,
        help="Timeout in seconds for detecting hung tests."
             " Set to 0 to disable."),
    parser.add_option("--debug",
        action="store_true", default=False,
        help="Debug mode"),
    for store_class in teststores.STORES:
        store_class.add_options(parser)

    options, args = parser.parse_args()
    if len(args) != 0:
        parser.print_help()
        sys.exit(2)

    logging.basicConfig(level=(logging.DEBUG if options.debug else logging.INFO))

    runner = Runner(options)

if __name__ == '__main__':
    main()
