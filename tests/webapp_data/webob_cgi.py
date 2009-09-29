#!/usr/bin/env python

from wsgiref.handlers import CGIHandler, SimpleHandler

from webob import Request, Response

def demo_app(environ, start_response):
    req = Request(environ)

    body = "get_param: %s post_param: %s" % (
        req.GET.get("get_param", ""),
        req.POST.get("post_param", ""),
    )

    res = Response(body)
    res.headers["Content-Type"] = "text/plain"
    res.headers["X-Some-Header"] = "Foo Value"

    return res(environ, start_response)

cgi_handler = CGIHandler().run(demo_app)
