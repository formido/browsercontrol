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

from webob import Request, Response
from paste.urlparser import StaticURLParser
from paste.proxy import TransparentProxy
import paste.httpserver
import simplejson
from django.conf import settings

WEBAPP_PORT = 8888

XR_HTTPD_HOST = "localhost:8889"
XR_HTTPD_BASEURL = "http://%s/" % XR_HTTPD_HOST

class Message(object):
    def __str__(self):
        return "<%s, type: %s>" % (self.__class__.__name__, self.type)

class ClientMessage(Message):
    def __init__(self, json):
        self.json = json
        json_object = simplejson.loads(json)
        self.__dict__.update(json_object)

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
                         "time_est_total", "error_msg"])
        d = {}
        d.update(dict((k, v) for (k, v) in self.__class__.__dict__.iteritems()
                             if k in json_keys))
        d.update(dict((k, v) for (k, v) in self.__dict__.iteritems()
                             if k in json_keys))

        return simplejson.dumps(d)

class WebAppException(Exception):
    pass

class WebApp(object):
    def __init__(self, runner=None, debug=False, tests_path=None):
        self.log = logging.getLogger(self.__class__.__name__)
        self.ua_string = None
        self.failed = False
        self.runner = runner
        self.server = None
        self.debug = debug
        self.tests_path = tests_path
        self.session_id = str(int(time.time()))
        self.log.info("WebApp session_id: %s", self.session_id)

        self.xr_proxyapp = None
        self.xr_proxyapp = TransparentProxy(force_host=XR_HTTPD_HOST)

        self.pkg_dir = os.path.dirname(os.path.abspath(__file__))
        # Use 1min of max age to avoid using cached files after an update.
        # XXX does it make sense with httpd.js?
        self.mainapp = StaticURLParser(self.tests_path, cache_max_age=60)
        self.framerunnerapp = StaticURLParser(os.path.join(self.pkg_dir, "framerunner"),
                                              cache_max_age=60)
        self._start_xr_httpdjs()

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

    def _start_xr_httpdjs(self):
        tries = 10
        for i in range(tries):
            if not self._can_connect("http://%s/server/shutdown" % XR_HTTPD_HOST):
                break
            self.log.debug("Waiting for old XULRunner httpd to terminate (%i/%i)...", i, tries)
            time.sleep(2)
        else:
            self.log.error("Couldn't stop existing XULRunner httpd")
            sys.exit(1)

        if self._can_connect("http://localhost:%s" % WEBAPP_PORT):
            self.log.error("Something is running on port %s" % WEBAPP_PORT)
            sys.exit(1)
        if self._can_connect(XR_HTTPD_BASEURL):
            self.log.error("Something is running on %s" % XR_HTTPD_BASEURL)
            sys.exit(1)

        os.environ["HTTPDJS_BASE_PATH"] = self.tests_path
        self.log.debug("HTTPDJS_BASE_PATH=%s", self.tests_path)

        args = [settings.XR_PATH,
                os.path.join(self.pkg_dir, "xrhttpd", "application.ini")]

        # XXX always show the console?
        #if self.debug:
        if False:
            args.extend(["-jsconsole", "-console"])

        self.log.debug("xr args %s", args)
        self.xr_proc = subprocess.Popen(args)
        time.sleep(0.5)

        # Check that it is running:
        tries = 15
        for i in range(tries):
            self.log.debug("Waiting for xr httpd startup (%i/%i)...", i, tries)
            if self._can_connect(XR_HTTPD_BASEURL):
                break
            time.sleep(3)
        else:
            self.log.error("Couldn't start XULRunner httpd")
            sys.exit(1)

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
        self.log.debug('Serving on http://localhost:%s' % WEBAPP_PORT)

        #server.serve_forever()
        self.server.stopped = False
        while self.server.running:
            #log.debug("Handling request")
            self.server.handle_request()
        self.server.server_close()
        self.server.stopped = True
        self.log.debug("Web Server stopped")

    def stop(self):
        if self.xr_proc:
            self._can_connect("http://%s/server/shutdown" % XR_HTTPD_HOST,
                              verbose=True)
            self.xr_proc.wait()

        if not self.server:
            return
        self.server.running = False

        time.sleep(0.5)

        if not self.server.stopped:
            self.log.debug("Sending dummy message to server for shut down")
            # Relax the ua string check
            self.ua_string = None
            # Dummy request to shut down server
            self._can_connect("http://localhost:%i/ping" % WEBAPP_PORT)
        # Stop it again in case it wasn't started the first time we asked to stop
        if self.server:
            self.server.running = False

    def _return_failure(self, exception, environ, start_response):
        self.runner.client_msg_q.put(exception)
        self.log.exception(exception)
        self.failed = True
        self.exception = exception

        server_msg = ServerMessage()
        server_msg.type = "error"
        server_msg.error_msg = exception.message
        return Response(server_msg.dump_json())(environ, start_response)

    def handle_client_message(self, environ, start_response):
        req = Request(environ)

        if self.ua_string and not self.runner.options.manual \
           and not self.runner.options.nouacheck:
            # Ignore the "contype" user agent that is sent from IE in some circumstances
            #  (http://support.microsoft.com/default.aspx?scid=kb;en-us;293792)
            if req.user_agent != "contype" and req.user_agent != self.ua_string:
                if self.ua_string == "pending_update":
                    self.ua_string = req.user_agent
                    self.runner.update_ua_string(req.user_agent)
                else:
                    raise WebAppException("Unexpected User agent (saw: '%s', "
                                          "expect: '%s')" % (req.user_agent,
                                          self.ua_string))

        data = req.environ['wsgi.input'].read(int(req.environ['CONTENT_LENGTH']))
        self.log.debug("Received client message")

        try:
            client_msg = ClientMessage(data)
        except ValueError, ve:
            raise WebAppException("Error parsing JSON: %s" % ve)

        if not hasattr(client_msg, "type"):
            raise WebAppException("Invalid Client message, missing type attribute")
        self.log.debug("Client message type: %s", client_msg.type)

        if client_msg.type == "fail":
            raise WebAppException("Failure sent from framerunner client: %s" % client_msg.message)

        if not hasattr(client_msg, "session_id"):
            raise WebAppException("Invalid Client message, missing session_id attribute")

        if not self.runner.options.manual and client_msg.session_id != self.session_id:
            raise WebAppException("Received unknown session_id %s (expecting %s)" %
                                  (client_msg.session_id, self.session_id))

        if client_msg.type == "wants_url":
            # Client sent no test result, nothing to queue
            pass
        elif client_msg.type in ("submit_result", "fail"):
            #self.runner.client_msg_q.put(client_msg)
            self.log.debug("queuing the clientMessage")
            self.runner.client_msg_q.put(client_msg)
        else:
            raise WebAppException("unknown client message type (%s)" % client_msg.type)

        self.log.debug("Waiting for available server message ...")
        server_msg = self.runner.server_msg_q.get()
        self.log.debug("... got server message %s", server_msg)

        resp = Response(server_msg.dump_json())

        #resp.content_type = "application/json"
        # The default content-type headers makes IE return a "parsererror" on the XHR

        # IE has troubles if charset=utf-8 is in the content type.
        # Don't use the content_type setter here
        resp.headers["content-type"] = "text/html"
        return resp(environ, start_response)

    def __call__(self, environ, start_response):
        if self.failed:
            msg = "Failure condition detected, not handling request"
            self.log.error(msg)
            resp = Response(msg)
            return resp(environ, start_response)

        log = self.log
        req = Request(environ)

        if self.runner and req.path_info == "/framerunner/testservice":
            try:
                return self.handle_client_message(environ, start_response)
            except WebAppException, e:
                return self._return_failure(e, environ, start_response)
            except Exception, e:
                # Rewrap the exception to give more information
                e = Exception("Unknown error while processing client message: %s" % e)
                return self._return_failure(e, environ, start_response)

        #resp = req.get_response(self.app)
        #return resp(environ, start_response)

        if self.runner and req.path_info_peek() == "framerunner":
            environ["PATH_INFO"] = re.sub("^/framerunner", "", environ["PATH_INFO"])
            return self.framerunnerapp(environ, start_response)

        if req.path_info_peek() == "ping":
            return Response("pong")(environ, start_response)

        return self.xr_proxyapp(environ, start_response)
        # XXX mainapp is not used any more.
        #return self.mainapp(environ, start_response)
