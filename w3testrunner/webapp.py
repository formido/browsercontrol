from __future__ import with_statement

import base64
import errno
import httplib
import logging
import os
import random
import re
import select
import subprocess
import sys
import threading
import time
import urllib2
import urlparse
try:
    import simplejson as json
except ImportError:
    import json # Python >= 2.6

from lovely.jsonrpc import dispatcher, wsgi
from paste.urlparser import StaticURLParser
from paste.proxy import TransparentProxy
from paste.httpserver import WSGIHandler
from paste.cgiapp import CGIApplication, CGIWriter, StdinReader, \
                         proc_communicate
import paste.httpserver
from webob import Request
from webob.headerdict import HeaderDict

from w3testrunner.imagecompare import ImageComparator, ImageCompareException
from w3testrunner.teststores.common import StoreException

log = logging.getLogger(__name__)

WEBAPP_HOST = "localhost"
WEBAPP_PORT = 8888

class RPC(object):
    def __init__(self, webapp):
        self.webapp = webapp
        self.runner = webapp.runner

        self.image_comparator = ImageComparator()
        self.screenshot1_id = -1

    def reset(self):
        self.runner.reset()

    def clear_results(self):
        self.runner.clear_results()

    def get_state(self):
        return self.runner.get_state()

    def load_tests(self, store_info):
        success, message = True, ""
        try:
            self.runner.load_tests(store_info)
        except StoreException, e:
            success, message = False, "Error: %s" % e

        return {
            "success": success,
            "message": message,
        }

    def set_status(self, status, message):
        self.runner.set_status(status, message)

    def take_screenshot1(self):
        try:
            self.image_comparator.grab_image1()
        except ImageCompareException, e:
            return {
                "success": False,
                "message": str(e),
                # path? or image string?
                "error_image": e.error_image,
            }

        self.screenshot1_id = random.randint(0, 2**32)
        return {
            "success": True,
            "screenshot1_id": self.screenshot1_id
        }

    def take_screenshot2_and_compare(self, screenshot1_id, save_images):
        if screenshot1_id != self.screenshot1_id:
            raise Exception("Unknown screenshot id to compare with")
        try:
            self.image_comparator.grab_image2()
        except ImageCompareException, e:
            return {
                "success": False,
                "message": str(e)
            }
        self.screenshot1_id = -1

        pixel_diff = self.image_comparator.compare_images()

        images_path = None
        images = {}
        if (save_images == "always" or
            (save_images == "if_pixel_diff_gt_0" and pixel_diff > 0) or
            (save_images == "if_pixel_diff_eq_0" and pixel_diff == 0)):
            log.debug("Saving images")
            images = self.image_comparator.save_images()

        self.image_comparator.reset()
        ret = {
            "success": True,
            "pixel_diff": pixel_diff,
        }
        ret.update(images)
        return ret

    def test_started(self, testid):
        self.runner.test_started(testid)

    def suspend_timer(self, testid, suspended):
        self.runner.suspend_timer(testid, suspended)

    def set_result(self, testid, result, did_start_notify):
        self.runner.set_result(testid, result, did_start_notify)

class RPCErrorMiddleware(object):
    """Middleware that will notify the runner in case of error.

    It expects the target application to be using the JSON-RPC protocol.
    """

    def __init__(self, application, runner):
        self.application = application
        self.runner = runner

    def __call__(self, environ, start_response):
        # import here to prevent cyclic import.
        from w3testrunner import runner

        req = Request(environ)
        if self.runner.status == runner.ERROR:
            input_json = json.loads(req.body)
            ALLOWED_ERROR_METHODS = ("reset", "load_tests", "get_state",
                                     "suspend_timer")
            if not input_json["method"] in ALLOWED_ERROR_METHODS:
                start_response("200 OK", [("Content-Type", "application/json")])
                return json.dumps({
                    "result": None,
                    "error": {
                        "type": "",
                        "message": "RPC method discarded because of ERROR "
                                   "condition (%s)" % self.runner.status_message,
                    },
                })

        body = self.application(environ, start_response)
        body_json = json.loads("".join(body))
        if "error" in body_json:
            self.runner.set_status(runner.ERROR,
                                   "Server-side RPC Error: %s %s" % (
                                   body_json["error"]["type"],
                                   body_json["error"]["message"]))
        return body

class MimeAndHeadersUpdaterMiddleware(object):
    HEADERS_FILE_SUFFIX = "^headers^"
    # See also: http://mxr.mozilla.org/mozilla-central/source/testing/mochitest/server.js#195
    MIME_MAPPINGS = {
        "html": "text/html",
        "ico": "image/x-icon",
        "xul": "application/vnd.mozilla.xul+xml",
        "jar": "application/x-jar",
        "ogg": "application/ogg",
        "ogv": "video/ogg",
        "oga": "audio/ogg",
        "xml": "text/xml",
        "xhtml": "application/xhtml+xml",
        "svg": "image/svg+xml",
    }

    def __init__(self, application, tests_path=None):
        self.application = application
        self.tests_path = tests_path

    def _maybe_parse_headers_file(self, path_info):
        if not self.tests_path:
            return None, {}
        path_info = path_info.lstrip("/")
        target = os.path.normpath(os.path.join(self.tests_path, path_info))
        if not os.path.isfile(target):
            return None, {}

        headers_file = target + self.HEADERS_FILE_SUFFIX
        if not os.path.isfile(headers_file):
            return None, {}

        status = None
        headers = {}
        with open(headers_file) as f:
            for l in f:
                l = l.strip()
                if not l:
                    continue

                if l.startswith("HTTP "):
                    status = l[len("HTTP "):]
                    continue
                i = l.find(":")
                if i < 0:
                    log.warn("Invalid header line (%s) in file %s", l,
                             headers_file)
                    continue
                key, val = l[:i], l[i + 1:]
                headers[key.strip()] = val.strip()
        return status, headers

    def __call__(self, environ, start_response):
        path_info = environ.get('PATH_INFO', '')

        def start_mime_update(status, response_headers, exc_info=None):
            ext = os.path.splitext(environ["SCRIPT_NAME"])[1].lower()[1:]

            header_dict = HeaderDict.view_list(response_headers)
            if ext in self.MIME_MAPPINGS:
                header_dict["Content-Type"] = self.MIME_MAPPINGS[ext]

            new_status, headers = self._maybe_parse_headers_file(path_info)
            if new_status:
                status = new_status

            # HeaderDict.update() doesn't do what we need here.
            for k, v in headers.iteritems():
                header_dict[k] = v

            return start_response(status, response_headers, exc_info)

        return self.application(environ, start_mime_update)

class PythonCGIApplication(CGIApplication):
    """
    Override CGIApplication to execute CGI scripts with the current Python
    interpreter.

    (and apply the patch from
     http://trac.pythonpaste.org/pythonpaste/ticket/382).
    """

    def __call__(self, environ, start_response):
        if 'REQUEST_URI' not in environ:
            environ['REQUEST_URI'] = (
                environ.get('SCRIPT_NAME', '')
                + environ.get('PATH_INFO', ''))
        if self.include_os_environ:
            cgi_environ = os.environ.copy()
        else:
            cgi_environ = {}
        for name in environ:
            # Should unicode values be encoded?
            if (name.upper() == name
                and isinstance(environ[name], str)):
                cgi_environ[name] = environ[name]
        if self.query_string is not None:
            old = cgi_environ.get('QUERY_STRING', '')
            if old:
                old += '&'
            cgi_environ['QUERY_STRING'] = old + self.query_string

        # When running the unit tests without nose, the script path is not
        # absolute and tests fail.
        self.script = os.path.abspath(self.script)
        cgi_environ['SCRIPT_FILENAME'] = self.script
        proc = subprocess.Popen(
            # Begin Paste modification.
            # The -u option is used prevent Python replacing \n to \r\n when
            # writing to sys.stdout on Windows.
            [sys.executable, '-u', self.script],
            # End Paste modification.
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=cgi_environ,
            cwd=os.path.dirname(self.script),
            )
        writer = CGIWriter(environ, start_response)
        if select and sys.platform != 'win32':
            proc_communicate(
                proc,
                stdin=StdinReader.from_environ(environ),
                stdout=writer,
                stderr=environ['wsgi.errors'])
        else:
            stdout, stderr = proc.communicate(StdinReader.from_environ(environ).read())
            if stderr:
                environ['wsgi.errors'].write(stderr)
            writer.write(stdout)
        if not writer.headers_finished:
            start_response(writer.status, writer.headers)
        return []

class ProxyRemappingMiddleware(object):
    def __init__(self, application, paths_mappings):
        self.application = application
        self.paths_mappings = paths_mappings

    def __call__(self, environ, start_response):
        path_info = environ["PATH_INFO"]
        for source_path, target_path in self.paths_mappings:
            if not path_info.startswith(source_path):
                continue
            environ["PATH_INFO"] = path_info.replace(source_path,
                                                     target_path, 1)
            log.debug("Found mapping %s => %s", source_path, target_path)
            return self.application(environ, start_response)

        start_response("404 Not found", [("Content-type", "text/plain")])
        return "Not found"

class PortCheckerMixin(object):
    server_host = "localhost"
    server_port = -1

    def _can_connect(self, path, verbose=False):
        assert self.server_port > 0, "self.server_port must be set"

        url = "http://%s:%s%s" % (self.server_host, self.server_port, path)
        try:
            # XXX timeout is 2.6 only
            urllib2.urlopen(url, timeout=5).read()
        # XXX see why getting BadStatusLine sometimes.
        except (urllib2.URLError, httplib.BadStatusLine):
            e = sys.exc_info()[1]
            log.debug("Exception in _can_connect: %s", e)
            if isinstance(e, urllib2.HTTPError):
                return True
            # with 2.6 e.reason.errno can be used instead of e.reason.args[0]
            if e.reason.args[0] == errno.ECONNREFUSED:
                return False
        return True

    def check_free_port(self):
        for i in range(5):
            if not self._can_connect("/stop"):
                break
            log.info("Server already running, trying to stop it...")
            time.sleep(2)
        else:
            raise Exception("Something is listening on port %s, can't start "
                            " the server." % self.server_port)

    def check_server_started(self):
        for i in range(5):
            if self._can_connect("/"):
                return
            time.sleep(2)
        else:
            raise Exception("The server is not listening on port %s after "
                            "startup" % self.server_port)

class WebApp(PortCheckerMixin):
    def __init__(self, runner):
        self.runner = runner
        self.image_store = {}
        self.image_store_last_index = -1
        self.running = False

        thisdir = os.path.dirname(os.path.abspath(__file__))

        self.resourcesapp = MimeAndHeadersUpdaterMiddleware(
            StaticURLParser(os.path.join(thisdir, "resources"),
                            cache_max_age=60))

        self.rpc = RPC(self)
        rpcdispatcher = dispatcher.JSONRPCDispatcher(self.rpc, json_impl=json)
        self.rpcapp = wsgi.WSGIJSONRPCApplication({'rpc': rpcdispatcher})
        self.rpcapp = RPCErrorMiddleware(self.rpcapp, self.runner)

        # Disable lovely.jsonrpc debug messages which can be quite large when
        # transfering image data URLs.
        logging.getLogger('lovely.jsonrpc').setLevel(logging.INFO)

        self.tests_path = None
        self.localtests_app = None
        self.remotetests_app = None

        self.server_host = WEBAPP_HOST
        self.server_port = WEBAPP_PORT
        self.check_free_port()

        threading.Thread(target=self._run_server).start()

        self.check_server_started()
        self.runner.ua_string = None

    def _run_server(self):
        # NOTE: wsgiref.simple_server.make_server raises
        # "Hop-by-hop headers not allowed" when using the
        # paste.proxy.TransparentProxy application. There's no issue with
        # paste.httpserver
        #server = simple_server.make_server(WEBAPP_HOST, WEBAPP_PORT, self)

        # Reduce some paste server noise
        logging.getLogger('paste').setLevel(logging.INFO)
        server = paste.httpserver.serve(self, host="%s:%s" % ("", WEBAPP_PORT),
                                        start_loop=False)

        self.running = True
        log.debug("Serving on http://%s:%s" % (WEBAPP_HOST, WEBAPP_PORT))

        while self.running:
            #log.debug("Handling request")
            server.handle_request()
        server.server_close()
        log.debug("Web Server stopped")

    def enable_localtests(self, tests_path):
        self.tests_path = tests_path
        self.localtests_app = MimeAndHeadersUpdaterMiddleware(
            StaticURLParser(tests_path, cache_max_age=60), tests_path)

    def disable_localtests(self):
        self.tests_path = None
        self.localtests_app = None

    def enable_remotetests(self, proxy_mappings, default_target_url):
        """Set up a proxy to reach remote tests through another host.

        Arguments:
        proxy_mappings -- list of (source_url, target_url) mappings.
        default_target_url -- The hostname and port of this URL is used for the
                              default proxy destination.

        Limitations:

        The source host and port must be the same as the Web Application
        (localhost:8888).
        The target_url hostname and port must match the ones in the
        default_target_url argument, or not be specified.
        """
        default_target_parseresult = urlparse.urlparse(default_target_url)
        assert default_target_parseresult.scheme == "http"
        target_netloc = default_target_parseresult.netloc

        path_mappings = []

        for (source, target) in proxy_mappings:
            source_parseresult = urlparse.urlparse(source)
            assert source_parseresult.scheme == "http"
            assert source_parseresult.hostname == WEBAPP_HOST
            assert source_parseresult.port == WEBAPP_PORT
            target_parseresult = urlparse.urlparse(target)

            assert target_parseresult.scheme in ("", "http")
            assert target_parseresult.hostname == None or \
                   target_parseresult.hostname == default_target_parseresult.hostname
            assert target_parseresult.port == None or \
                   target_parseresult.port == default_target_parseresult.port
            path_mappings.append((source_parseresult.path,
                                  target_parseresult.path))

        self.remotetests_app = ProxyRemappingMiddleware(
            TransparentProxy(force_host=target_netloc), path_mappings)

    def disable_remotetests(self):
        self.remotetests_app = None

    def _create_report(self, req, start_response):
        # import here to prevent cyclic import.
        from w3testrunner import runner

        state = self.runner.get_state().copy()
        state["status_pretty"] = runner.STATUS_TO_NAME[state["status"]]

        result_rows = []
        for test in state["tests"]:
            status = "N/A"
            if "result" in test:
                status = test["result"]["status"]
            result_rows.append(("<tr><td>%s</td><td>%s</td>"
                                "<td class='result-%s'>%s</td></tr>") %
                                (test["type"], test["full_id"], status,
                                 status.upper()))

        state["results"] = "\n".join(result_rows)
        state["test_count"] = len(state["tests"])
        page = """<!DOCTYPE html>
<html>
<head>
    <title>W3TestRunner Test report</title>
    <link rel="stylesheet" type="text/css" href="/testrunner/testrunner.css"/>
    <style>
    </style>
</head>
<body>
    <h1>W3TestRunner Test report</h1>
    <h2>Test environment information</h2>
    <dl>
        <dt>Useragent:</dt>
        <dd>%(ua_string)s</dd>
        <dt>Status:</dt>
        <dd>%(status_pretty)s</dd>
        <dt>Status Message:</dt>
        <dd>%(status_message)s</dd>
        <dt>Number of tests:</dt>
        <dd>%(test_count)s</dd>
    </dl>
    <h2>Results Table</h2>
    <table id="testsTable">
        <thead>
            <tr>
                <th style='min-width: 0'>Test Type</th>
                <th>Test Identifier</th>
                <th>Status</th>
            </tr>
        </thead>
        <tbody>
%(results)s
        <tbody>
    </table>
</body>
        """ % state

        start_response("200 OK", [("Content-type", "text/html")])
        return page

    def _handle_image_store(self, req, start_response):
        def return_500(msg):
            start_response("500 Error", [("Content-type", "text/plain")])
            return msg

        req.path_info_pop()
        if req.path_info_peek() == "put":
            log.debug("Image store size: %s", len(self.image_store.keys()))
            head = "data:image/png;base64,"
            if not req.body.startswith(head):
                return return_500("Invalid image to store")
            data = base64.b64decode(req.body[len(head):])
            if not data.startswith("\x89PNG"):
                return return_500("Bad image. Should be PNG")

            self.image_store_last_index += 1
            self.image_store[self.image_store_last_index] = data

            MAX_IMAGES = 5
            trim_index_start = self.image_store_last_index - MAX_IMAGES
            while True:
                if not trim_index_start in self.image_store:
                    break
                del self.image_store[trim_index_start]
                trim_index_start -= 1

            start_response("200 OK", [("Content-type", "text/plain")])
            return str(self.image_store_last_index)

        if req.path_info_peek() == "get":
            req.path_info_pop()
            try:
                index = int(req.path_info_pop())
            except ValueError:
                return return_500("Index not an integer")
            if not index in self.image_store:
                return return_500("No image at this index")

            start_response("200 OK", [("Content-type", "image/png")])
            return self.image_store[index]

    def __call__(self, environ, start_response):
        req = Request(environ)

        if req.path_info_peek() == "stop":
            log.info("Received a /stop HTTP request, stopping the runner.")
            self.running = False
            self.runner.running = False
            start_response("200 OK", [("Content-type", "text/plain")])
            return "Stopping server"

        if not self.runner.running:
            start_response("500 Internal Server Error",
                           [("Content-type", "text/plain")])
            return "Error: The Runner is not running"

        if not self.runner.ua_string:
            self.runner.ua_string = req.user_agent

        if (not self.runner.options.nouacheck and
            self.runner.ua_string and
            self.runner.ua_string != req.user_agent):
            start_response("500 Internal Server Error",
                           [("Content-type", "text/plain")])
            return (("The server received a request from a different user "
                     "agent.\n Original ua: %s\n This ua: %s\n"
                     "You should restart the server or use the original "
                     "user agent.") %
                    (self.runner.ua_string, req.user_agent))

        if req.path_info_peek() == "imagestore":
            return self._handle_image_store(req, start_response)

        if req.path_info_peek() == "report":
            return self._create_report(environ, start_response)

        if (req.path_info == "/" or
            req.path_info == "/favicon.ico" or
            req.path_info == ("/browsertest.js") or
            req.path_info == ("/browsertest.css") or
            req.path_info.startswith("/testrunner") or
            # For Mochitests:
            req.path_info.startswith("/MochiKit") or
            req.path_info.startswith("/tests/SimpleTest/")):
            return self.resourcesapp(environ, start_response)

        if req.path_info_peek() == "rpc":
            return self.rpcapp(environ, start_response)

        if req.path_info.endswith(".py") and self.tests_path:
            script = req.path_info.lstrip("/")
            cgiapp = PythonCGIApplication({}, script=script, path=[self.tests_path])
            return cgiapp(environ, start_response)

        if self.localtests_app:
            return self.localtests_app(environ, start_response)
        if self.remotetests_app:
            return self.remotetests_app(environ, start_response)

        # Default response
        start_response("404 Not found", [("Content-type", "text/plain")])
        return "Not found"
