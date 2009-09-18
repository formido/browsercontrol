import base64
import errno
import httplib
import logging
import os
import random
import re
import sys
import threading
import time
import urllib2
try:
    import simplejson as json
except ImportError:
    import json # Python >= 2.6

from webob import Request
from paste.urlparser import StaticURLParser
import paste.httpserver
from wsgi_jsonrpc import WSGIJSONRPCApplication

from w3testrunner.imagecompare import ImageComparator, ImageCompareException
from w3testrunner.testsloaders import LoaderException

log = logging.getLogger(__name__)

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

    def load_tests(self, type, load_info):
        success, message = True, ""
        try:
            self.runner.load_tests(type, load_info)
        except LoaderException, e:
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
                # path? or image string?
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

class MimeUpdaterMiddleware(object):
    def __init__(self, application, mime_mappings):
        self.application = application
        self.mime_mappings = mime_mappings

    def __call__(self, environ, start_response):
        def start_mime_update(status, response_headers, exc_info=None):
            ext = os.path.splitext(environ["SCRIPT_NAME"])[1].lower()[1:]

            if ext in self.mime_mappings:
                response_headers = [(name,value) for name, value in
                                    response_headers
                                    if name.lower() != "content-type"]
                response_headers.append(("Content-Type",
                                         self.mime_mappings[ext]))

            return start_response(status, response_headers, exc_info)

        return self.application(environ, start_mime_update)

# See also: http://mxr.mozilla.org/mozilla-central/source/testing/mochitest/server.js#195
MIME_MAPPINGS = {
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

class RPCErrorMiddleware(object):
    """Middleware that will notify the running in case of error.
    
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
                start_response('200 OK', [('Content-Type', 'application/json')])
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

class WebApp(object):
    def __init__(self, runner):
        self.runner = runner
        self.image_store = {}
        self.image_store_last_index = -1
        self.running = False

        thisdir = os.path.dirname(os.path.abspath(__file__))

        self.resourcesapp = MimeUpdaterMiddleware(
            StaticURLParser(os.path.join(thisdir, "resources"),
                            cache_max_age=60),
            MIME_MAPPINGS)


        self.rpc = RPC(self)
        self.rpcapp = RPCErrorMiddleware(WSGIJSONRPCApplication(
                                             instance=self.rpc),
                                         self.runner)
        # Disable wsgi_jsonrpc debug messages which can be quite large when
        # transfering image data URLs.
        logging.getLogger('wsgi_jsonrpc').setLevel(logging.INFO)

        self.localtests_app = None

        for i in range(5):
            if not self._can_connect("http://localhost:%s/stop" % WEBAPP_PORT):
                break
            log.info("Server already running, trying to stop it...")
            time.sleep(2)
        else:
            raise Exception("Something is listening on port 8888, can't start "
                            " the server.")

        threading.Thread(target=self._run_server).start()

    def _can_connect(self, url, verbose=False):
        try:
            urllib2.urlopen(url).read()
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

    def _run_server(self):
        # NOTE: wsgiref.simple_server.make_server raises
        # "Hop-by-hop headers not allowed" when using the
        # paste.proxy.TransparentProxy application. There's no issue with
        # paste.httpserver
        #server = simple_server.make_server("localhost", WEBAPP_PORT, self)

        # Reduce some paste server noise
        logging.getLogger('paste').setLevel(logging.INFO)
        server = paste.httpserver.serve(self, host="%s:%s" % ("", WEBAPP_PORT),
                                        start_loop=False)

        self.running = True
        log.debug('Serving on http://localhost:%s' % WEBAPP_PORT)

        while self.running:
            #log.debug("Handling request")
            server.handle_request()
        server.server_close()
        log.debug("Web Server stopped")

    def enable_localtests(self, tests_path):
        self.localtests_app = MimeUpdaterMiddleware(StaticURLParser(tests_path,
                                                        cache_max_age=60),
                                                    MIME_MAPPINGS)

    def disable_localtests(self):
        self.localtests_app = None

    def _create_report(self, req, start_response):
        state = self.runner.get_state().copy()
        state["status_pretty"] = [
            "NEEDS_TESTS", "RUNNING", "FINISHED", "STOPPED", "ERROR"
        ][state["status"]]

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

        start_response("200 OK", [('Content-type', 'text/html')])
        return page

    def _handle_image_store(self, req, start_response):
        def return_500(msg):
            start_response("500 Error", [('Content-type', 'text/plain')])
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

            start_response("200 OK", [('Content-type', 'text/plain')])
            return str(self.image_store_last_index)

        if req.path_info_peek() == "get":
            req.path_info_pop()
            try:
                index = int(req.path_info_pop())
            except ValueError:
                return return_500("Index not an integer")
            if not index in self.image_store:
                return return_500("No image at this index")

            start_response("200 OK", [('Content-type', 'image/png')])
            return self.image_store[index]

    def __call__(self, environ, start_response):
        req = Request(environ)

        if req.path_info_peek() == "stop":
            log.info("Received a /stop HTTP request, stopping the runner.")
            self.running = False
            self.runner.running = False
            start_response("200 OK", [('Content-type', 'text/plain')])
            return "Stopping server"

        if not self.runner.running:
            start_response("500 Internal Server Error",
                           [('Content-type', 'text/plain')])
            return "Error: The Runner is not running"

        if not self.runner.ua_string:
            self.runner.ua_string = req.user_agent

        if (not self.runner.options.nouacheck and
            self.runner.ua_string and
            self.runner.ua_string != req.user_agent):
            start_response("500 Internal Server Error",
                           [('Content-type', 'text/plain')])
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
            req.path_info.startswith("/testrunner") or
            # For MochiTests:
            req.path_info.startswith("/MochiKit") or
            req.path_info.startswith("/tests/SimpleTest/")):
            return self.resourcesapp(environ, start_response)

        if req.path_info_peek() == "rpc":
            return self.rpcapp(environ, start_response)

        if self.localtests_app:
            return self.localtests_app(environ, start_response)

        # Default response
        start_response("404 Not found", [('Content-type', 'text/plain')])
        return "Not found"
