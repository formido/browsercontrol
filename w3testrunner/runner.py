import optparse
import os
import logging
import signal
import sys
import threading
import time
import traceback

from w3testrunner.webapp import WebApp
from w3testrunner import testsloaders
from w3testrunner.testsloaders import LoaderException

log = logging.getLogger(__name__)

NEEDS_TESTS, RUNNING, FINISHED, STOPPED, ERROR = range(5)

class Runner(object):
    def __init__(self, options):
        self.options = options
        self.running = False
        self.last_loader = None
        self.running_test = None
        self.hang_timer = None
        self.last_hung_testid = None
        self.webapp = WebApp(self)
        self.reset()
        # Batch mode is active if there's a browser to control.
        self.batch = bool(self.options.browser)
        log.debug("Batch mode: %s", self.batch)

        # Guard in an exception handler so that the webapp can shutdown if
        # there's an exception raised in _post_init().
        try:
            self._post_init()
        except:
            traceback.print_exc()

    def _post_init(self):
        load_infos = []
        for loader_class in testsloaders.LOADERS:
            load_info = loader_class.maybe_load_tests(self)
            if load_info:
                load_infos.append((loader_class.type, load_info))
        if len(load_infos) > 1:
            raise Exception("More than one loader wants to load tests.\n"
                            "There may be some conflicting command line "
                            "parameters")
        if len(load_infos) == 1:
            self.load_tests(*load_infos[0])

        threading.Thread(target=self.main_loop).start()
        if not self.batch:
            log.info("The runner is started. You should now point your "
                     "browser to http://localhost:8888/")

        self.running = True
        try:
            while self.running:
                time.sleep(1)
        except KeyboardInterrupt:
            # If not killed other thread will keep it running
            if hasattr(os, "kill"):
                os.kill(os.getpid(), signal.SIGKILL)
            sys.exit()
        log.info("End of main()")

    def main_loop(self):
        log.debug("in main_loop %s", self)

        # TODO:
        # if batch: check that there's a tests loader and results saver. Error otherwise.
        event = threading.Event()

        while True:
            log.debug("Waiting...")
            event.wait()
            log.debug("...Finished waiting")

        # TODO:
        # command line argument: load the tests to run
        # start browser if there's one (or use a dummy one if none to have only one code path)
        # Run all the tests (i.e. wait for the browser to have consumed all the tests)
        # If results_saver is available: save results
        # if loop mode: go to start of loop.

    def _stop_hang_timer(self):
        if not self.hang_timer:
            return
        self.hang_timer.cancel()
        self.hang_timer = None
        self.last_hung_testid = None

    def _hang_timer_callback(self):
        self.hang_timer = None

        # XXX investigate how this sometimes happen.
        if not self.running_test:
            log.error("No running test when hang timer fired. "
                      "How did that happen?")
            return

        log.info("Detected hang while running test %s",
                 self.running_test["id"])
        self.last_hung_testid = self.running_test["id"]

        self.set_result(self.running_test["id"], {
            "status": "timeout",
            "status_message": "Timeout detected from server side",
        }, True)
        self.running_test = None

        # TODO if not batch mode, restart browser.

    # Methods called from RPC:

    def reset(self):
        # TODO: reset other state?
        self._stop_hang_timer()
        self.status = NEEDS_TESTS
        self.status_message = ""
        self.ua_string = None
        self.testid_to_test = {}
        if self.last_loader:
            self.last_loader.cleanup()
            self.last_loader = None

        self.tests = []

    def clear_results(self):
        for test in self.tests:
            if "result" in test:
                del test["result"]

    def get_state(self):
        """Return a JSONifiable object representing the Runner state."""
        state = {
            "status": self.status,
            "status_message": self.status_message,
            "ua_string": self.ua_string,
            "batch": self.batch,
            "timeout": self.options.timeout,
        }
        # TODO: filter props on tests?
        state["tests"] = self.tests
        return state

    def load_tests(self, type, load_info):
        log.info("Loading tests using type: %s load_info: %s", type, load_info)
        self.reset()

        # TODO: dynamically locate the matching loader.
        loader_classes = [lc for lc in testsloaders.LOADERS if lc.type == type]
        if len(loader_classes) == 0:
            raise Exception("Can't find a loader for type %s", type)

        assert len(loader_classes) == 1, "Duplicate loaders?"

        loader = loader_classes[0](self, load_info)
        loader.load()
        self.last_loader = loader
        if not self.tests:
            raise LoaderException("Couldn't load any tests")

        self.testid_to_test = dict([(test["id"], test) for test in self.tests])
        self.status = STOPPED

    def set_status(self, status, message):
        if self.status == ERROR and status == ERROR:
            log.warn("Setting ERROR state twice. The message is ignored")
            return

        if self.status == ERROR:
            log.warn("Can't override ERROR status. reset or load_tests "
                     "should be called")
            return

        self.status = status
        self.status_message = message

        if status == ERROR:
            self._stop_hang_timer()
            # TODO: maybe upload results if in batch mode?

    def _get_test(self, testid):
        if not testid in self.testid_to_test:
            raise Exception("Test with identifier %s not found" % testid)
        return self.testid_to_test[testid]

    def test_started(self, testid):
        log.info("Test %s started", testid)
        test = self._get_test(testid)
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

    def suspend_timer(self, testid, suspended):
        log.debug("suspend_timer testid: %s, suspended: %s", testid, suspended)
        test = self._get_test(testid)
        self._ensure_running_test(testid)

        if suspended:
            self._stop_hang_timer()
        else:
            self.test_started(testid)

    def set_result(self, testid, result, did_start_notify):
        log.info("Saving result for testid: %s", testid)

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
            if "result" in test:
                del test["result"]
            return

        test["result"] = result

def main():
    parser = optparse.OptionParser(
        usage='%prog [OPTIONS]')
    parser.add_option('--browser',
        help='Name or path to the browser to use for running the tests (NOT YET IMPLEMENTED)')
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
    for loader_class in testsloaders.LOADERS:
        loader_class.add_options(parser)

    options, args = parser.parse_args()
    if len(args) != 0:
        parser.print_help()
        sys.exit(2)

    logging.basicConfig(level=(logging.DEBUG if options.debug else logging.INFO))

    runner = Runner(options)

if __name__ == '__main__':
    main()
