import BaseHTTPServer
import errno
import httplib
import logging
import posixpath
import os
import signal
from SimpleHTTPServer import SimpleHTTPRequestHandler
import sys
import threading
import time
import unittest
import urllib
import urllib2
try:
    import simplejson as json
except ImportError:
    import json # Python >= 2.6

from w3testrunner.webapp import PortCheckerMixin
from w3testrunner.teststores.common import StoreException
from w3testrunner.teststores.remote import RemoteTestStore

try:
    from test_webapp import MockWebApp
except ImportError:
    sys.path.append(os.path.join(os.path.dirname(__file__), os.pardir))
    from test_webapp import MockWebApp

STORE_SERVER_PORT = 9999
STORE_SERVER_PATH = "/"
STORE_SERVER_URL = "http://localhost:%s%s" % (STORE_SERVER_PORT,
                                              STORE_SERVER_PATH)

log = logging.getLogger(__name__)

remote_data_dir = os.path.join(os.path.dirname(__file__), "remote_data")


class HTTPHandler(SimpleHTTPRequestHandler):

    SUPPORTED_PROTOCOL_VERSION = 1

    def send_head(self):
        if not self.server.store_server.tests_path:
            self.send_error(404, "File not found")
            return None
        return SimpleHTTPRequestHandler.send_head(self)

    def translate_path(self, path):
        """Translate a /-separated PATH to the local filename syntax.

        Copied from SimpleHTTPServer.py and modified to use a specific path
        from self.server instead of os.getcwd().
        """
        # abandon query parameters
        path = path.split('?',1)[0]
        path = path.split('#',1)[0]
        path = posixpath.normpath(urllib.unquote(path))
        words = path.split('/')
        words = filter(None, words)
        # SimpleHTTPServer.py modification:
        #path = os.getcwd()
        path = self.server.store_server.tests_path
        for word in words:
            drive, word = os.path.splitdrive(word)
            head, word = os.path.split(word)
            if word in (os.curdir, os.pardir): continue
            path = os.path.join(path, word)
        return path

    def _load_tests(self, request):
        if not self.server.store_server.tests_data:
            return {
                "error": "No tests are available."
            }
        self.server.store_server.load_requests.append(request)
        return self.server.store_server.tests_data.pop(0)

    def _save_results(self, request):
        self.server.store_server.save_requests.append(request)
        return {
            "error": None,
        }

    def _handle_request(self):
        if self.headers["content-type"].lower() != "application/json":
            return {
                "error": "Content-type must be application/json"
            }

        length = int(self.headers["content-length"])
        body = self.rfile.read(length)
        try:
            request = json.loads(body)
        except ValueError, e:
            return {
                "error": "Invalid JSON: %s" % str(e)
            }
        if not "username" in request or not "token" in request:
            return {
                "error": "Missing username or token"
            }
        proto_version = request.get("protocol_version", -1)
        if proto_version != self.SUPPORTED_PROTOCOL_VERSION:
            return {
                "error": "Unsupported protocol version %i "
                         "(server supports version %s)" % (
                          proto_version, self.SUPPORTED_PROTOCOL_VERSION)
            }
        username, token = request["username"], request["token"]
        store_server = self.server.store_server
        if not username in store_server.credentials:
            return {
                "error": "Unknown username"
            }
        if store_server.credentials[username] != token:
            return {
                "error": "Invalid token",
            }

        if self.path == "/load/":
            return self._load_tests(request)
        elif self.path == "/save/":
            return self._save_results(request)
        return {
            "error": "Nothing to do"
        }

    def do_GET(self):
        if self.path == "/stop":
            self.send_response(200, "Shutting down.")
            self.server.store_server.httpd_running = False
            return
        return SimpleHTTPRequestHandler.do_GET(self)

    def do_POST(self):
        response = self._handle_request()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()

        self.wfile.write(json.dumps(response))

    def log_message(self, format, *args):
        pass


class StoreServer(PortCheckerMixin):
    """Simple HTTP Server implementing the remote store protocol for testing."""

    def __init__(self):
        self.shutdown_complete_event = threading.Event()
        self.ready_event = threading.Event()
        self.httpd_running = False
        self.reset()
        self.server_port = STORE_SERVER_PORT

        self.check_free_port()
        threading.Thread(target=self._start).start()
        self.check_server_started()

    def _start(self):
        self.httpd_running = True
        server_address = ("", STORE_SERVER_PORT)
        self.httpd = BaseHTTPServer.HTTPServer(server_address, HTTPHandler)
        self.httpd.store_server = self
        self.ready_event.set()
        while self.httpd_running:
            self.httpd.handle_request()
        self.shutdown_complete_event.set()

    def stop(self):
        assert not self.shutdown_complete_event.is_set()
        self.httpd_running = False

        log.debug("Dummy shutdown request")
        # Dummy request to shut down the server.
        try:
            # XXX timeout is 2.6 only.
            urllib2.urlopen(STORE_SERVER_URL, timeout=10).read()
        except urllib2.URLError, e:
            pass
        self.httpd.server_close()
        self.shutdown_complete_event.wait()

    def reset(self):
        self.credentials = {}
        self.tests_data = {
            "error": "No tests data available"
        }
        self.load_requests = []
        self.save_requests = []
        self.tests_path = None

class MockRunner(object):
    def __init__(self):
        self.webapp = MockWebApp()
        self.tests = []


class TestRemoteStore(unittest.TestCase):
    @classmethod
    def setup_class(cls):
        cls.store_server = StoreServer()
        cls.store_server.ready_event.wait()

    @classmethod
    def teardown_class(cls):
        cls.store_server.stop()

    def tearDown(self):
        self.store_server.reset()

    def test_load_save(self):
        self.store_server.tests_path = remote_data_dir
        self.store_server.tests_data = [{
            "error": None,
            "proxy_mappings": [
                ("http://localhost:8888/", "/sample_tests_0/"),
            ],
            "tests": [{
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
            }]
        }]
        self.store_server.credentials = {
            "alice": "a_token",
        }

        store_info = {
            "remote_url": STORE_SERVER_URL,
            "username": "alice",
            "token": "a_token",
        }
        mock_runner = MockRunner()
        remote_store = RemoteTestStore(mock_runner, store_info)
        sample_metadata = {"meta_name": "meta_value"}
        tests = remote_store.load(sample_metadata)
        self.assertEquals(self.store_server.load_requests, [{
            "username": "alice",
            "token": "a_token",
            "protocol_version": RemoteTestStore.PROTOCOL_VERSION,
            "metadata": sample_metadata,
            "types": None,
            "count": None,
        }])
        self.assertEquals(self.store_server.save_requests, [])
        self.assertEquals(self.store_server.tests_data, [],
                          "tests_data wasn't consumed")

        self.assertEquals(tests, [{
            'equal': True,
            'expected': 0,
            'failure_type': '',
            'file': 'reftests/ref_pass.html',
            'file2': 'reftests/ref_pass.html',
            'full_id': 'reftests/reftest:== ref_pass.html ref_pass.html',
            'id': 'reftests/reftest:a3e11f282c81ad5492950595618f9ed1',
            'type': 'reftest',
            'url': 'http://localhost:8888/reftests/ref_pass.html',
            'url2': 'http://localhost:8888/reftests/ref_pass.html',
        }])
        self.assertEquals(mock_runner.webapp.proxy_mappings, [
            [u"http://localhost:8888/", u"/sample_tests_0/"],
        ])
        self.assertEquals(mock_runner.webapp.default_target_url,
                          STORE_SERVER_URL)

        mock_runner.tests = [
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
         'url2': None}]

        self.assertEquals(len(self.store_server.load_requests), 1)
        self.assertEquals(self.store_server.save_requests, [])
        remote_store.save(sample_metadata)
        self.assertEquals(len(self.store_server.load_requests), 1)
        self.assertEquals(self.store_server.save_requests, [{
            "username": "alice",
            "token": "a_token",
            "metadata": sample_metadata,
            "protocol_version": RemoteTestStore.PROTOCOL_VERSION,
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
                }
            ]
        }])

        remote_store.cleanup()
        self.assertEquals(mock_runner.webapp.proxy_mappings, None)
        self.assertEquals(mock_runner.webapp.default_target_url, None)

    def test_protocol_version_mismatch(self):
        self.store_server.credentials = {
            "alice": "a_token",
        }
        store_info = {
            "remote_url": STORE_SERVER_URL,
            "username": "alice",
            "token": "a_token",
        }
        mock_runner = MockRunner()
        remote_store = RemoteTestStore(mock_runner, store_info)
        old_supported_protocol_version = HTTPHandler.SUPPORTED_PROTOCOL_VERSION
        HTTPHandler.SUPPORTED_PROTOCOL_VERSION = 99
        self.assertRaises(StoreException, remote_store.load, {})
        self.assertRaises(StoreException, remote_store.save, {})
        HTTPHandler.SUPPORTED_PROTOCOL_VERSION = old_supported_protocol_version

    def test_invalid_token(self):
        self.store_server.credentials = {
            "alice": "a_token",
        }
        store_info = {
            "remote_url": STORE_SERVER_URL,
            "username": "alice",
            "token": "invalid_token",
        }
        mock_runner = MockRunner()
        remote_store = RemoteTestStore(mock_runner, store_info)
        self.assertRaises(StoreException, remote_store.load, {})
        self.assertRaises(StoreException, remote_store.save, {})


    def test_invalid_username(self):
        self.store_server.credentials = {
            "alice": "a_token",
        }
        store_info = {
            "remote_url": STORE_SERVER_URL,
            "username": "no-such-user",
            "token": "a_token",
        }
        mock_runner = MockRunner()
        remote_store = RemoteTestStore(mock_runner, store_info)
        self.assertRaises(StoreException, remote_store.load, {})
        self.assertRaises(StoreException, remote_store.save, {})

if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG)

    if "--server" in sys.argv:
        store_server = StoreServer()
        store_server.tests_path = remote_data_dir
        try:
            while store_server.httpd_running:
                time.sleep(1)
        except KeyboardInterrupt:
            # If not killed other thread will keep it running
            if hasattr(os, "kill"):
                os.kill(os.getpid(), signal.SIGKILL)
        sys.exit()

    TestRemoteStore.setup_class()
    unittest.main()
    testRemoteStore.teardown_class()
