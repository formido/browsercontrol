from __future__ import with_statement
import hashlib
import itertools
import logging
import os.path
from os.path import join
import re
import sys
import time
import urlparse

from w3testrunner.teststores.common import TestStore, StoreException

log = logging.getLogger(__name__)

# utility functions

def joinposix(*paths):
    return '/'.join(paths)

class Test(object):
    def __init__(self):
        self._flags = set()
        self.full_id = None

SERVER_URL = "http://localhost:8888/"

class ImportedTest(object):
    TEXT_EXTENSIONS = ["css", "html", "xhtml", "js", "xml", "svg"]

    SRC_HREF_RE = re.compile("(?:src|href)\s*=\s*(?P<quote>[\"'])(?P<url>[^\"']+)(?P=quote)")
    CSS_URL_RE = re.compile("url\(\s*[\"']?(?P<url>[^\"')]+)[\"']?\s*\)")
    CSS_IMPORT_RE = re.compile("@import\s+(?P<quote>[\"'])(?P<url>[^\"']+)(?P=quote)")

    metadata = None
    file_based = True

    def __init__(self, testid):
        self.testid = testid

    def __eq__(self, other):
        """Two tests of different type are equal if they have the same testid.
        The purpose it to avoid having two different tests with the same id in
        the same set even if they have a different type"""
        if not isinstance(other, ImportedTest):
            return False
        return self.testid == other.testid

    def __hash__(self):
        return hash(self.testid)

    def __repr__(self):
        return "<%s %s>" % (self.__class__.__name__, self.testid)

    @classmethod
    def create_from_test(cls, test):
        classname = test.type.capitalize()
        itest_class = sys.modules[__name__].__dict__.get(classname, None)
        assert itest_class, "Can't find class for test type %s" % test.type
        return itest_class.do_create_from_test(test)

    @classmethod
    def do_create_from_test(cls, test):
        itest = cls(test.id)
        return itest

    def get_test(self):
        """Returns a the test from the database with the same identifier.
        Note: The returned test may not be of the same type."""
        return Test.objects.get(pk=self.testid, deleted=False)

    def exists(self):
        raise NotImplementedError()

    def _get_related_resources(self, resource):
        def find_resources(resource):
            full_path = join(self.tests_dir, resource)

            ext = os.path.splitext(resource)[1][1:]
            if not ext in self.TEXT_EXTENSIONS:
                return set()

            content = open(full_path).read()
            iterators = [(m.groupdict()["url"] for m in regex.finditer(content)) for
                            regex in [self.SRC_HREF_RE, self.CSS_URL_RE, self.CSS_IMPORT_RE]]

            found_resources = set()
            base = "/" + os.path.dirname(resource)
            if not base.endswith("/"):
                base += "/"

            for url in itertools.chain(*iterators):
                url = urlparse.urljoin(base, url)
                # Only keep the path from the parsed url.  We check if the file
                # exists on the filesystem in order to crawl that resource.
                path = urlparse.urlparse(url).path[1:]
                if not path or not os.path.isfile(join(self.tests_dir, path)):
                    continue
                found_resources.add(path)
            return found_resources

        tocrawl = set([resource])
        all_resources = set([resource])
        while tocrawl:
            resources = find_resources(tocrawl.pop())
            tocrawl.update(resources - all_resources)
            all_resources.update(resources)

        return all_resources

    def _add_flags(self, test, *args):
        test._flags.update(args)

    def _compute_common_flags(self, test):
        schemes = [urlparse.urlparse(u).scheme for u in test.test_resources]
        if "data" in schemes:
            self._add_flags(test, "dataurl")

        extensions = [os.path.splitext(u)[1][1:] for u in test.test_resources]
        extensions_as_flag = ("svg", "xhtml")
        for ext in extensions_as_flag:
            if ext in extensions:
                self._add_flags(test, ext)

    def _compute_flags(self, test):
        raise NotImplementedError()

    def _compute_moz_flags(self, test):
        extensions = [os.path.splitext(u)[1][1:] for u in test.test_resources]
        if "xul" in extensions:
            self._add_flags(test, "moz", "moz:xul")

        if "netscape.security" in test.resources_text_content or \
           "EventUtils.js" in test.resources_text_content:
            self._add_flags(test, "moz", "moz:security")
        if "Components.interfaces" in test.resources_text_content or \
           "Components.classes" in test.resources_text_content:
            self._add_flags(test, "moz", "moz:prop_objects")

        # XXX not accurate. It should check against the hosts in
        # build/pgo/server-locations.txt
        if "example.org" in test.resources_text_content:
            self._add_flags(test, "proxy")

    def _fixup_test(self, test, path_as_id=None):
        if path_as_id:
            test.id = path_as_id
            test.file = path_as_id

            # XXX not correct for http tests and ssl stuff.
            url = SERVER_URL + path_as_id
            test.url = url

        if not test.full_id:
            test.full_id = test.id

        for r in test.test_resources:
            test.resources.update(self._get_related_resources(r))

        test.resources_content = ""
        test.resources_text_content = ""

        for r in sorted(test.resources):
            res_path = join(self.tests_dir, r)
            if not os.path.exists(res_path):
                continue
            with open(res_path) as f:
                content = f.read()
                test.resources_content += content
                if not os.path.splitext(r)[1][1:] in self.TEXT_EXTENSIONS:
                    continue
                # SimpleTest.js references Mozilla specific objects, but it
                # does not use them if they are not available. So don't include
                # that file in the content scanned for Mozilla specific objects.
                if r == "tests/SimpleTest/SimpleTest.js":
                    continue
                test.resources_text_content += content

        test.hash = hashlib.md5(test.resources_content).hexdigest()
        self._compute_common_flags(test)
        self._compute_flags(test)

        if self.metadata:
            self.metadata.update_test(test)

        # Could be large, so free them now.
        del test.resources_content
        del test.resources_text_content

    @classmethod
    def get_imported_tests(cls, path):
        itest = cls(path)
        if not itest.exists():
            return []
        return [itest]

    @classmethod
    def update_dirty_itests(cls, resource, lines, dirty_itests):
        return False

    def create_test(self):
        raise NotImplementedError()

class Mochitest(ImportedTest):
    def __init__(self, path):
        super(Mochitest, self).__init__(path)
        self.path = path

    def exists(self):
        dir, file = os.path.split(self.path)
        if not os.path.isfile(join(self.tests_dir, self.path)):
            return False

        # from mozilla/testing/mochitest/server.js :: isTest()
        # A bit more restrictive though: filename must start with "test_", not
        # only contain that string.
        return file.startswith("test_") and \
            not ".js" in file and \
            not ".css" in file and \
            not re.search("\^headers\^$", file) and \
            not file.endswith("-expected.txt") # Added this condition
                                               # to skip layouttests.

    def _compute_flags(self, test):
        self._compute_moz_flags(test)

    def create_test(self):
        assert self.exists()
        dir, file = os.path.split(self.path)

        test = Test()
        test.type = "mochitest"
        full_path = join(self.tests_dir, self.path)
        assert os.path.exists(full_path), "path %s does not exist" % full_path

        test.resources = set()
        test.test_resources = set([self.path])
        self._fixup_test(test, path_as_id=self.path)
        return test

# XXX refactor duplicated code with Mochitest.
class Browsertest(ImportedTest):
    def __init__(self, path):
        super(Browsertest, self).__init__(path)
        self.path = path

    def exists(self):
        dir, file = os.path.split(self.path)
        fullpath = join(self.tests_dir, self.path)
        if not os.path.isfile(fullpath):
            return False
        with open(fullpath) as f:
            # XXX hacky way of detecting the Browsertest format.
            if not "/browsertest.js" in f.read():
                return False

        # from mozilla/testing/mochitest/server.js :: isTest()
        # A bit more restrictive though: filename must start with "test_", not
        # only contain that string.
        return file.startswith("test_") and \
            not ".js" in file and \
            not ".css" in file and \
            not re.search("\^headers\^$", file) and \
            not file.endswith("-expected.txt") # Added this condition
                                               # to skip layouttests.

    def _compute_flags(self, test):
        pass

    def create_test(self):
        assert self.exists()
        dir, file = os.path.split(self.path)

        test = Test()
        test.type = "browsertest"
        full_path = join(self.tests_dir, self.path)
        assert os.path.exists(full_path), "path %s does not exist" % full_path

        test.resources = set()
        test.test_resources = set([self.path])
        self._fixup_test(test, path_as_id=self.path)
        return test

class Layouttest(ImportedTest):
    REPLACE_EXT_RE = re.compile("\.[^\.]*$")
    LTC_CALLS_RE = re.compile("layoutTestController\.(\w+)")

    def __init__(self, path):
        super(Layouttest, self).__init__(path)
        self.path = path

    def _pre_create_test(self):
        dir, file = os.path.split(self.path)

        # From run-webkit-tests, $fileFilter function (and below for svg)
        ALLOWED_EXTS = ("html", "shtml", "xml", "xhtml", "pl", "php", "svg")
        ext = os.path.splitext(file)[1]
        if not ext or not ext[1:] in ALLOWED_EXTS:
            return None

        expected_file = self.REPLACE_EXT_RE.sub("", file)
        expected_file += "-expected.txt"
        expected_path = joinposix(dir, expected_file) if dir else expected_file

        if not os.path.isfile(join(self.tests_dir, expected_path)):
            return None

        test = Test()
        test.type = "layouttest"
        test.expected_path = expected_path

        full_path = join(self.tests_dir, self.path)
        assert os.path.exists(full_path), "path %s does not exist" % full_path

        exp_content = open(join(self.tests_dir, expected_path)).read()
        # Save this on the test for use in _compute_flags
        test.exp_content = exp_content

        # See run-webkit-tests::isTextOnlyTest()
        if exp_content.startswith("layer at"):
            return None

        return test

    def exists(self):
        if not os.path.isfile(join(self.tests_dir, self.path)):
            return False

        test = self._pre_create_test()
        return test != None

    def _compute_flags(self, test):
        if "CONSOLE MESSAGE:" in test.exp_content or "ALERT:" in test.exp_content:
            self._add_flags(test, "ltmessages")

        # TODO: replace this code by a flag set in the metadata file

        ## XXX should not be path specific
        #WEBKIT_FILE_PREFIX = "/WebKit/LayoutTests/"
        #
        #use_wk_http = use_wk_ssl = False
        ## Keep in sync with run-webkit-tests, around line 555
        #if test_file.startswith(WEBKIT_FILE_PREFIX + "http"):
        #    if not test_file.startswith(WEBKIT_FILE_PREFIX + "http/tests/local/") and \
        #       not test_file.startswith(WEBKIT_FILE_PREFIX + "http/tests/ssl/") and \
        #       not test_file.startswith(WEBKIT_FILE_PREFIX + "http/tests/media/"):
        #        use_wk_http = True
        #    elif test_file.startswith(WEBKIT_FILE_PREFIX + "http/tests/ssl/"):
        #        use_wk_ssl = True
        #if use_wk_http or use_wk_http:
        #    test.flags_set.add("layouttesthttp")
        #
        #url = self.server_url + test_file
        #url_for_fetch = url
        #if use_wk_http:
        #    url = "http://127.0.0.1:8000" + \
        #         test_file.replace(WEBKIT_FILE_PREFIX + "http", "")
        #elif use_wk_ssl:
        #    url = "http://127.0.0.1:8443" + \
        #         test_file.replace(WEBKIT_FILE_PREFIX + "http", "")
        #log.debug("url: %s", url)

        funcs = set(self.LTC_CALLS_RE.findall(test.resources_text_content))
        unprivilegedFuncs = set(["dumpAsText", "waitUntilDone", "notifyDone"])

        if "waitUntilDone" in funcs:
            self._add_flags(test, "ltwait")
        privilegedFuncs = funcs - unprivilegedFuncs
        if privilegedFuncs:
            self._add_flags(test, "layouttests")
            # TODO: save this for capability testing
            #test.pfuncs = privilegedFuncs

        # XXX \b not working?
        if re.search("\Walert\(|\Wprompt\(|\Wconfirm\(", test.resources_text_content):
            self._add_flags(test, "ltalert")

        del test.exp_content

    def create_test(self):
        assert self.exists()
        test = self._pre_create_test()
        dir, file = os.path.split(self.path)

        test.resources = set([test.expected_path])
        test.test_resources = set([self.path])
        self._fixup_test(test, path_as_id=self.path)
        return test

class Reftest(ImportedTest):
    file_based = False
    hash_id = True

    def __init__(self, testid, full_id):
        super(Reftest, self).__init__(testid)
        self.full_id = full_id

    @classmethod
    def do_create_from_test(cls, test):
        return cls(test.pk, test.full_id)

    def exists(self):
        assert self.file_based, "Should only called for file based tests"

    @classmethod
    def _build_testid(cls, manifest_path, line, use_hash=True):
        if not cls.hash_id:
            use_hash = False
        dir, file = os.path.split(manifest_path)
        paths = ["reftest:%s" % (hashlib.md5(line).hexdigest() if use_hash
                                 else line)]
        if dir:
            paths.insert(0, dir)
        return joinposix(*paths)

    @classmethod
    def _build_full_id(cls, manifest_path, line):
        return cls._build_testid(manifest_path, line, False)

    @classmethod
    def _line_to_itest(cls, manifest_path, line, path="", line_no=-1):
        if not line or line[0] == "#":
            return None
        line = re.sub("\s+#.*$", "", line)
        # strip leading and trailing whitespace
        line = line.strip()
        if not line:
            return None
        if not cls._parse_line(line, path, line_no):
            return None

        dir, file = os.path.split(manifest_path)
        testid = cls._build_testid(manifest_path, line)
        full_id = cls._build_full_id(manifest_path, line)
        itest = Reftest(testid, full_id)
        # The following attributes are temporary, not persisted in the database
        # object.  They will be used in create_test() for creating the db object.
        itest.line = line
        itest.line_no = line_no
        itest.directory = dir
        return itest

    # More or less direct port of Mozilla reftest.js::ReadManifest() in Python
    @classmethod
    def _parse_line(cls, line, path="", line_no=-1):
        EXPECTED_PASS = 0;
        EXPECTED_FAIL = 1;
        EXPECTED_RANDOM = 2;
        EXPECTED_DEATH = 3;  # test must be skipped to avoid e.g. crash/hang
        EXPECTED_LOAD = 4; # test without a reference (just test that it does
                           # not assert, crash, hang, or leak)
        urls = []
        #log.debug("reftest parsing line %s", line)

        ##for (line_no, line) in enumerate(open(f)):
        ##line_no += 1
        #assert line[0] != "#"
        #
        #line = re.sub("\s+#.*$", "", line)
        #
        ## strip leading and trailing whitespace
        #line = line.strip()
        #assert line

        items = line.split() # split on whitespace
        #print "line", line

        expected_status = EXPECTED_PASS;

        failure_types = "";
        while re.match("^(fails|random|skip|asserts)", items[0]):
            # XXX this store a failure_types for asserts.
            failure_types += " " + items[0]
            item = items.pop(0)
            stat = ""
            cond = False
            m = re.match("^(fails|random|skip)-if(\(.*\))$", item)
            if m:
                stat = m.group(1)
#                // Note: m[2] contains the parentheses, and we want them.
#                cond = Components.utils.evalInSandbox(m[2], sandbox);
                cond = False # XXX
            elif re.match("^(fails|random|skip)$", item):
                stat = item
                cond = True
            elif re.match("^asserts\((\d+)(-\d+)?\)$", item):
                cond = False
                # XXX asserts are ignored for now
            elif re.match("^asserts-if\((.*?),(\d+)(-\d+)?\)$", item):
                cond = False
                # XXX asserts are ignored for now
            else:
                raise Exception("Error in manifest file %s line %i" %
                                (path, line_no))

#            // XXX expected_status not yet implemented
#            if (!gIsExtractingTests)
#            if (cond) {
#                if (stat == "fails") {
#                    expected_status = EXPECTED_FAIL;
#                } else if (stat == "random") {
#                    expected_status = EXPECTED_RANDOM;
#                } else if (stat == "skip") {
#                    expected_status = EXPECTED_DEATH;
#                }
#            }
#        }
#
        run_http = items[0] == "HTTP"
        if run_http:
            items.pop(0)

        # TODO: v2
        run_http = False
        http_depth = None
        if items[0] == "HTTP":
            run_http = True
            http_depth = 0
            items.pop(0)
        elif re.match("HTTP\(\.\.(\/\.\.)*\)", items[0]):
            # Accept HTTP(..), HTTP(../..), HTTP(../../..), etc.
            run_http = True
            http_depth = (len(items[0]) - 5) / 3
            items.pop(0)

        # XXX do something with http_depth
        # XXX commented .js code below is not up to date.

        def uri_to_file(uri):
            return re.sub("[\?#].*$", "", uri)

        if items[0] == "include":
            if len(items) != 2 or run_http:
                raise Exception("Error in manifest file %s line %i" %
                                (path, line_no))
            log.debug("include statement ignored (%s)", line)
            # XXX add an exception for this file that is named reftests.list instead
            #  of reftest.list. Should be Mozilla specific and is not included now.
            if items[1] == "../../content/html/document/reftests/reftests.list":
                return None
            assert items[1].endswith("/reftest.list"), (
                     "Including a reftest manifest file that will not be "
                     "found (%s)") % items[1]
#            var incURI = gIOService.newURI(items[1], null, listURL);
#            secMan.checkLoadURI(aURL, incURI,
#                                CI.nsIScriptSecurityManager.DISALLOW_SCRIPT);
#            ReadManifest(incURI);
        elif items[0] == "load":
            if expected_status == EXPECTED_PASS:
                expected_status = EXPECTED_LOAD
            if len(items) != 2 or \
                (expected_status != EXPECTED_LOAD and \
                 expected_status != EXPECTED_DEATH):
                raise Exception("Error in manifest file %s line %i" %
                                (path, line_no))
#            var [testURI] = runHttp
#                            ? ServeFiles(aURL,
#                                         listURL.file.parent, [items[1]])
#                            : [gIOService.newURI(items[1], null, listURL)];
            test_uri = items[1]
#            var prettyPath = runHttp
#                           ? gIOService.newURI(items[1], null, listURL).spec
#                           : testURI.spec;
#            secMan.checkLoadURI(aURL, testURI,
#                                CI.nsIScriptSecurityManager.DISALLOW_SCRIPT);
#            gURLs.push( { equal: true /* meaningless */,
#                          expected: expected_status,
#                          prettyPath: prettyPath,
#                          prettyPath2: null,
#                          url: testURI,
#                          url2: null,
#                          failureTypes: failureTypes } );

            return {"equal": True, # meaningless
                    "expected": expected_status,
                    # XXX not yet implemented
                    "run_http": run_http,
                    #"prettyPath": prettyPath,
                    #"prettyPath2": null,
                    "url": test_uri,
                    "url2": "",
                    "file": uri_to_file(test_uri),
                    "file2": "",
                    "failure_types": failure_types}

        elif items[0] == "==" or items[0] == "!=":
            if len(items) != 3:
                raise Exception("Error in manifest file %s line %i" %
                                (path, line_no))
#            var [testURI, refURI] = runHttp
#                                  ? ServeFiles(aURL,
#                                               listURL.file.parent, [items[1], items[2]])
#                                  : [gIOService.newURI(items[1], null, listURL),
#                                     gIOService.newURI(items[2], null, listURL)];
            (test_uri, ref_uri) = (items[1], items[2])
#            var prettyPath = runHttp
#                           ? gIOService.newURI(items[1], null, listURL).spec
#                           : testURI.spec;
#            var prettyPath2 = runHttp
#                           ? gIOService.newURI(items[2], null, listURL).spec
#                           : refURI.spec;
#            secMan.checkLoadURI(aURL, testURI,
#                                CI.nsIScriptSecurityManager.DISALLOW_SCRIPT);
#            secMan.checkLoadURI(aURL, refURI,
#                                CI.nsIScriptSecurityManager.DISALLOW_SCRIPT);
#            gURLs.push( { equal: (items[0] == "=="),
#                          expected: expected_status,
#                          prettyPath: prettyPath,
#                          prettyPath2: prettyPath2,
#                          url: testURI,
#                          url2: refURI,
#                          failureTypes: failureTypes } );
            return {"equal": (items[0] == "=="),
                         "expected": expected_status,
                         # XXX not yet implemented
                         "run_http": run_http,
                         #"prettyPath": prettyPath,
                         #"prettyPath2": prettyPath2,
                         "url": test_uri,
                         "url2": ref_uri,
                         "file": uri_to_file(test_uri),
                         "file2": uri_to_file(ref_uri),
                         "failure_types": failure_types }
        else:
            raise Exception("Error parsing manifest file %s line %s: '%s'" %
                            (path, line_no, line))

    @classmethod
    def update_dirty_itests(cls, resource, lines, dirty_itests):
        dir, file = os.path.split(resource)
        if file != "reftest.list":
            return False

        for line in lines:
            if not line[0] in ("-", "+"):
                continue
            itest = cls._line_to_itest(resource, line[1:])
            if not itest:
                continue
            kind = ("added" if line[0] == "+" else "deleted")
            dirty_itests[kind].add(itest)

        # remove intersection, could happen with whitespace changes
        intersection = dirty_itests["added"] & dirty_itests["deleted"]
        dirty_itests["added"] -= intersection
        dirty_itests["deleted"] -= intersection

        return True

    @classmethod
    def get_imported_tests(cls, path):
        dir, file = os.path.split(path)
        if file != "reftest.list":
            return []

        itests = set()
        with open(join(cls.tests_dir, path)) as f:
            for (line_no, line) in enumerate(f):
                line_no += 1
                itest = cls._line_to_itest(path, line, path, line_no)
                if not itest:
                    continue
                itests.add(itest)
        return itests

    def _compute_flags(self, test):
        self._compute_moz_flags(test)

        if test.failure_type:
            self._add_flags(test, "rthasfailuretype")
        if not test.url2:
            self._add_flags(test, "rtloadonly")
        if "reftest-print" in test.resources_text_content:
            self._add_flags(test, "rtprint")
        if "reftest-wait" in test.resources_text_content:
            self._add_flags(test, "rtwait")

    def _is_special_scheme(self, url):
        return url.startswith("data:") or url.startswith("about:")

    def create_test(self):
        test = Test()
        test.type = "reftest"
        # This requires that this test was creating using _line_to_itest.
        # That should always the case in the current implementation.
        assert self.line, "Invalid state!"

        reftest = self._parse_line(self.line, self.line_no)

        for prop_url in ("url", "url2"):
            u = reftest[prop_url]
            if not u or self._is_special_scheme(u):
                continue
            reftest[prop_url] = SERVER_URL + \
                ((self.directory + "/") if self.directory else "") + u
        for prop_file in ("file", "file2"):
            f = reftest[prop_file]
            reftest[prop_file] = ""
            if not f or self._is_special_scheme(f):
                continue
            # posix style because it is stored in db
            if self.directory:
                reftest[prop_file] = joinposix(self.directory, f)
            else:
                reftest[prop_file] = f
            assert os.path.isfile(join(self.tests_dir, reftest[prop_file])), \
                    "Reftest manifest in directory '%s' references non existing file %s" % \
                    (self.directory, f)

        test.url = reftest["url"]
        test.url2 = reftest["url2"]
        test.file = reftest["file"]
        test.file2 = reftest["file2"]

        test.equal = reftest["equal"]
        test.expected = reftest["expected"]
        # XXX not yet implemented
        # XXX should it be failure_type*s* ???
        test.failure_type = reftest["failure_types"]

        # XXX detect reftest that require http server
        ##url = self.importer_manager.SERVER_URL + path
        #test.file = path

        test.id = self.testid
        test.full_id = self.full_id

        # XXX should use self.line here instead?
        test.resources = set([self.testid])
        test.test_resources = set()
        test.test_resources.add(test.file if test.file else test.url)
        if test.file2:
            test.test_resources.add(test.file2)
        elif test.url2:
            test.test_resources.add(test.url2)

        self._fixup_test(test)

        return test

class TestsExtractor(object):
    IGNORED_PATHS_RE = re.compile(r"(^|[/\\])(\..*|CVS|\.svn)($|[/\\])")

    def __init__(self, tests_dir=None):
        # The order of importers is important. In case of ambiguity, the first
        # importer that could locate a test will win.
        self.importers = [Browsertest, Layouttest, Mochitest, Reftest]
        self.tests_dir = tests_dir

    def _toposixpath(self, path):
        """
        Converts a path to POSIX style (forward slashes).
        All paths are stored with this style in the database to be OS independent.
        """
        return joinposix(*path.split(os.sep))

    def _is_ignored(self, path):
        IGNORED_RESOURCES = ("metadata.txt", "import_state.pickle")
        if path in IGNORED_RESOURCES:
            return True
        return self.IGNORED_PATHS_RE.search(path) != None

    def get_imported_tests_and_resources(self, directory):
        # YYY assume self.tests_dir == directory?
        #ImportedTest.tests_dir = self.tests_dir
        ImportedTest.tests_dir = directory

        imported_tests = set()
        resources = set()
        for root, dirs, files in os.walk(directory):
            toremove = []
            for d in dirs:
                if self._is_ignored(d):
                    toremove.append(d)
            for d in toremove:
                dirs.remove(d)

            # XXX not supported now because incremental checking won't read that file
            # XXX TODO: put a toplevel importignore.txt for this maybe
            #ignorefile = os.path.join(root, "importignore.txt")
            #if os.path.exists(ignorefile):
            #    for ignored_dir in open(ignorefile):
            #        ignored_dir = ignored_dir.strip()
            #        if ignored_dir in dirs:
            #            dirs.remove(ignored_dir)

            cur_dir = root[len(self.tests_dir) + 1:]
            cur_dir = self._toposixpath(cur_dir)
            for file in files:
                path = joinposix(cur_dir, file) if cur_dir else file
                if self._is_ignored(path):
                    continue
                resources.add(path)
                for importer in self.importers:
                    itests = importer.get_imported_tests(path)
                    if itests:
                        imported_tests.update(itests)
                        break
        return (imported_tests, resources)

    def get_imported_tests(self, directory):
        return self.get_imported_tests_and_resources(directory)[0]

class LocalTestStore(TestStore):
    name = "local"

    def __init__(self, runner, store_info):
        super(LocalTestStore, self).__init__(runner, store_info)
        self.tests_path = store_info["path"]
        # tests_path shouldn't contain a trailing slash.
        self.tests_path = self.tests_path.strip().rstrip("\\/")

    def load(self):
        if not os.path.exists(self.tests_path):
            raise StoreException("Tests path '%s' does not exist" %
                                   self.tests_path)

        testsextractor = TestsExtractor(tests_dir=self.tests_path)
        # TODO: support importing subdirectories
        itests = testsextractor.get_imported_tests(self.tests_path)

        props = [
            "id", "full_id", "type", "url", "file",
            # reftests
            "equal", "expected", "failure_type", "url2", "file2"
        ]
        tests = []
        for itest in itests:
            test_obj = {}
            test = itest.create_test()
            # Ignore layouttests for now.
            if test.type == "layouttest":
                continue
            for p in props:
                test_obj[p] = getattr(test, p, None)
            tests.append(test_obj)

        self.runner.webapp.enable_localtests(self.tests_path)
        return tests

    def cleanup(self):
        self.runner.webapp.disable_localtests()

    def save(self):
        log.info("Test results:")
        statuses = []
        for t in self.runner.tests:
            status = "not-run"
            if "result" in t:
                status = t["result"]["status"]
            log.info("Test: %s, result: %s", t["id"], status)
            statuses.append(status)
        for k, g in itertools.groupby(sorted(statuses)):
            log.info("    %s: %s", k, len(list(g)))

    @classmethod
    def add_options(cls, parser):
        parser.add_option("--tests-path",
            help="Path to the tests to load")

    @classmethod
    def options_to_store_info(cls, options):
        if not options.tests_path:
            return None
        return {
            "name": "local",
            "path": options.tests_path,
        }
