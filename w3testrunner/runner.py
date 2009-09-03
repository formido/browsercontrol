import os
import sys
import time
import threading
import traceback
import signal
import urllib
import optparse
import os.path
import re
import difflib
import Queue
import time
import logging

from django.conf import settings

from browsertests.utils import cli_wrapper
from browsertests.tests.models import Test, Status
from browsertests.results.models import Result
from browsertests.useragents.models import Useragent

from browsertests.runner.reftest import ImageComparator
import browsertests.runner.browser as browser
import browsertests.runner.webapp as webapp
from browsertests.runner.webapp import WebApp
from browsertests.runner.webapp import ServerMessage

log = logging.getLogger(__name__)

# This should be a bit larger that the value in framerunner/testrunner.js
# XXX Under high IO load, server interaction may take very long times.
# 10 seconds is not enough in that case.
TEST_TIMEOUT = 10

class TestHandler(object):
    def __init__(self, runner, test):
        self.runner = runner
        self.test = test
        self.status = "FAIL"

    def get_type(self):
        raise NotImplemented()

    def get_result(self):
        raise NotImplemented()

    def set_status(self, status):
        self.status = status

    def get_url(self):
        return self.test.url

    def return_result(self, result):
        result.status = self.status
        result.succeeded = self.status == "PASS"
        return result

class MochiTestHandler(TestHandler):
    def get_type(self):
        return "load_mochitest"

    def get_result(self, client_msg):
        result = Result()
        result.type = "mochitestresult"
        result.test = self.test
        if self.status == "PASS":
            if client_msg.fail_count == 0 and client_msg.todo_count == 0:
                self.status = "PASS"
            else:
                self.status = "FAIL"

            # XXX what to do with todo?
            result.pass_count = client_msg.pass_count
            result.fail_count = client_msg.fail_count
            result.todo_count = client_msg.todo_count
            result.log = client_msg.log

            if hasattr(client_msg, "timed_out") and client_msg.timed_out:
                log.debug("Test timed out")
                result.timed_out = True

                # XXX have a status for timeouts??

                # If a tests shows an alert and times out, following tests could
                # go wrong, so force a restart.
                log.debug("Detected timeout, forcing restart")
                self.runner.force_restart = True

        return self.return_result(result)

class LayoutTestHandler(TestHandler):
    # XXX refactor with importer
    REPLACE_EXT_RE = re.compile("\.[^\.]*$")
    STRIP_SPACE_RE = re.compile("\s+")
    STRIP_NON_ASCII = "".join(map(chr, range(128))) + "?" * 128

    def get_type(self):
        return "load_layouttest"

    def _equals_ignoring_space(self, str1, str2):
        str1_nospace = re.sub(self.STRIP_SPACE_RE, "", str1)
        str2_nospace = re.sub(self.STRIP_SPACE_RE, "", str2)
        return str1_nospace == str2_nospace

    def get_result(self, client_msg):
        result = Result()
        result.type = "layouttestresult"
        result.test = self.test
        if self.status == "PASS":
            log.debug("Client message %s", client_msg)
            actual = client_msg.text_dump
            if isinstance(actual, unicode):
                actual = actual.encode("utf8")
            #log.debug("text dump: %s", actual)

            # XXX duplicated with importer
            expected_file = self.REPLACE_EXT_RE.sub("-expected.txt", self.test.file)
            expected_file_fullpath = os.path.join(self.runner.webapp.tests_path,
                                                  expected_file)

            log.debug("expected file %s", expected_file_fullpath)
            expected = open(expected_file_fullpath).read()
            if self._equals_ignoring_space(actual, expected):
                self.status = "PASS"
            else:
                self.status = "FAIL"
                result.log = actual

                # TODO: use diff command if available with -ubwB to ignore whitespace

                actual_file = self.REPLACE_EXT_RE.sub("-actual.txt", self.test.file)
                result.diff = "\n".join(difflib.unified_diff(
                                        # difflib does not like non ascii
                                        [l.translate(self.STRIP_NON_ASCII) for l in expected.splitlines()],
                                        [l.translate(self.STRIP_NON_ASCII) for l in actual.splitlines()],
                                        expected_file, actual_file))

            #log.debug("Test result: %s %s %s %s", self.status, repr(expected), repr(actual), repr(result.diff))
            log.debug("Test status: %s", self.status)

        return self.return_result(result)

class RefTestHandler(TestHandler):
    imagecomparator = None

    REFTEST_URL_CROP_BOX = "red.html"

    def __init__(self, runner, test):
        super(RefTestHandler, self).__init__(runner, test)

        self.crop_box_status = None
        self.url_status = None
        self.url2_status = None
        self.save_images = (not runner.options.dummy) or runner.options.debug

        if not RefTestHandler.imagecomparator:
            # XXX always use small_height for now
            #small_height = runner.options.debug
            small_height = True
            results_path = None

            if hasattr(settings, "REFTEST_RESULTS_PATH"):
                results_path = settings.REFTEST_RESULTS_PATH
            if runner.options.reftest_results_path:
                results_path = runner.options.reftest_results_path
            RefTestHandler.imagecomparator = ImageComparator(
                                                   results_path=results_path,
                                                   small_height=small_height)

    def get_url(self):
        if self.mode == "get_crop_box":
            return self.REFTEST_URL_CROP_BOX
        elif self.mode == "url":
            return self.test.url
        elif self.mode == "url2":
            return self.test.url2
        else:
            assert False, "Incorrect mode"

    def set_mode(self, mode):
        self.mode = mode

    def get_type(self):
        return "load_reftest"

    def set_status(self, status):
        if self.mode == "get_crop_box":
            if status != "PASS":
                raise Exception("Failure while grabbing crop box, this is fatal "
                                "(status was %s)" % status)
            self.crop_box_status = status
        elif self.mode == "url":
            self.url_status = status
        elif self.mode == "url2":
            self.url2_status = status
        else:
            assert False, "Incorrect mode"

    def get_result(self, client_msg):
        ic = RefTestHandler.imagecomparator

        if self.mode == "get_crop_box":
            log.debug("Grabbing crop box")
            if self.crop_box_status != "PASS":
                raise Exception("Failed when grabbing crop box, this is fatal")
            ic.init_crop_box()
            return None

        if self.mode == "url":
            log.debug("Grabbing image1")
            if self.url_status == "PASS":
                if not ic.grab_image1():
                    self.url_status = "FAIL-SCREENSHOT"
                    self.runner.force_restart = True
            log.debug("image1 status: %s", self.url_status)
            return None

        assert self.mode == "url2", "Incorrect mode"

        if self.url2_status == "PASS":
            if not ic.grab_image2():
                self.url2_status = "FAIL-SCREENSHOT"
                self.runner.force_restart = True
        log.debug("image2 status: %s", self.url2_status)

        result = Result()
        result.type = "reftestresult"
        result.test = self.test
        result.pixel_diff = -1

        # If one of the url failed, mark the test with the failure of the first
        self.status = self.url2_status
        if self.url_status != "PASS":
            self.status = self.url_status

        if self.status == "PASS":
            # There should be two images available here.
            result.pixel_diff = ic.compare_images()
            # XXX TODO: handle the expected flag

            equal = result.pixel_diff == 0
            succeeded = self.test.equal == equal
            self.status = ("PASS" if succeeded else "FAIL")
            log.debug("Reftest status: %s, pixel_diff: %s", self.status, result.pixel_diff)

        if self.save_images and self.status != "PASS":
            result.saved_path = ic.save_images()

        ic.reset()
        return self.return_result(result)

class Runner(object):
    def __init__(self, options, ua_args):
        self.options = options

        self.browser = None
        self.webapp = None
        self.results = []
        self.exit_status = 0
        self.running = False

        self.force_restart = False

        self.server_msg_q = Queue.Queue(1)
        self.client_msg_q = Queue.Queue(1)

        # Initialize user agent
        if len(ua_args) == 1:
            self.ua = Useragent.objects.get(pk=int(self.ua_args[0]))
        else:
            product, branch, platform = ua_args
            if not platform in ("win", "lin", "mac"):
                raise Exception("Invalid platform %s should be one of "
                                "win/lin/mac" % platform)
            # XXX use Useragent.objects.get_by_pbp instead
            uas = Useragent.objects.filter(
                                enabled=True,
                                branch__product=product,
                                branch__name=branch,
                                platform=platform)
            if len(uas) != 1:
                raise Exception("Couldn't find only one User Agent (product=%s "
                                "branch=%s platform=%s) (found %s)" % (
                                product, branch, platform, len(uas)))
            self.ua = uas[0]
        log.info("User Agent to use %s", self.ua)

        # Compute tests to run
        if self.options.tests:
            ids = [id.strip() for id in self.options.tests.split(",")]
            self.tests = Test.objects.filter(pk__in=ids)
            # Keeps order from the command line
            tests_dict = dict([(t.id, t) for t in self.tests])
            self.tests = [tests_dict[id] for id in ids]

            # Remove tests that aleady have a result for this ua, if not in dummy mode.
            if not self.options.dummy:
                self.tests = [test for test in self.tests if not self.ua in
                                [r.ua for r in test.result_set.all()]]
        else:
            self.tests = self._get_tests()

    def main(self):
        if not self.options.justserver:
            if not self.tests and not self.options.justbrowser:
                log.info("No tests to run, aborting...")
                return

        if self.options.justbrowser:
            self._init_browser()
            self.browser.launch()
            return

        self.webapp = WebApp(self, debug=self.options.debug,
                             tests_path=self.options.tests_path)

        if not self.options.justserver:
            threading.Thread(target=self.run_tests).start()

        self.running = True

        if self.options.ipython:
            from IPython.Shell import IPShellEmbed
            ipshell = IPShellEmbed([])
            ipshell()
            os.kill(os.getpid(), signal.SIGKILL)
            sys.exit()
        elif not self.options.skipmain:
            time.sleep(1)
            try:
                while self.running:
                    time.sleep(1)
            except KeyboardInterrupt:
                # If not killed other thread will keep it running
                if hasattr(os, "kill"):
                    os.kill(os.getpid(), signal.SIGKILL)
                sys.exit()
            log.debug("Exit of waiting loop")
        log.info("End of main() with exit status %i", self.exit_status)
        if self.exit_status:
            log.info("WARNING: NON-ZERO EXIT STATUS (failure detected)")
        return self.exit_status

    def _get_tests(self):
        disabling_flags = ("moz", "proxy",
                           # XXX rthasfailuretype too restrictive
                           "rthttp", "rtloadonly", "rthasfailuretype", "rtwait", "rtprint",
                           "ltmessages", "ltwait", "layouttests", "layouttesthttp", "ltalert")

        tests = Test.objects.filter(enabled=True, deleted=False).extra(where=[
            """
                NOT (EXISTS (SELECT 1
                    FROM results_result
                    WHERE tests_test.id = results_result.test_id AND tests_test.version = results_result.test_version AND '%s' = results_result.ua_id))
            """ % self.ua.pk,
            """
                NOT (EXISTS (SELECT 1
                    FROM tests_testblacklist
                    WHERE tests_test.id = tests_testblacklist.test_id AND '%s' = tests_testblacklist.ua_id))
            """ % self.ua.pk,
            """
                NOT (EXISTS (SELECT 1
                    FROM tests_test_flags, tests_flag
                    WHERE tests_test.id = tests_test_flags.test_id AND tests_flag.name = tests_test_flags.flag_id AND tests_flag.name IN (%s)))
            """ % ",".join("'%s'" % f for f in disabling_flags)
            ])

        if self.options.maxtests > 0:
            tests = tests[:self.options.maxtests]

        # The query above can be pretty expensive.  With MySQL, running analyze
        # on the tables can help a lot.
        log.info("Fetching tests from db")
        start_time = time.time()
        test = list(tests)
        log.info("Time to fetch tests: %s", time.time() - start_time)

        return tests

    def _init_browser(self):
        session_id = (self.webapp.session_id if self.webapp else "")
        url = "http://localhost:%s/framerunner/framerunner.html?session_id=%s" % \
              (webapp.WEBAPP_PORT, session_id)

        if self.options.debug:
            url += "&debug=1"
        if self.options.manual:
            url += "&manual=1"

        if self.options.manual and not self.options.justbrowser:
            self.browser = browser.DummyBrowser(url, None)
        else:
            browsers_base_dir = getattr(settings, "BROWSERS_BASE_DIR", None)
            self.browser = browser.new_browser_from_ua(url, self.ua,
                                                       browsers_base_dir)

    def update_ua_string(self, ua_string):
        """Called from WebApp to update the current Useragent string"""
        self.ua.name = ua_string
        log.debug("Updating UA string to %s", ua_string)
        self.ua.save()

    def _do_run_tests(self):
        log.debug("Waiting for server startup")
        time.sleep(0.5)
        if not self.webapp.server:
            raise Exception("Error, server is not running")

        self._init_browser()
        self.webapp.ua_string = self.ua.name

        ServerMessage.test_count = len(self.tests)
        ServerMessage.start_time = time.time()

        self.force_restart = True
        was_restarted = True

        reftest_url_failed = True
        reftest_url_status = None

        test_start_time = 0
        GENERATION_CHECK_INTERVAL = 5
        last_generation = Status.objects.get(pk=1).generation
        if last_generation == Status.BUSY:
            log.info("An import is in progress, aborting tests")
            return
        last_generation_check_time = time.time()

        # maximum number of consecutive test failures before aboring.
        MAX_FAILED_TEST_COUNT = 50
        failed_test_count = 0

        def test_generator(tests):
            crop_box_initialized = False
            for (index, test) in enumerate(tests):
                if test.type == "mochitest":
                    yield (index, MochiTestHandler(self, test))
                elif test.type == "layouttest":
                    yield (index, LayoutTestHandler(self, test))
                elif test.type == "reftest":
                    handler = RefTestHandler(self, test)
                    if not crop_box_initialized:
                        crop_box_initialized = True
                        handler.set_mode("get_crop_box")
                        yield (index, handler)
                    handler.set_mode("url")
                    yield (index, handler)
                    handler.set_mode("url2")
                    yield (index, handler)
                else:
                    assert False, "Unknown test type: '%s'" % test.type


        # Used by buildbot
        log.info("Number of tests:%i", len(self.tests))

        for (index, handler) in test_generator(self.tests):

            if time.time() - last_generation_check_time > GENERATION_CHECK_INTERVAL:
                last_generation_check_time = time.time()
                generation = Status.objects.get(pk=1).generation
                #log.debug("Retrieving new generation %i", generation)
                if generation == Status.BUSY:
                    log.info("An import is in progress, aborting tests")
                    return
                if generation != last_generation:
                    log.info("Generation changed (from %i to %i), aborting tests" % (
                             last_generation, generation))
                    return

            if self.force_restart:
                was_restarted = True
                self.force_restart = False
                # Dummy message to give a response to the previously running browser
                # so that the python server can close the socket.
                log.debug("Dummy restarting message...")
                server_msg = ServerMessage()
                server_msg.type = "restarting"
                server_msg.test_index = index
                self.server_msg_q.put(server_msg)
                time.sleep(2)
                if self.server_msg_q.full():
                    self.server_msg_q.get()
                time.sleep(2)
                log.debug("...done")
                if self.client_msg_q.full():
                    log.debug("A client message was queued, clearing it.")
                    self.client_msg_q.get()

                log.info("Starting / Restaring browser")
                self.browser.launch()
                assert self.server_msg_q.empty()
                assert self.client_msg_q.empty()
            else:
                was_restarted = False

            log.info("Processing test %s url %s (%i/%i)", handler.test,
                     handler.get_url(), index + 1, len(self.tests))
            if not test_start_time:
                test_start_time = time.time()

            server_msg = ServerMessage()
            server_msg.type = handler.get_type()
            server_msg.test_index = index
            server_msg.url = handler.get_url()
            server_msg.test_id = handler.test.id

            # XXX handle more gracefully
            assert self.server_msg_q.empty(), "Browser did not consume server message"

            self.server_msg_q.put(server_msg)

            status = "PASS"
            client_msg = None

            try:
                log.debug("Waiting for client message ...")
                timeout = (TEST_TIMEOUT if not self.options.notimeout else sys.maxint)
                # If the browser was restarted, wait longer as it may be still
                # loading.
                if was_restarted and not self.options.debug:
                    timeout *= 3
                    log.debug("Browser was restarted, timeout is %ss", timeout)
                client_msg = self.client_msg_q.get(True, timeout)
                assert self.client_msg_q.empty()
            except Queue.Empty:
                log.debug("... Timed out waiting for client message")
                # Empty the queue in case a client request is attempted just after.
                if self.server_msg_q.full():
                    self.server_msg_q.get()
                if not self.browser.is_alive() or self.browser.may_have_crashed():
                    log.debug("Detected browser crash")
                    status = "CRASH"
                else:
                    log.debug("Detected browser hang")
                    status = "HANG"
                self.force_restart = True
            else:
                log.debug("... Got client message")
                if isinstance(client_msg, Exception):
                    raise client_msg

                if not hasattr(client_msg, "test_id") or not client_msg.test_id:
                    raise Exception("Client message is missing test_id. JSON: '%s'" %
                                    client_msg.json)

                if client_msg.test_id != handler.test.id:
                    raise Exception("Got a client message with unexpected test_id.\n"
                                    "  Expecting: %s\n  Got: %s\n" %
                                    (handler.test.id, client_msg.test_id))

                # XXX should check if there is 0 windows.
                try:
                    self.browser.ensure_single_window()
                except browser.BrowserException, e:
                    log.debug("Browser has not only one window, setting status "
                              "to FAIL-SINGLE-WINDOW. Exception: %s" % e)
                    status = "FAIL-SINGLE-WINDOW"
                    # Restart browser to reset its state.
                    self.force_restart = True

            # This can happen if an unexpected client message is received. In
            # that case, nothing is put in the queue.
            if self.webapp.failed:
                log.error("Detected webapp failure, aborting")
                raise self.webapp.exception
            # XXX should not happen, now that an exception is added to the queue
            # in case of failure.
            if client_msg and client_msg.type == "fail":
                assert False, "How did this situation happen?"
                raise Exception("Client failure (%s) aborting" % client_msg.message)

            handler.set_status(status)
            result = handler.get_result(client_msg)

            if result:
                result.ua = self.ua
                result.session = self.webapp.session_id
                result.duration = time.time() - test_start_time
                result.test_version = handler.test.version
                test_start_time = 0

                log.debug("Result is: %s", result)

                if not self.options.dummy:
                    result.save()
                else:
                    log.info("Dummy mode, not saving test result")

                log.info("Test status: %s duration: %s", result.status,
                         result.duration)
                self.results.append(result)

                # Detect consecutive test failures that could
                # indicate something needs attention.
                if not result.succeeded:
                    failed_test_count += 1
                else:
                    failed_test_count = 0
                if failed_test_count >= MAX_FAILED_TEST_COUNT:
                    raise Exception(("%s consecutive test failures detected. "
                                    "Stopping tests as something bad could have "
                                    "happened.") % MAX_FAILED_TEST_COUNT)

    def run_tests(self):
        try:
            self._do_run_tests()
        except Exception, e:
            log.error("An exception happened: %s", e)
            traceback.print_exc()
            self.exit_status = 2
        finally:
            log.debug("End of tests")

            if not self.server_msg_q.full():
                server_msg = ServerMessage()
                server_msg.type = "finished"
                server_msg.test_index = ServerMessage.test_count
                self.server_msg_q.put(server_msg)

            if self.browser:
                self.browser.terminate()
            self.webapp.stop()

            log.debug("=== Test results ===")
            passed = 0
            for i, r in enumerate(self.results):
                if r.status == "PASS":
                    passed += 1
                if self.options.debug:
                        log.debug("%s Test(%s) %s %s", i, r.test.id, r.test.url,
                                  r.test.url2)
                        log.debug("     %s", r)
                        log.debug("     %s", r.type)
                        log.debug("     %s", r.status)
            # This message is parsed by buildbot, keep it in sync
            total = len(self.tests)
            skipped = total - len(self.results)
            failures = total - passed - skipped
            log.info("Test results: total:%i skip:%i pass:%i "
                     "fail:%i (percent failues %.2f)" % (
                      total, skipped, passed, failures,
                      float(failures) / total * 100.0 if total > 0 else 0))

            log.debug("Finished tests, sleeping a bit...")
            time.sleep(2)

            # Try to stop again in case it did not stop previously for some reasons
            self.webapp.stop()

            log.debug("End of run_tests()")
            self.running = False

def main():
    # XXX option names should be more consistent: separate words by dashes.
    parser = optparse.OptionParser(
        usage='%prog [OPTIONS] { UA_ID | PRODUCT BRANCH PLATFORM }')
    parser.add_option('-j', '--justserver',
        action="store_true", default=False,
        help='Just run the embedded server (for testing)')
    parser.add_option('--justbrowser',
        action="store_true", default=False,
        help='Just launch the browser (for testing)')
    # XXX is this still useful??
    parser.add_option('-m', '--skipmain',
        action="store_true", default=False,
        help='Goes through main, for debugging with python -i')
    parser.add_option('-i', '--ipython',
        action="store_true", default=False,
        help='Run ipython')
    parser.add_option('--notimeout',
        action="store_true", default=False,
        help='Use a very large timeout')
    parser.add_option('--nouacheck',
        action="store_true", default=False,
        help='Does not check User Agent')
    parser.add_option('--manual',
        action="store_true", default=False,
        help='Manual mode: does not launch browser automatically and disables timeouts')
    parser.add_option('--maxtests', type="int",
        help='Maximum number of test to run in this session')
    parser.add_option('--tests',
        help='Comma separated list of test ids to run')
    parser.add_option('--reftest-results-path',
        help='Path where to store the reftest image results')

    parser = cli_wrapper.add_common_parser_options(parser)

    options, args = parser.parse_args()
    if not len(args) in (1, 3):
        parser.print_help()
        sys.exit(2)

    cli_wrapper.process_options(options)

    runner = Runner(options, args)
    runner.main()
    sys.exit(runner.exit_status)

if __name__ == '__main__':
    main()
