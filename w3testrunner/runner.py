import os
import sys
import threading
import signal
import optparse
import os.path
import re
import time
import logging

from w3testrunner.testsextractor import TestsExtractor
from w3testrunner.webapp import WebApp

log = logging.getLogger(__name__)

class Runner(object):
    def __init__(self, options, tests_path):
        self.options = options
        self.tests_path = tests_path
        self.webapp = None
        self.tests = self._get_tests()

    def main(self):
        if not self.tests:
            log.info("No tests to run, aborting...")
            return

        self.webapp = WebApp(self, debug=self.options.debug,
                             tests_path=self.tests_path)

        self.running = True
        time.sleep(1)
        try:
            while self.running:
                time.sleep(1)
        except KeyboardInterrupt:
            # If not killed other thread will keep it running
            if hasattr(os, "kill"):
                os.kill(os.getpid(), signal.SIGKILL)
            sys.exit()

        log.info("End of main() with exit status %i", self.exit_status)
        if self.exit_status:
            log.info("WARNING: NON-ZERO EXIT STATUS (failure detected)")
        return self.exit_status

    def _get_tests(self):
        testsextractor = TestsExtractor(tests_dir=self.tests_path)
        # TODO: support importing subdirectories
        itests = testsextractor.get_imported_tests(self.tests_path)

        props = [
            "id", "full_id", "type", "url", "file",
            # reftests
            "equal", "expected", "failure_type", "url2", "file2"
        ]
        test_objs = []
        for itest in itests:
            test_obj = {}
            test = itest.create_test()
            for p in props:
                test_obj[p] = getattr(test, p, None)
            test_objs.append(test_obj)

        return test_objs

def main():
    parser = optparse.OptionParser(
        usage='%prog [OPTIONS] PATH_TO_THE_TESTS')
    parser.add_option('--reftest-results-path',
        help='Path where to store the reftest image results')
    parser.add_option("--debug",
        action="store_true", default=False,
        help="Debug mode"),

    options, args = parser.parse_args()
    if len(args) != 1:
        parser.print_help()
        sys.exit(2)

    logging.basicConfig(level=(logging.DEBUG if options.debug else logging.INFO))

    tests_path = args[0]
    runner = Runner(options, tests_path)
    runner.main()

if __name__ == '__main__':
    main()
