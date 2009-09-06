/**
 * TestRunner: A test runner for SimpleTest
 * TODO:
 *
 *  * Avoid moving iframes: That causes reloads on mozilla and opera.
 *
 *
**/
var TestRunner = {};
TestRunner.logEnabled = false;
TestRunner._currentTest = 0;
TestRunner.currentTestURL = "";
TestRunner._tests = [];

TestRunner.timeout = 5 * 60 * 1000; // 5 minutes.
TestRunner.maxTimeouts = 4; // halt testing after too many timeouts

/**
 * Make sure the tests don't hang indefinitely.
**/
TestRunner._numTimeouts = 0;
TestRunner._currentTestStartTime = new Date().valueOf();

TestRunner._checkForHangs = function() {
  if (TestRunner._currentTest < TestRunner._tests.length) {
    var runtime = new Date().valueOf() - TestRunner._currentTestStartTime;
    if (runtime >= TestRunner.timeout) {
      var frameWindow = $('testframe').contentWindow.wrappedJSObject ||
                          $('testframe').contentWindow;
      frameWindow.SimpleTest.ok(false, "Test timed out.");

      // If we have too many timeouts, give up. We don't want to wait hours
      // for results if some bug causes lots of tests to time out.
      if (++TestRunner._numTimeouts >= TestRunner.maxTimeouts) {
        TestRunner._haltTests = true;

        TestRunner.currentTestURL = "(SimpleTest/TestRunner.js)";
        frameWindow.SimpleTest.ok(false, TestRunner.maxTimeouts + " test timeouts, giving up.");
        var skippedTests = TestRunner._tests.length - TestRunner._currentTest;
        frameWindow.SimpleTest.ok(false, "Skipping " + skippedTests + " remaining tests.");
      }

      frameWindow.SimpleTest.finish();

      if (TestRunner._haltTests)
        return;
    }

    TestRunner.deferred = callLater(30, TestRunner._checkForHangs);
  }
}

/**
 * This function is called after generating the summary.
**/
TestRunner.onComplete = null;

/**
 * If logEnabled is true, this is the logger that will be used.
**/
TestRunner.logger = MochiKit.Logging.logger;

/**
 * Toggle element visibility
**/
TestRunner._toggle = function(el) {
    if (el.className == "noshow") {
        el.className = "";
        el.style.cssText = "";
    } else {
        el.className = "noshow";
        el.style.cssText = "width:0px; height:0px; border:0px;";
    }
};


/**
 * Creates the iframe that contains a test
**/
TestRunner._makeIframe = function (url, retry) {
    var iframe = $('testframe');
    /* Doesn't work as expected on IE
    if (url != "about:blank" &&
        (("hasFocus" in document && !document.hasFocus()) ||
         ("activeElement" in document && document.activeElement != iframe))) {
        // typically calling ourselves from setTimeout is sufficient
        // but we'll try focus() just in case that's needed
        window.focus();
        iframe.focus();
        if (retry < 3) {
            window.setTimeout('TestRunner._makeIframe("'+url+'", '+(retry+1)+')', 1000);
            return;
        }

        if (TestRunner.logEnabled) {
            TestRunner.logger.log("Error: Unable to restore focus, expect failures and timeouts.");
        }
    }
    window.scrollTo(0, $('indicator').offsetTop);
    */
    iframe.src = url;
    iframe.name = url;
    iframe.width = "500";
    return iframe;
};

/**
 * TestRunner entry point.
 *
 * The arguments are the URLs of the test to be ran.
 *
**/
TestRunner.runTests = function (tests) {
    if (TestRunner.logEnabled)
        TestRunner.logger.log("SimpleTest START");

    TestRunner._tests = tests;

    $('testframe').src="";
    TestRunner._checkForHangs();
    window.focus();
    $('testframe').focus();
    TestRunner.runNextTest();
};

TestRunner._stopAndShowFailure = function(message) {
  TestRunner._haltTests = true;
  TestRunner.runNextTest();

  var indicator = $("indicator");
  indicator.innerHTML = "Harness Failure: " + message;
  indicator.style.backgroundColor = "#FFA500";
}

var currentReftest = null;
var currentReftestState = 0;
var reftestScreenshot1Id = -1;
var lastTestResults = null;
var reftestStates = [
  "loadUrl1",
  "takeScreenshot1",
  "loadUrl2",
  "takeScreenshot2AndCompare",
  "testFinished"
];

TestRunner.handleReftest = function() {
  function loadUrl(url, callback) {
    var iframe = TestRunner._makeIframe(url, 0);

    var connectId = connect(iframe, "onload", this, function() {
      disconnect(connectId);
      log("reftest url loaded");
      TestRunner.handleReftest();
    });
  }

  log("TestRunner.handleReftest", currentReftestState,
      reftestStates[currentReftestState]);
  switch (reftestStates[currentReftestState]) {
    case "loadUrl1":
      loadUrl(currentReftest.url);

      break;
    case "takeScreenshot1":
      sendMessage({
        type: "take_screenshot1"
      }, function(serverMessage) {
        TestRunner.handleReftest(serverMessage);
      });

      break;
    case "loadUrl2":
      var serverMessage = arguments[0];
      reftestScreenshot1Id = serverMessage.screenshot1_id;

      loadUrl(currentReftest.url2);
      break;
    case "takeScreenshot2AndCompare":
      sendMessage({
        type: "take_screenshot2_and_compare",
        screenshot1_id: reftestScreenshot1Id,
        save_images: currentReftest.equal ? "if_pixel_diff_gt_0" : "if_pixel_diff_eq_0"
      }, function(serverMessage) {
        TestRunner.handleReftest(serverMessage);
      });

      break;
    case "testFinished":
      var serverMessage = arguments[0];
      var equal = serverMessage.pixel_diff == 0;

      var testPassed = (equal == currentReftest.equal);
      log("test status: ", testPassed);

      currentReftest = null;
      currentReftestState = 0;
      reftestScreenshot1Id = -1;

      lastTestResults = {
        "OK": testPassed ? 1 : 0,
        "notOK": testPassed ? 0 : 1,
        "todo": 0,
        "imagesPath": serverMessage.images_path
      };

      // return to avoid incrementing the state counter.
      return TestRunner.testFinished();
  }
  currentReftestState++;
};

TestRunner.runTest = function(test) {
  if (test.type == "mochitest") {
    var url = TestRunner._tests[TestRunner._currentTest].testURL;
    TestRunner._makeIframe(url, 0);

  } else if (test.type == "reftest") {
    currentReftest = test;
    currentReftestState = 0;
    TestRunner.handleReftest();

  } else {
    TestRunner._stopAndShowFailure("Unknown test type: " + test.type);
  }
};

/**
 * Run the next test. If no test remains, calls onComplete().
 **/
TestRunner._haltTests = false;
TestRunner.runNextTest = function() {
    if (TestRunner._currentTest < TestRunner._tests.length &&
        !TestRunner._haltTests)
    {
        var test = TestRunner._tests[TestRunner._currentTest];
        var url = test.testURL;
        TestRunner.currentTestURL = url;

        $("current-test-path").innerHTML = url;

        TestRunner._currentTestStartTime = new Date().valueOf();

        if (TestRunner.logEnabled)
            TestRunner.logger.log("Running " + url + "...");

        TestRunner.runTest(test);
    } else {
        $("current-test").innerHTML = "<b>Finished</b>";
        TestRunner._makeIframe("about:blank", 0);

        if (parseInt($("pass-count").innerHTML) == 0 &&
            parseInt($("fail-count").innerHTML) == 0 &&
            parseInt($("todo-count").innerHTML) == 0)
        {
          // No |$('testframe').contentWindow|, so manually update: ...
          // ... the log,
          if (TestRunner.logEnabled)
            TestRunner.logger.error("TEST-UNEXPECTED-FAIL | (SimpleTest/TestRunner.js) | No checks actually run.");
          // ... the count,
          $("fail-count").innerHTML = 1;
          // ... the indicator.
          var indicator = $("indicator");
          indicator.innerHTML = "Status: Fail (No checks actually run)";
          indicator.style.backgroundColor = "red";
        }

        if (TestRunner.logEnabled) {
            TestRunner.logger.log("Passed: " + $("pass-count").innerHTML);
            TestRunner.logger.log("Failed: " + $("fail-count").innerHTML);
            TestRunner.logger.log("Todo:   " + $("todo-count").innerHTML);
            TestRunner.logger.log("SimpleTest FINISHED");
        }

        if (TestRunner.onComplete)
            TestRunner.onComplete();
    }
};

/**
 * This stub is called by SimpleTest when a test is finished.
**/
TestRunner.testFinished = function(doc) {
    if (TestRunner.logEnabled)
        TestRunner.logger.debug("SimpleTest finished " +
                                TestRunner._tests[TestRunner._currentTest].testURL);

    TestRunner.updateUI();
    TestRunner._currentTest++;
    TestRunner.runNextTest();
};

/**
 * Get the results.
 */
TestRunner.countResults = function(doc) {
  if (lastTestResults) {
    var results = lastTestResults;
    lastTestResults = null;
    return results;
  }
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

TestRunner.updateUI = function() {
  var results = TestRunner.countResults($('testframe').contentDocument);
  var passCount = parseInt($("pass-count").innerHTML) + results.OK;
  var failCount = parseInt($("fail-count").innerHTML) + results.notOK;
  var todoCount = parseInt($("todo-count").innerHTML) + results.todo;
  $("pass-count").innerHTML = passCount;
  $("fail-count").innerHTML = failCount;
  $("todo-count").innerHTML = todoCount;

  // Set the top Green/Red bar
  var indicator = $("indicator");
  if (failCount > 0) {
    indicator.innerHTML = "Status: Fail";
    indicator.style.backgroundColor = "red";
  } else if (passCount > 0) {
    indicator.innerHTML = "Status: Pass";
    indicator.style.backgroundColor = "#0d0";
  } else {
    indicator.innerHTML = "Status: ToDo";
    indicator.style.backgroundColor = "orange";
  }

  // Set the table values
  var trID = "tr-" + $('current-test-path').innerHTML;
  var row = $(trID);
  var tds = row.getElementsByTagName("td");
  tds[0].style.backgroundColor = "#0d0";
  tds[0].innerHTML = results.OK;
  tds[1].style.backgroundColor = results.notOK > 0 ? "red" : "#0d0";
  tds[1].innerHTML = results.notOK;
  tds[2].style.backgroundColor = results.todo > 0 ? "orange" : "#0d0";
  tds[2].innerHTML = results.todo;

  if (results.imagesPath) {
    tds[3].style.visibility = "visible";
    var imgLinks = tds[3].getElementsByTagName("a");

    function createOpenImageClosure(imageName) {
      return function(e) {
        e.preventDefault();
        $('image-viewer').src = "/reftest_results/" + results.imagesPath +
                                "/" + imageName + ".png";
        $('image-viewer-container').style.display = "block";
      }
    }
    connect(imgLinks[0], "onclick", this, createOpenImageClosure("image1"));
    connect(imgLinks[1], "onclick", this, createOpenImageClosure("image2"));
    connect(imgLinks[2], "onclick", this, createOpenImageClosure("imagediff"));
  }
}
