import logging
import urllib2
try:
    import simplejson as json
except ImportError:
    import json # Python >= 2.6

from w3testrunner.teststores.common import TestStore, StoreException

log = logging.getLogger(__name__)

class RemoteTestStore(TestStore):
    name = "remote"
    load_once = False

    # TODO: should point to the production server once implemented.
    DEFAULT_REMOTE_URL = "http://localhost:9999/"
    # Default number of tests to load per iteration.
    DEFAULT_COUNT = 50
    LOAD_PATH = "load/"
    SAVE_PATH = "save/"

    PROTOCOL_VERSION = 1

    def __init__(self, runner, store_info):
        super(RemoteTestStore, self).__init__(runner, store_info)

    def _send_server(self, request, path):
        urllib_request = urllib2.Request(self.store_info["remote_url"] + path)
        request.update({
            "protocol_version": self.PROTOCOL_VERSION,
            "username": self.store_info["username"],
            "token": self.store_info["token"],
        })

        urllib_request.add_header("Content-Type", "application/json")
        try:
            response_body = urllib2.urlopen(urllib_request,
                                            json.dumps(request)).read()
        except urllib2.URLError, e:
            raise StoreException("Can't connect to remote store at %s (%s)" % (
                                 self.store_info["remote_url"], e))

        try:
            response = json.loads(response_body)
        except ValueError, e:
            raise StoreException("Can't parse response JSON: %s" % e)
        log.debug("Server response: %s", response)

        if response["error"]:
            raise StoreException("Error returned from server: %s" %
                                 response["error"])
        return response

    def load(self):
        request = {
            "types": self.store_info.get("types"),
            "count":self.store_info.get("count"),
        }
        load_response = self._send_server(request, RemoteTestStore.LOAD_PATH)

        if "proxy_mappings" in load_response:
            self.runner.webapp.enable_remotetests(
                load_response["proxy_mappings"], self.store_info["remote_url"])

        return load_response["tests"]

    def cleanup(self):
        self.runner.webapp.disable_remotetests()

    def save(self):
        results = []
        for test in self.runner.tests:
            result = test.get("result", {})
            result["testid"] = test["id"]
            results.append(result)

        log.debug("Saving results: %s", results)
        request = {
            "results": results,
        }
        self._send_server(request, RemoteTestStore.SAVE_PATH)

    @classmethod
    def add_options(cls, parser):
        parser.add_option("--remote-url", default=cls.DEFAULT_REMOTE_URL,
            help="(Remote Test Store) Remote test store service URL.")
        parser.add_option("--username", help="(Remote Test Store) username.")
        parser.add_option("--token", help="(Remote Test Store) token.")

        parser.add_option("--filter-types",
            help="(Remote Test Store) Comma separated list of test types.\n"
                 "Only the test types in the list will be fetched.")
        parser.add_option("--filter-count", type="int",
            default=cls.DEFAULT_COUNT,
            help="(Remote Test Store) Number of tests to fetch.")
        # TODO
        # --filter-path
        # --filter-testsuite

    @classmethod
    def options_to_store_info(cls, options):
        if not options.username:
            return None
        if not options.token:
            raise StoreException("Missing --token parameter")
        return {
            "name": cls.name,
            "remote_url": options.remote_url,
            "username": options.username,
            "token": options.token,
            "types": options.filter_types,
            "count": options.filter_count,
        }
