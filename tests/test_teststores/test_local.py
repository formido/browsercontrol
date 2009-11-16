import os
import sys
import unittest

from w3testrunner.teststores.local import LocalTestStore

try:
    from test_webapp import MockWebApp
except ImportError:
    sys.path.append(os.path.join(os.path.dirname(__file__), os.pardir))
    from test_webapp import MockWebApp
import utils

local_data_dir = os.path.join(os.path.dirname(__file__), "local_data")

class MockRunner(object):
    def __init__(self):
        self.webapp = MockWebApp()


class LocalTestsLoaderTest(utils.WTRTestCase):
    def test_load_sample_tests_0(self):
        tests_dir = os.path.join(local_data_dir, "sample_tests_0")

        runner = MockRunner()
        store_info = {
            "type": "local",
            "path": tests_dir,
        }
        store = LocalTestStore(runner, store_info)
        self.assertEqual(runner.webapp.tests_path, None)
        tests = store.load()
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
        store.cleanup()
        self.assertEqual(runner.webapp.tests_path, None)
