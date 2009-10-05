import httplib
import os
import unittest
import urllib

from w3testrunner.webapp import WebApp

webapp = None
webapp_data_dir = os.path.join(os.path.dirname(__file__), "webapp_data")

# Useful when debugging:
#httplib.HTTPConnection.debuglevel = 1

class MockRunner(object):
    def __init__(self):
        self.running = True
        self.ua_string = None

        class MockOptions(object):
            nouacheck = False
        self.options = MockOptions()

class TestWebApp(unittest.TestCase):

    def testRoot(self):
        conn = httplib.HTTPConnection("localhost", 8888)
        conn.request("GET", "/")
        response = conn.getresponse()
        self.assertEqual(response.status, 200)
        self.assertEqual(response.reason, "OK")
        self.assertEqual(response.getheader("content-type"), "text/html")
        self.assertNotEqual(response.getheader("date"), None)
        self.assertNotEqual(response.getheader("server"), None)
        content = response.fp.read()
        self.assertTrue("W3TestRunner" in content)

    def testCGI(self):
        conn = httplib.HTTPConnection("localhost", 8888)
        conn.request("GET", "/hello_cgi.py")
        response = conn.getresponse()
        self.assertEqual(response.status, 404)
        self.assertEqual(response.reason, "Not found")
        self.assertEqual(response.getheader("content-type"), "text/plain")

        webapp.enable_localtests(webapp_data_dir)

        conn.request("GET", "/hello_cgi.py")
        response = conn.getresponse()
        self.assertEqual(response.status, 200)
        self.assertEqual(response.reason, "OK")
        self.assertEqual(response.getheader("content-type"), "text/plain")
        content = response.fp.read()
        self.assertEqual(content, "Test content here\n")

        conn.request("GET", "/status_cgi.py")
        response = conn.getresponse()
        self.assertEqual(response.status, 500)
        self.assertEqual(response.reason, "Doh, Server Error")
        self.assertEqual(response.getheader("content-type"), "text/plain")
        # the status_cgi.py^headers^ file should not be parsed when executing
        # CGI.
        self.assertEqual(response.getheader("X-Should-Be-Ignored"), None)
        content = response.fp.read()
        self.assertEqual(content, "Test content here\n")

        conn.request("GET", "/webob_cgi.py")
        response = conn.getresponse()
        self.assertEqual(response.status, 200)
        self.assertEqual(response.reason, "OK")
        self.assertEqual(response.getheader("content-type"), "text/plain")
        self.assertEqual(response.getheader("X-Some-Header"), "Foo Value")
        content = response.fp.read()
        self.assertEqual(content, "get_param:  post_param: ")

        conn.request("GET", "/webob_cgi.py?get_param=A%20param")
        response = conn.getresponse()
        self.assertEqual(response.status, 200)
        self.assertEqual(response.reason, "OK")
        self.assertEqual(response.getheader("content-type"), "text/plain")
        self.assertEqual(response.getheader("X-Some-Header"), "Foo Value")
        content = response.fp.read()
        self.assertEqual(content, "get_param: A param post_param: ")

        params = urllib.urlencode({'post_param': 'A posted param'})
        headers = {"Content-type": "application/x-www-form-urlencoded",
                   "Accept": "text/plain"}
        conn.request("POST", "/webob_cgi.py", params, headers)
        response = conn.getresponse()
        self.assertEqual(response.status, 200)
        self.assertEqual(response.reason, "OK")
        self.assertEqual(response.getheader("content-type"), "text/plain")
        self.assertEqual(response.getheader("X-Some-Header"), "Foo Value")
        content = response.fp.read()
        self.assertEqual(content, "get_param:  post_param: A posted param")

        webapp.disable_localtests()

        conn.request("GET", "/hello_cgi.py")
        response = conn.getresponse()
        self.assertEqual(response.status, 404)
        self.assertEqual(response.reason, "Not found")
        self.assertEqual(response.getheader("content-type"), "text/plain")

    def testHeaders(self):
        conn = httplib.HTTPConnection("localhost", 8888)
        webapp.enable_localtests(webapp_data_dir)

        conn.request("GET", "/foo.xml")
        response = conn.getresponse()
        self.assertEqual(response.status, 200)
        self.assertEqual(response.reason, "OK")
        self.assertEqual(response.getheader("content-type"), "text/xml")
        self.assertEqual(response.getheader("X-Some-Header"), "Foo Value")
        content = response.fp.read()
        self.assertEqual(content,
                         """<?xml version="1.0" encoding="UTF-8"?><foo/>\n""")

        conn.request("GET", "/foo.oga")
        response = conn.getresponse()
        self.assertEqual(response.status, 404)
        self.assertEqual(response.reason, "Sorry, can't find it")
        self.assertEqual(response.getheader("content-type"), "audio/ogg")
        self.assertEqual(response.getheader("X-Some-Header2"), "Foo Value 2")
        content = response.fp.read()
        self.assertEqual(content, "Test content here\n")

        webapp.disable_localtests()

def setup():
    global webapp
    mock_runner = MockRunner()
    webapp = WebApp(mock_runner)

def teardown():
    webapp.running = False
