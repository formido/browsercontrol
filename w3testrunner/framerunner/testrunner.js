/**
 * TestRunner: A test runner for the Browser Tests project.
 *
 * Based on Mozilla TestRunner, itself based on MochiKit TestRunner.
 */

var TestRunner = {};
TestRunner.currentTestId = null;
TestRunner.currentTestURL = ""; // Used by Mochitests
TestRunner._haltTests = false;
TestRunner._timedOut = false;
TestRunner._logBuffer = "";
TestRunner._savedClientMessage = null;
// Urls of all executed tests => true (for detecting duplicate results).
TestRunner._seenTests = {};
// Warning: should be less than the TEST_TIMEOUT constant defined in testrunner/runner.py
TestRunner.timeout = 8; // seconds

TestRunner.logEnabled = true;
TestRunner.logger = new Logger();

// XXX should use MochiKit API to retrieve the logged messages instead.

TestRunner.logger.addListener("logListener", "DEBUG", function(msg) {
  TestRunner._logBuffer += msg.num + " " + msg.level + " " + msg.info.join(' ') + "\n";
});

var gParams = parseQueryString(location.search.substring(1), false);
gParams.session_id = gParams.session_id || "_no_session_id_";

// Dummy method which is called by the WebKit DOM tests if it detects it is running
// in a frame. Will fail otherwise.
function setResult() {
}

/**
 * Creates the iframe that contains a test
 **/
TestRunner._makeIframe = function (url) {
  var iframe = $('testframe');
  iframe.src = url;
  iframe.name = url;
  iframe.width = "500";
  return iframe;
};

TestRunner.runMochiTest = function (serverMessage) {
  TestRunner.log("Running mochitest: " + TestRunner.currentTestId);

  clearTimeout(TestRunner.hangTimeout);
  TestRunner._timedOut = false;
  TestRunner.logger.counter = 0;
  TestRunner.currentTestURL = serverMessage.url;

  TestRunner.hangTimeout = setTimeout(function() {
    TestRunner.log("Hang timeout for test: " + TestRunner.currentTestId);
    TestRunner._timedOut = true;

    var frameWindow = $('testframe').contentWindow.wrappedJSObject ||
                      $('testframe').contentWindow;
    frameWindow.SimpleTest.ok(false, "Test timed out.");
    frameWindow.SimpleTest.finish();

  }, TestRunner.timeout * 1000);

  TestRunner._makeIframe(serverMessage.url);
  TestRunner.log("Iframe src: " + $('testframe').src);
};

TestRunner.runTest = function (serverMessage, doneCallback) {
  TestRunner.log("Handling test " + serverMessage.url)

  var testTimeout = setTimeout(function() {
    TestRunner.log("test timed out (" + serverMessage.url + ")");
    disconnect(connectId);

    doneCallback(true);
  }, TestRunner.timeout * 1000);

  var iframe = TestRunner._makeIframe(serverMessage.url);

  var connectId = connect(iframe, "onload", this, function() {
    disconnect(connectId);
    clearTimeout(testTimeout);
    TestRunner.log("test loaded");

    doneCallback(false);
  });
};

TestRunner.log = function(s) {
  if (!gParams.debug)
    return;
  var messages = $("messages");
  messages.innerHTML += s + "<br/>";
  messages.scrollTop = messages.scrollHeight;
}

TestRunner.handleServerMessage = function(serverMessage) {

  var type = serverMessage.type;

  TestRunner.log("processing server message (type: " + type + ")");

  var fields = ["test_index", "test_count", "percent", "time_elapsed", "time_est_remaining",
                "time_est_total", "test_id", "url"];
  for (var i = 0; i < fields.length; i++) {
    var f = fields[i];
    $("status-" + f).innerHTML = serverMessage[f] || "-";
  }

  if (type == "finished") {
    TestRunner.log("Tests are finished");
    return;
  }

  if (type == "restarting") {
    TestRunner.log("Tests are restarting");
    return;
  }

  if (TestRunner._haltTests) {
    TestRunner.log("Tests are stopped");
    return;
  }

  if (type.search(/^load_/) != -1) {
    if (TestRunner.currentTestId) {
      TestRunner.sendFailClientMessage("Loading a new test (" + serverMessage.test_id +
        ") while previous test (" + TestRunner.currentTestId + ") is not finished");
      return;
    }
    TestRunner.currentTestId = serverMessage.test_id;
  }

  if (type == "load_mochitest") {
    // XXX is the timeout necessary?
    setTimeout(function() {
      TestRunner.runMochiTest(serverMessage);
    }, 100);
    return;
  }

  if (type == "load_layouttest") {
    TestRunner.log("Handling layouttest " + serverMessage.url)

    // TODO: wait a timeout for layouttests that have the flag "ltwait"

    function layouttestDone(timedOut) {
      TestRunner.log("layouttest done. timedOut: " + timedOut);

      var doc = $('testframe').contentWindow.document || $('testframe').contentDocument;

      var elem = doc.body || doc.documentElement;

      var innerText = toInnerText(elem);
      TestRunner.log("inner: " + innerText);

      TestRunner.sendSubmitResultClientMessage({
        text_dump: innerText
      });
    }

    TestRunner.runTest(serverMessage, layouttestDone);
    return;
  }

  if (type == "load_reftest") {
    TestRunner.log("Handling reftest " + serverMessage.url)

    // XXX use a smaller timeout for reftests?

    function reftestDone(timedOut) {
      // In a timeout to let the onload handler finish.
      setTimeout(function() {
        TestRunner.sendSubmitResultClientMessage({});
      }, 100);
    }

    TestRunner.runTest(serverMessage, reftestDone);
    return;
  }

  if (type == "error") {
    var msg = "ERROR: Server reports: " + serverMessage.error_msg;
    TestRunner.log(msg);
    TestRunner._haltTests = true;
    alert(msg);
    return;
  }

  TestRunner.sendFailClientMessage("Error: unknown server message (" + type + ")");
  alert(msg);
}

TestRunner.sendClientMessage = function(clientMessage, force) {

  if (TestRunner._haltTests) {
    TestRunner.log("Tests are stopped, not sending message");
    return;
  }
  clientMessage.session_id = gParams.session_id;

  if (gParams.manual && !force) {
    TestRunner.log("manual mode, not sending message to server");
    TestRunner._savedClientMessage = clientMessage;
    removeElementClass("sendMessage", "invisible");
    return;
  }

  TestRunner.log("=== Sending client message to server (type: " +
                 clientMessage.type + ")===");
  var json = MochiKit.Base.serializeJSON(clientMessage);

  // workaround for bug http://trac.mochikit.com/ticket/313
  // IE does not recognize vertical tab literal "\v", so use the unicode escape.
  json = json.replace(/\u000b/g, "\\u000b");

  // Safari 3 on Windows sometimes get confused when using a relative path here.
  // So use an absolute one.
  var deferred = MochiKit.Async.doXHR("/framerunner/testservice", {
    method: "POST",
    sendContent: json
  });

  deferred.addCallbacks(function(req) {
    var serverMessage = eval("(" + req.responseText + ")");

    TestRunner.handleServerMessage(serverMessage);

  }, function() {
    var msg = "XHR error";
    TestRunner.sendFailClientMessage(msg);
    alert(msg);
  });
}

TestRunner.sendSubmitResultClientMessage = function(submitResultClientMessage) {
  submitResultClientMessage.type = "submit_result";
  submitResultClientMessage.test_id = TestRunner.currentTestId;
  TestRunner.currentTestId = null;
  TestRunner.sendClientMessage(submitResultClientMessage);
}

TestRunner.sendFailClientMessage = function(message) {
  TestRunner.log("Error: " + message);
  var failClientMessage = {
    type: "fail",
    message: message
  };
  TestRunner.sendClientMessage(failClientMessage, true);
  TestRunner._haltTests = true;
}


/**
 * This stub is called by SimpleTest when a test is finished.
 * NOTE: The API uses an argument for the document. It is not used here.
 */
TestRunner.testFinished = function(doc_unused) {
  TestRunner.log("Test finished: " + TestRunner.currentTestId);

  // In manual mode, we can see the same test several times, disable the duplicate check
  if (gParams.manual)
    TestRunner._seenTests = {};

  if (TestRunner._seenTests[TestRunner.currentTestId]) {
    // XXX should it be fatal?
    TestRunner.sendFailClientMessage("multiple testFinished calls for test " + TestRunner.currentTestId)
    return;
  }
  TestRunner._seenTests[TestRunner.currentTestId] = true;

  if (!TestRunner.currentTestId) {
    // XXX should it be fatal?
    TestRunner.sendFailClientMessage("testFinished called without active test")
    return;
  }

  clearTimeout(TestRunner.hangTimeout);

  if (TestRunner.logEnabled)
    TestRunner.logger.debug("SimpleTest finished " + TestRunner.currentTestURL);

  var doc = $('testframe').contentWindow.document || $('testframe').contentDocument;

  var resultCounters = TestRunner.countResults(doc);

  // XXX do not send log if successful?
  var submitResultMessage = {
    pass_count: resultCounters.OK,
    fail_count: resultCounters.notOK,
    todo_count: resultCounters.todo,
    timed_out: TestRunner._timedOut,
    log: TestRunner._logBuffer
  }
  TestRunner._logBuffer = "";

  var msg = (submitResultMessage.fail_count > 0) ? "FAILED " : "PASS ";
  msg += " pass_count: " + submitResultMessage.pass_count +
         " fail_count: " + submitResultMessage.fail_count +
         " todo_count: " + submitResultMessage.todo_count;
  TestRunner.log(msg);

  TestRunner.sendSubmitResultClientMessage(submitResultMessage);
};

/**
 * Get the results.
 */
TestRunner.countResults = function(doc) {
  var nOK = withDocument(doc,
    partial(getElementsByTagAndClassName, 'div', 'test_ok')
  ).length;
  var nNotOK = withDocument(doc,
    partial(getElementsByTagAndClassName, 'div', 'test_not_ok')
  ).length;
  var nTodo = withDocument(doc,
    partial(getElementsByTagAndClassName, 'div', 'test_todo')
  ).length;
  return {"OK": nOK, "notOK": nNotOK, "todo": nTodo};
}


onload = function() {

  connect("wantsUrl", "onclick", function(e) {
    e.preventDefault();
    TestRunner.sendClientMessage({type: "wants_url"}, true);
  });

  connect("loadred", "onclick", function(e) {
    e.preventDefault();
    TestRunner.handleServerMessage({type: "load_reftest", "url": "red.html"})
  });

  connect("abort", "onclick", function(e) {
    e.preventDefault();
    TestRunner.sendFailClientMessage("User aborted tests");
  });

  connect("haltTests", "onclick", function(e) {
    e.preventDefault();
    TestRunner._haltTests = true;
  });

  connect("clear", "onclick", function(e) {
    e.preventDefault();
    $("messages").innerHTML = "";
  });

  connect("sendMessage", "onclick", function(e) {
    e.preventDefault();
    if (!TestRunner._savedClientMessage) {
      alert("No saved client message");
      return;
    }
    TestRunner.sendClientMessage(TestRunner._savedClientMessage, true);
    TestRunner._savedClientMessage = null;
    MochiKit.DOM.addElementClass("sendMessage", "invisible");
  });

  if (gParams.debug)
    MochiKit.DOM.addElementClass("testframe", "small");

  if (!gParams.manual)
    TestRunner.sendClientMessage({type: "wants_url"});

  MochiKit.DOM.addElementClass("sendMessage", "invisible");
}
