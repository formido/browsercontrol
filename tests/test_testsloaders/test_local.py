import os
import unittest

from w3testrunner.testsloaders import LocalTestsLoader

local_data_dir = os.path.join(os.path.dirname(__file__), "local_data")

class MockWebApp(object):
    def __init__(self):
        self.tests_path = None

    def enable_localtests(self, tests_path):
        self.tests_path = tests_path

    def disable_localtests(self):
        self.tests_path = None

class MockRunner(object):
    def __init__(self):
        self.webapp = MockWebApp()

class LocalTestsLoaderTest(unittest.TestCase):

    def assertTestsEquals(self, actual_tests, expected_tests):
        # XXX sort by id until deterministic test ordering is implemented in
        # the test loader.
        actual_tests = sorted(actual_tests, key=lambda t: t["id"])
        expected_tests = sorted(expected_tests, key=lambda t: t["id"])

        self.assertEqual(len(actual_tests), len(expected_tests))

        for actual, expected in zip(actual_tests, expected_tests):
            # Remove keys on the actual test that are not in the expected one.
            actual_filtered = dict([(k, v) for (k, v) in actual.iteritems() if
                                    k in expected.keys()])
            self.assertEqual(actual_filtered, expected)

    def testLoadSampleTests0(self):
        tests_dir = os.path.join(local_data_dir, "sample_tests_0")

        runner = MockRunner()
        loader = LocalTestsLoader(runner, tests_dir)
        self.assertEqual(runner.webapp.tests_path, None)
        tests = loader.load()
        self.assertEqual(runner.webapp.tests_path, tests_dir)

        expected_tests = [{
            'equal': True,
            'expected': 0,
            'failure_type': '',
            'file': 'reftests/ref_pass.html',
            'file2': 'reftests/ref_pass.html',
            'full_id': 'reftests/reftest:== ref_pass.html ref_pass.html',
            'id': 'reftests/reftest:a3e11f282c81ad5492950595618f9ed1',
            'type': 'reftest',
            'url': 'http://localhost:8888/reftests/ref_pass.html',
            'url2': 'http://localhost:8888/reftests/ref_pass.html'
        }, {
            'equal': None,
            'expected': None,
            'failure_type': None,
            'file': 'test_mochi_pass.html',
            'file2': None,
            'full_id': 'test_mochi_pass.html',
            'id': 'test_mochi_pass.html',
            'type': 'mochitest',
            'url': 'http://localhost:8888/test_mochi_pass.html',
            'url2': None
        }, {
            'equal': None,
            'expected': None,
            'failure_type': None,
            'file': 'test_browser_pass.html',
            'file2': None,
            'full_id': 'test_browser_pass.html',
            'id': 'test_browser_pass.html',
            'type': 'browsertest',
            'url': 'http://localhost:8888/test_browser_pass.html',
            'url2': None
        }]
        self.assertTestsEquals(tests, expected_tests)
        loader.cleanup()
        self.assertEqual(runner.webapp.tests_path, None)
