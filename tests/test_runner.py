import logging
import os
import threading
import time
import unittest
import urllib2
try:
    import simplejson as json
except ImportError:
    import json # Python >= 2.6

from lovely.jsonrpc import proxy
from lovely.jsonrpc.proxy import RemoteException

import w3testrunner
from w3testrunner import runner
from w3testrunner.runner import Runner
from w3testrunner.browsers.dummy import DummyBrowser
from w3testrunner.browsers.manager import browsers_manager
from w3testrunner.teststores import remote

from test_teststores import test_remote
import utils

log = logging.getLogger(__name__)

runner_data_dir = os.path.join(os.path.dirname(__file__), "runner_data")


class BaseMockOptions(object):
    nouacheck = False
    browser = None
    tests_path = None
    timeout = 0
    username = None
    debug = False

class BaseMockBrowser(DummyBrowser):
    name = "mockbrowser"
    POLL_INTERVAL_SECONDS = 0.5
    MAX_POLL = 10

    def __init__(self, *args, **kwargs):
        super(BaseMockBrowser, self).__init__(*args, **kwargs)

        # The Webapp checks that all requests are made from the same
        # user agent. DummyBrowser makes a request with urllib2 so we
        # use that user agent for the next JSON RPC requests.
        class JSONRPCTransport(proxy.JSONRPCTransport):
            # XXX the useragent should be extracted from urllib2 instead
            # of being hardcoded.
            headers = {'User-Agent': 'Python-urllib/%s' %
                                      urllib2.__version__,
                       'Content-Type': 'application/json',
                       'Accept': 'application/json'}
        self.client = proxy.ServerProxy('http://localhost:8888/rpc',
                                        json_impl=json,
                                        transport_impl=JSONRPCTransport)

    def launch(self):
        super(BaseMockBrowser, self).launch()
        threading.Thread(target=self._poll_webapp_until_ready).start()

    def _poll_webapp_until_ready(self):
        for i in range(self.MAX_POLL):
            time.sleep(self.POLL_INTERVAL_SECONDS)
            # FIXME: sometimes get_state() raises an exception.
            try:
                state = self.client.get_state()
            except IOError, e:
                log.warn("IOError when calling get_state(): %s", e)
                continue
            if state["status"] != runner.INITIALIZING:
                break
        else:
            raise Exception("Webapp not ready after %s tries." % self.MAX_POLL)
        self.on_webapp_ready()

class MockBrowser(BaseMockBrowser):
    def on_webapp_ready(self):
        self.client.set_status(w3testrunner.runner.RUNNING, "Started tests.")

        self.client.test_started("test_mochi_pass.html")
        self.client.set_result("test_mochi_pass.html", {
            u'fail_count': 0,
            u'log': u'TEST-PASS | http://localhost:8888/test_mochi_pass.html | Should pass\n',
            u'pass_count': 1,
            u'status': u'pass'
        }, True)

        self.client.test_started("reftests/reftest:a3e11f282c81ad5492950595618f9ed1")
        # TODO: simulate RPC calls to take screenshots (and mock the screenshooter).
        self.client.set_result("reftests/reftest:a3e11f282c81ad5492950595618f9ed1", {
            u'pixel_diff': 0,
            u'status': u'pass'
        }, True)

        self.client.test_started("test_browser_pass.html")
        self.client.set_result("test_browser_pass.html", {
            u'fail_count': 0,
            u'log': u'0 | pass | true is not true\n',
            u'pass_count': 1,
            u'status': u'pass'
        }, True)

# Uncomment when debugging.
#logging.basicConfig(level=logging.DEBUG)

class TestRunner(utils.WTRTestCase):
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
        client.set_status(w3testrunner.runner.RUNNING, "Started tests.")

    def test_rpc(self):
        runner = Runner(BaseMockOptions(), start_loop=False)
        self.assertEqual(runner.status, w3testrunner.runner.NEEDS_TESTS)

        client = proxy.ServerProxy('http://localhost:8888/rpc', json_impl=json)
        state = client.get_state()
        self.assertEqual(state, {
            u'batch': False,
            u'status': w3testrunner.runner.NEEDS_TESTS,
            u'status_message': u'',
            u'tests': [],
            u'timeout': 0,
            u'ua_string': u'lovey.jsonpc.proxy (httplib)'
        })

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
        self.assertEqual(runner.status, w3testrunner.runner.RUNNING)
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
        self.assertEqual(runner.status, w3testrunner.runner.RUNNING)
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

    def _exercise_browsers(self, mockbrowser_class, callback):
        browser_names = utils.browser_names_to_test()

        browser_names.remove("dummy")
        browser_names.insert(0, "mockbrowser")

        old_browser_classes = browsers_manager.browser_classes[:]
        browsers_manager.browser_classes.insert(0, mockbrowser_class)

        for browser_name in browser_names:
            log.info("**** Testing browser %s", browser_name)
            callback(browser_name)

        browsers_manager.browser_classes = old_browser_classes

    def test_batch_browsers_local_store(self):
        def test_browser(browser_name):
            class MockOptions(BaseMockOptions):
                browser =  browser_name
                tests_path = os.path.join(runner_data_dir, "sample_tests_0")

            runner = Runner(MockOptions(), start_loop=False)
            runner.end_event.wait()

            expected_tests_with_results = [
            {'equal': True,
             'expected': 0,
             'failure_type': '',
             'file': 'reftests/ref_pass.html',
             'file2': 'reftests/ref_pass.html',
             'full_id': 'reftests/reftest:== ref_pass.html ref_pass.html',
             'id': 'reftests/reftest:a3e11f282c81ad5492950595618f9ed1',
             'result': {u'pixel_diff': 0, u'status': u'pass'},
             'type': 'reftest',
             'url': 'http://localhost:8888/reftests/ref_pass.html',
             'url2': 'http://localhost:8888/reftests/ref_pass.html'},
            {'equal': None,
             'expected': None,
             'failure_type': None,
             'file': 'test_mochi_pass.html',
             'file2': None,
             'full_id': 'test_mochi_pass.html',
             'id': 'test_mochi_pass.html',
             'result': {u'fail_count': 0,
                        u'log': u'TEST-PASS | http://localhost:8888/test_mochi_pass.html | Should pass\n',
                        u'pass_count': 1,
                        u'status': u'pass'},
             'type': 'mochitest',
             'url': 'http://localhost:8888/test_mochi_pass.html',
             'url2': None},
            {'equal': None,
             'expected': None,
             'failure_type': None,
             'file': 'test_browser_pass.html',
             'file2': None,
             'full_id': 'test_browser_pass.html',
             'id': 'test_browser_pass.html',
             'result': {u'fail_count': 0,
                        u'log': u'0 | pass | true is not true\n',
                        u'pass_count': 1,
                        u'status': u'pass'},
             'type': 'browsertest',
             'url': 'http://localhost:8888/test_browser_pass.html',
             'url2': None}
            ]

            self.assertTestsEquals(runner.test_store.saved_tests,
                                   expected_tests_with_results)

        self._exercise_browsers(MockBrowser, test_browser)

    def test_batch_browsers_timeouts(self):
        test_runner = self

        class MockBrowserTimingOut(BaseMockBrowser):
            def __init__(self, *args, **kwargs):
                super(MockBrowserTimingOut, self).__init__(*args, **kwargs)
                self._state = 0
                MockBrowserTimingOut.terminate_call_count = 0

            def on_webapp_ready(self):
                if self._state == 0:
                    self.client.set_status(w3testrunner.runner.RUNNING,
                                           "Started tests.")
                    self.client.test_started("test_alerts.html")
                elif self._state == 1:
                    self.client.set_status(w3testrunner.runner.RUNNING,
                                           "Started tests.")
                    self.client.test_started("reftests/reftest:13830c0691ff1351423206a9a156ea45")

                    res = self.client.take_screenshot1()
                    test_runner.assertTrue(res["success"],
                                           "Failed to take screenshot: %s" %
                                           res.get("message"))
                    test_runner.assertTrue("screenshot1_id" in res)
                elif self._state == 2:
                    self.client.set_status(w3testrunner.runner.RUNNING,
                                           "Started tests.")
                    self.client.test_started("test_frame_escape.html")
                else:
                    assert False, "Unknown state (%s), launch() was called too " \
                                  "many times." % self._state

                self._state += 1

            def terminate(self):
                super(MockBrowserTimingOut, self).terminate()
                MockBrowserTimingOut.terminate_call_count += 1

        class MockImageComparator(object):
            def __init__(self):
                self.grabbed_image = False

            def grab_image1(self):
                assert not self.grabbed_image
                self.grabbed_image = True

        def test_browser(browser_name):
            class MockOptions(BaseMockOptions):
                browser =  browser_name
                tests_path = os.path.join(runner_data_dir, "sample_tests_1")
                timeout = 2

            runner = Runner(MockOptions(), start_loop=False)
            runner.browser.runner = runner
            if browser_name == "mockbrowser":
                mock_image_comparator = MockImageComparator()
                runner.webapp.rpc.image_comparator = mock_image_comparator
            runner.end_event.wait()
            if browser_name == "mockbrowser":
                self.assertTrue(mock_image_comparator.grabbed_image)
                self.assertEqual(MockBrowserTimingOut.terminate_call_count, 2)

            expected_tests_with_results = [
               {'equal': None,
                'expected': None,
                'failure_type': None,
                'file': 'test_alerts.html',
                'file2': None,
                'full_id': 'test_alerts.html',
                'id': 'test_alerts.html',
                'result': {'status': 'timeout',
                           'status_message': 'Timeout detected from server side'},
                'type': 'mochitest',
                'url': 'http://localhost:8888/test_alerts.html',
                'url2': None},
               {'equal': True,
                'expected': 0,
                'failure_type': '',
                'file': 'reftests/ref_pass.html',
                'file2': 'reftests/frame_escape.html',
                'full_id': 'reftests/reftest:== ref_pass.html frame_escape.html',
                'id': 'reftests/reftest:13830c0691ff1351423206a9a156ea45',
                'result': {'status': 'timeout',
                           'status_message': 'Timeout detected from server side'},
                'type': 'reftest',
                'url': 'http://localhost:8888/reftests/ref_pass.html',
                'url2': 'http://localhost:8888/reftests/frame_escape.html'},
               {'equal': None,
                'expected': None,
                'failure_type': None,
                'file': 'test_frame_escape.html',
                'file2': None,
                'full_id': 'test_frame_escape.html',
                'id': 'test_frame_escape.html',
                'result': {'status': 'timeout',
                           'status_message': 'Timeout detected from server side'},
                'type': 'mochitest',
                'url': 'http://localhost:8888/test_frame_escape.html',
                'url2': None}]

            self.assertTestsEquals(runner.test_store.saved_tests,
                                   expected_tests_with_results)

        self._exercise_browsers(MockBrowserTimingOut, test_browser)


    @classmethod
    def setup_class(cls):
        cls.store_server = test_remote.StoreServer()
        cls.store_server.ready_event.wait()

    @classmethod
    def teardown_class(cls):
        cls.store_server.stop()

    def test_batch_browsers_remote_store(self):
        def test_browser(browser_name):
            self.store_server.tests_path = runner_data_dir
            self.store_server.tests_data = [{
                "error": None,
                "proxy_mappings": [
                    ("http://localhost:8888/", "/sample_tests_0/"),
                ],
                "tests": [
                    {'equal': True,
                     'expected': 0,
                     'failure_type': '',
                     'file': 'reftests/ref_pass.html',
                     'file2': 'reftests/ref_pass.html',
                     'full_id': 'reftests/reftest:== ref_pass.html ref_pass.html',
                     'id': 'reftests/reftest:a3e11f282c81ad5492950595618f9ed1',
                     'type': 'reftest',
                     'url': 'http://localhost:8888/reftests/ref_pass.html',
                     'url2': 'http://localhost:8888/reftests/ref_pass.html'},
                    {'equal': None,
                     'expected': None,
                     'failure_type': None,
                     'file': 'test_mochi_pass.html',
                     'file2': None,
                     'full_id': 'test_mochi_pass.html',
                     'id': 'test_mochi_pass.html',
                     'type': 'mochitest',
                     'url': 'http://localhost:8888/test_mochi_pass.html',
                     'url2': None},
                    {'equal': None,
                     'expected': None,
                     'failure_type': None,
                     'file': 'test_browser_pass.html',
                     'file2': None,
                     'full_id': 'test_browser_pass.html',
                     'id': 'test_browser_pass.html',
                     'type': 'browsertest',
                     'url': 'http://localhost:8888/test_browser_pass.html',
                     'url2': None}
                ]
            }, {
                "error": None,
                "tests": [],
            }]
            self.store_server.credentials = {
                "alice": "a_token",
            }

            class MockOptions(BaseMockOptions):
                browser =  browser_name

                username = "alice"
                token = "a_token"
                remote_url = test_remote.STORE_SERVER_URL
                filter_types = None
                filter_count = 50

            self.assertEqual(len(self.store_server.load_requests), 0)
            runner = Runner(MockOptions(), start_loop=False)
            runner.end_event.wait()

            self.assertEquals(self.store_server.tests_data, [])
            # Two load requests should be performed. The second will return no
            # tests and the runner will stop.
            expected_load_request = {
                "username": "alice",
                "token": "a_token",
                "protocol_version": remote.RemoteTestStore.PROTOCOL_VERSION,
                # metadata is environment specific.
                "metadata": self.store_server.load_requests[0]["metadata"],
                "types": None,
                "count": 50,
            }
            self.assertEquals(self.store_server.load_requests, [
                expected_load_request, expected_load_request,
            ])
            self.assertEquals(len(self.store_server.save_requests), 1)
            self.assertDictEquals(self.store_server.save_requests[0], {
                "username": "alice",
                "token": "a_token",
                "protocol_version": remote.RemoteTestStore.PROTOCOL_VERSION,
                # metadata is environment specific.
                "metadata": self.store_server.save_requests[0]["metadata"],
                "results": [
                    {
                        u'testid': u'reftests/reftest:a3e11f282c81ad5492950595618f9ed1',
                        u'status': u'pass',
                        u'pixel_diff': 0,
                    }, {
                        u'testid': u'test_mochi_pass.html',
                        u'status': u'pass',
                        u'pass_count': 1,
                        u'fail_count': 0,
                        u'log': u'TEST-PASS | http://localhost:8888/test_mochi_pass.html | Should pass\n',
                    }, {
                        u'status': u'pass',
                        u'pass_count': 1,
                        u'fail_count': 0,
                        u'log': u'0 | pass | true is not true\n', u'testid': u'test_browser_pass.html'
                    }
                ]
            })
            self.store_server.reset()

        self._exercise_browsers(MockBrowser, test_browser)


if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG)
    TestRunner.setup_class()
    unittest.main()
    TestRunner.teardown_class()
