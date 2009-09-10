import time
import os
import sys
import logging
import subprocess
import urllib2
import httplib
import threading
import datetime
import re
import errno
import random
try:
    import simplejson as json
except ImportError:
    import json # Python >= 2.6

from webob import Request, Response
from paste.urlparser import StaticURLParser
from paste.proxy import TransparentProxy
import paste.httpserver

from w3testrunner.imagecompare import ImageComparator, ImageCompareException

WEBAPP_PORT = 8888

XR_HTTPD_HOST = "localhost:8889"
XR_HTTPD_BASEURL = "http://%s/" % XR_HTTPD_HOST

class Message(object):
    def __str__(self):
        return "<%s, type: %s>" % (self.__class__.__name__, self.type)

class ClientMessage(Message):
    def __init__(self, json_string):
        json_object = json.loads(json_string)
        self.__dict__.update(json_object)

    def __getattr__(self, name):
        return None

class ServerMessage(Message):
    test_count = -1
    start_time = time.time()

    def __init__(self):
        super(ServerMessage, self).__init__()
        self.test_index = -1

    def dump_json(self):
        time_elapsed = time.time() - ServerMessage.start_time
        ratio = max(0.01, float(self.test_index) / ServerMessage.test_count)
        time_est_total = time_elapsed / ratio
        time_est_remaining = time_est_total - time_elapsed
        self.percent = str(int(ratio * 100.0))

        for n in ["time_elapsed", "time_est_remaining", "time_est_total"]:
            delta = datetime.timedelta(seconds=locals()[n])
            # XXX this assumes the string has format hh:mm:ss.mmmmm
            setattr(self, n, str(delta).split(".")[0])

        json_keys = set(["type", "url", "test_id", "test_index", "test_count",
                         "percent", "time_elapsed", "time_est_remaining",
                         "time_est_total", "error_msg", "error_image_path"])
        d = {}
        d.update(dict((k, v) for (k, v) in self.__class__.__dict__.iteritems()
                             if k in json_keys))
        d.update(dict((k, v) for (k, v) in self.__dict__.iteritems()
                             if k in json_keys))

        return json.dumps(d)

class WebAppException(Exception):
    def __init__(self, message):
        self.message = message
    def __str__(self):
        return self.message

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
    "xul": "application/vnd.mozilla.xul+xml",
    "jar": "application/x-jar",
    "ogg": "application/ogg",
    "ogv": "video/ogg",
    "oga": "audio/ogg",
}

class WebApp(object):
    def __init__(self, runner=None, debug=False, tests_path=None):
        self.log = logging.getLogger(self.__class__.__name__)
        self.failed = False
        self.runner = runner
        self.server = None
        self.debug = debug
        self.tests_path = tests_path

        self.pkg_dir = os.path.dirname(os.path.abspath(__file__))

        # Use 1min of max age to avoid using cached files after an update.
        self.mainapp = MimeUpdaterMiddleware(StaticURLParser(self.tests_path,
                                                             cache_max_age=60),
                                             MIME_MAPPINGS)

        self.resourcesapp = StaticURLParser(os.path.join(self.pkg_dir,
                                                         "resources"),
                                            cache_max_age=60)

        reftest_results_path = self.runner.options.reftest_results_path
        if not reftest_results_path:
            reftest_results_path = os.path.join(self.pkg_dir, "reftest_results")
        self.reftest_results_app = StaticURLParser(reftest_results_path,
                                                   cache_max_age=60)

        self.image_comparator = ImageComparator(results_path=
                                                reftest_results_path)
        self.screenshot1_id = -1

        threading.Thread(target=self.run_server).start()

    def _can_connect(self, url, verbose=False):
        try:
            urllib2.urlopen(url).read()
        # XXX see why getting BadStatusLine sometimes.
        except (urllib2.URLError, httplib.BadStatusLine):
            e = sys.exc_info()[1]
            if verbose:
                self.log.debug("Exception in _can_connect: %s", e)
            # with 2.6 e.reason.errno can be used instead of e.reason.args[0]
            if e.reason.args[0] == errno.ECONNREFUSED:
                return False
        return True

    def run_server(self):
        # NOTE: wsgiref.simple_server.make_server raises "Hop-by-hop headers not allowed" when using the
        # paste.proxy import TransparentProxy application. There's no issue with paste.httpserver
        #self.server = simple_server.make_server("localhost", WEBAPP_PORT, self)

        # Reduce some paste server noise
        logging.getLogger('paste').setLevel(logging.INFO)
        self.server = paste.httpserver.serve(self, host="%s:%s" % ("",
                                             WEBAPP_PORT), start_loop=False)
        self.log.debug("SERVER %s", self.server)

        self.server.running = True
        self.log.info('Serving on http://localhost:%s' % WEBAPP_PORT)

        #server.serve_forever()
        self.server.stopped = False
        while self.server.running:
            #log.debug("Handling request")
            self.server.handle_request()
        self.server.server_close()
        self.server.stopped = True
        self.log.debug("Web Server stopped")

    def stop(self):
        if not self.server:
            return
        self.server.running = False

        time.sleep(0.5)

        if not self.server.stopped:
            self.log.debug("Sending dummy message to server for shut down")
            # Dummy request to shut down server
            self._can_connect("http://localhost:%i/ping" % WEBAPP_PORT)
        # Stop it again in case it wasn't started the first time we asked to stop
        if self.server:
            self.server.running = False

    def _return_failure(self, exception, environ, start_response):
        self.log.exception(exception)

        server_msg = ServerMessage()
        server_msg.type = "error"
        server_msg.error_msg = str(exception)
        if (isinstance(exception, ImageCompareException) and
            exception.error_image_path):
            server_msg.error_image_path = exception.error_image_path
        return Response(server_msg.dump_json())(environ, start_response)

    def handle_client_message(self, environ, start_response):
        req = Request(environ)
        data = req.environ['wsgi.input'].read(int(req.environ['CONTENT_LENGTH']))
        self.log.debug("Received client message")

        try:
            client_msg = ClientMessage(data)
        except ValueError, ve:
            raise WebAppException("Error parsing JSON: %s" % ve)

        server_msg = {}

        if client_msg.type == "get_tests":
            server_msg["tests"] = self.runner.tests

        elif client_msg.type == "take_screenshot1":
            self.image_comparator.grab_image1()
            self.screenshot1_id = random.randint(0, 2**32)
            server_msg["screenshot1_id"] = self.screenshot1_id

        elif client_msg.type == "take_screenshot2_and_compare":
            if client_msg.screenshot1_id != self.screenshot1_id:
                raise Exception("Unknown screenshot id to compare with")
            self.screenshot1_id = -1
            self.image_comparator.grab_image2()
            server_msg["pixel_diff"] = pixel_diff = self.image_comparator.compare_images()

            if (client_msg.save_images == "always" or
                (client_msg.save_images == "if_pixel_diff_gt_0" and pixel_diff > 0) or
                (client_msg.save_images == "if_pixel_diff_eq_0" and pixel_diff == 0)):
                self.log.debug("Saving images")
                server_msg["images_path"] = self.image_comparator.save_images()

            self.image_comparator.reset()

        resp = Response(json.dumps(server_msg))

        # IE has troubles if charset=utf-8 is in the content type.
        # Don't use the content_type setter here
        resp.headers["content-type"] = "text/html"
        return resp(environ, start_response)

    def __call__(self, environ, start_response):
        req = Request(environ)

        if self.runner and req.path_info == "/testservice":
            try:
                return self.handle_client_message(environ, start_response)
            except (WebAppException, ImageCompareException), e:
                return self._return_failure(e, environ, start_response)
            except Exception, e:
                # Rewrap the exception to give more information
                e = Exception("Unknown error while processing client message: %s" % e)
                return self._return_failure(e, environ, start_response)

        if (req.path_info.startswith("/MochiKit") or
            req.path_info.startswith("/static") or
            req.path_info.startswith("/tests/SimpleTest/") or
            req.path_info == "/"):
            return self.resourcesapp(environ, start_response)

        if self.runner and req.path_info_peek() == "reftest_results":
            environ["PATH_INFO"] = re.sub("^/reftest_results", "", environ["PATH_INFO"])
            return self.reftest_results_app(environ, start_response)

        if req.path_info_peek() == "ping":
            return Response("pong")(environ, start_response)

        return self.mainapp(environ, start_response)
