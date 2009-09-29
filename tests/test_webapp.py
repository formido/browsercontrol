import httplib
import os
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

def setup():
    global webapp
    mock_runner = MockRunner()
    webapp = WebApp(mock_runner)

def test_root():
    conn = httplib.HTTPConnection("localhost", 8888)
    conn.request("GET", "/")
    response = conn.getresponse()
    assert response.status == 200
    assert response.reason == "OK"
    assert response.getheader("content-type") == "text/html"
    assert response.getheader("date") != None
    assert response.getheader("server") != None
    content = response.fp.read()
    assert "W3TestRunner" in content

def test_cgi():
    conn = httplib.HTTPConnection("localhost", 8888)
    conn.request("GET", "/hello_cgi.py")
    response = conn.getresponse()
    assert response.status == 404
    assert response.reason == "Not found"
    assert response.getheader("content-type") == "text/plain"

    webapp.enable_localtests(webapp_data_dir)

    conn.request("GET", "/hello_cgi.py")
    response = conn.getresponse()
    assert response.status == 200
    assert response.reason == "OK"
    assert response.getheader("content-type") == "text/plain"
    content = response.fp.read()
    assert content == "Test content here\n"

    conn.request("GET", "/status_cgi.py")
    response = conn.getresponse()
    assert response.status == 500
    assert response.reason == "Doh, Server Error"
    assert response.getheader("content-type") == "text/plain"
    # the status_cgi.py^headers^ file should not be parsed when executing CGI.
    assert response.getheader("X-Should-Be-Ignored") == None
    content = response.fp.read()
    assert content == "Test content here\n"

    conn.request("GET", "/webob_cgi.py")
    response = conn.getresponse()
    assert response.status == 200
    assert response.reason == "OK"
    assert response.getheader("content-type") == "text/plain"
    assert response.getheader("X-Some-Header") == "Foo Value"
    content = response.fp.read()
    assert content == "get_param:  post_param: "

    conn.request("GET", "/webob_cgi.py?get_param=A%20param")
    response = conn.getresponse()
    assert response.status == 200
    assert response.reason == "OK"
    assert response.getheader("content-type") == "text/plain"
    assert response.getheader("X-Some-Header") == "Foo Value"
    content = response.fp.read()
    assert content == "get_param: A param post_param: "

    params = urllib.urlencode({'post_param': 'A posted param'})
    headers = {"Content-type": "application/x-www-form-urlencoded",
               "Accept": "text/plain"}
    conn.request("POST", "/webob_cgi.py", params, headers)
    response = conn.getresponse()
    assert response.status == 200
    assert response.reason == "OK"
    assert response.getheader("content-type") == "text/plain"
    assert response.getheader("X-Some-Header") == "Foo Value"
    content = response.fp.read()
    assert content == "get_param:  post_param: A posted param"

    webapp.disable_localtests()

    conn.request("GET", "/hello_cgi.py")
    response = conn.getresponse()
    assert response.status == 404
    assert response.reason == "Not found"
    assert response.getheader("content-type") == "text/plain"

def test_headers():
    conn = httplib.HTTPConnection("localhost", 8888)
    webapp.enable_localtests(webapp_data_dir)

    conn.request("GET", "/foo.xml")
    response = conn.getresponse()
    assert response.status == 200
    assert response.reason == "OK"
    assert response.getheader("content-type") == "text/xml"
    assert response.getheader("X-Some-Header") == "Foo Value"
    content = response.fp.read()
    assert content == """<?xml version="1.0" encoding="UTF-8"?><foo/>\n"""

    conn.request("GET", "/foo.oga")
    response = conn.getresponse()
    assert response.status == 404
    assert response.reason == "Sorry, can't find it"
    assert response.getheader("content-type") == "audio/ogg"
    assert response.getheader("X-Some-Header2") == "Foo Value 2"
    content = response.fp.read()
    assert content == "Test content here\n"

    webapp.disable_localtests()

def teardown():
    webapp.running = False
