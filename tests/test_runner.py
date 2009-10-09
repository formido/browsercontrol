import threading
import unittest
import time
try:
    import simplejson as json
except ImportError:
    import json # Python >= 2.6

from lovely.jsonrpc import proxy
from lovely.jsonrpc.proxy import RemoteException

import w3testrunner
from w3testrunner.runner import Runner

class TestRunner(unittest.TestCase):
    def reset_and_load(self, client, runner):
        client.reset()
        runner._set_tests([{
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
        }])
        self.assertEqual(runner.status, w3testrunner.runner.STOPPED)

    def testRPC(self):
        class MockOptions(object):
            nouacheck = False
            browser = None
            tests_path = None
            timeout = 0

        runner = Runner(MockOptions(), start_loop=False)
        self.assertEqual(runner.status, w3testrunner.runner.NEEDS_TESTS)
        runner.running = True

        client = proxy.ServerProxy('http://localhost:8888/rpc', json_impl=json)
        state = client.get_state()
        self.assertEqual({
            u'batch': False,
            u'status': w3testrunner.runner.NEEDS_TESTS,
            u'status_message': u'',
            u'tests': [],
            u'timeout': 0,
            u'ua_string': u'lovey.jsonpc.proxy (httplib)'
        }, state)

        # TODO: Test the following RPC methods:
        #
        #def reset(self):
        #def clear_results(self):
        #def get_state(self):
        #def load_tests(self, type, load_info):
        #def set_status(self, status, message):
        #def take_screenshot1(self):
        #def take_screenshot2_and_compare(self, screenshot1_id, save_images):
        #def test_started(self, testid):
        #def suspend_timer(self, testid, suspended):
        #def set_result(self, testid, result, did_start_notify):

        self.reset_and_load(client, runner)
        self.assertRaises(RemoteException, client.set_result,
                          "<unknown_testid>", {}, True)
        self.assertEqual(runner.status, w3testrunner.runner.ERROR)

        self.reset_and_load(client, runner)
        self.assertRaises(RemoteException, client.suspend_timer,
                          "<unknown_testid>", True)
        self.assertEqual(runner.status, w3testrunner.runner.ERROR)

        self.reset_and_load(client, runner)
        self.assertRaises(RemoteException, client.test_started,
                          "<unknown_testid>", True)
        self.assertEqual(runner.status, w3testrunner.runner.ERROR)

        # Test that setting a result with a testid that doesn't match the
        # testid of the test_started() call fails.
        self.reset_and_load(client, runner)
        client.test_started("test_mochi_pass.html")
        self.assertEqual(runner.status, w3testrunner.runner.STOPPED)
        self.assertRaises(RemoteException, client.set_result,
                          "<unknown_testid>", {}, True)
        self.assertEqual(runner.status, w3testrunner.runner.ERROR)

        sample_result = {
            "status": "pass",
            "pass_count": 1,
            "fail_count": 0,
            "log": "Some logs",
        }

        # Test that set_result() sets the result.
        self.reset_and_load(client, runner)
        client.test_started("test_mochi_pass.html")
        self.assertEqual(runner.status, w3testrunner.runner.STOPPED)
        client.set_result("test_mochi_pass.html", sample_result, True)
        actual_result = runner.testid_to_test["test_mochi_pass.html"]["result"]
        self.assertEqual(actual_result, sample_result)

        # Test that calling set_result with did_start_notify=True when
        # test_started() wasn't called fails.
        self.reset_and_load(client, runner)
        self.assertRaises(RemoteException, client.set_result,
                          "test_mochi_pass.html", sample_result, True)

        # Test that starting a test with an existing result fails.
        self.reset_and_load(client, runner)
        client.test_started("test_mochi_pass.html")
        client.set_result("test_mochi_pass.html", sample_result, True)
        self.assertRaises(RemoteException, client.test_started,
                          "test_mochi_pass.html")

        # Test that clearing a result on a test with no result fails.
        self.reset_and_load(client, runner)
        self.assertRaises(RemoteException, client.set_result,
                          "test_mochi_pass.html", None, False)

        # Test that setting a result on a test with an existing result fails.
        self.reset_and_load(client, runner)
        client.set_result("test_mochi_pass.html", sample_result, False)
        self.assertRaises(RemoteException, client.set_result,
                          "test_mochi_pass.html", sample_result, False)

        # Timeout tests.
        self.reset_and_load(client, runner)
        runner.options.timeout = 0.1
        client.test_started("test_mochi_pass.html")
        time.sleep(0.5)
        actual_result = runner.testid_to_test["test_mochi_pass.html"]["result"]
        self.assertEqual(actual_result, {
            "status": "timeout",
            "status_message": "Timeout detected from server side",
        })
        runner.options.timeout = 0

if __name__ == "__main__":
    unittest.main()
