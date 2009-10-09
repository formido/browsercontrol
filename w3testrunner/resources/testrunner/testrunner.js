var Utils = {
  fixupImageUrl: function(url) {
    // See http://support.microsoft.com/kb/208427
    var MAX_IE_URL_LENGTH = 2083;

    if (jQuery.browser.msie && url.length > MAX_IE_URL_LENGTH) {
      $.ajax({
        async: false,
        type: "POST",
        url: "/imagestore/put",
        data: url,
        success: function(msg) {
          url = "/imagestore/get/" + msg;
        },
        error: function(xhr, textStatus, errorThrown) {
          alert("XMLHttpRequest error when calling /imagestore." +
                " status: " + xhr.status +
                " statusText: " + xhr.statusText +
                " responseText: " + xhr.responseText);
        }
      });
    }

    return url;
  }
};

function LOG() {
  if (!window.console || !console.log || +console.log.apply)
    return;
  try {
    console.log.apply("", arguments);
  } catch (e) {
    // Safari throws when calling console.log.apply.
    var str = "";
    for (var i = 0; i < arguments.length; i++) {
      str += arguments[i] + " ";
    }
    console.log(str);
  }
};

var TR;
var TestRunner = TR = {
  _state: {},
  _statusMessage: "",
  _counters: null,
  _currentTestIndex: -1,

  _params: {},
  // Keep this in sync with the statuses in runner.py, order matters.
  _statusStrings: ["NEEDS_TESTS", "RUNNING", "FINISHED", "STOPPED", "ERROR"],
  _statuses: {},

  rpc: function(method, params, success, sync) {
    LOG("Sending RPC message", method, params);
    LOG("Current state: ", this._state && this._state.status);
    var ignoreError = false;
    if (this._state && this._state.status == ERROR) {
      if (jQuery.inArray(method, ["reset", "load_tests", "get_state",
                                  "suspend_timer", "set_status"]) == -1) {
        console.info("RPC method " + method + " blocked because of ERROR " +
                     "status");
        return;
      }
      ignoreError = true;
      // TODO: show in UI that the method was blocked?
    }

    $.jsonRpc({
      type: 'POST',
      url: '/rpc',
      async: !sync,
      method: method,
      params: params,
      success: function(msg, textStatus) {
        if (msg.error) {
          if (ignoreError)
            return;
          var message = "Server-side RPC Error: " + msg.error.type + " " +
                        msg.error.message;
          LOG("Got an error from server: " + message);
          TR.setStatus(ERROR, message, true);
          return;
        }
        LOG("Got message:", msg.result);

        if (success)
          success.call(TR, msg.result);
      },
      error: function(xhr, textStatus, errorThrown) {
        if (ignoreError)
          return;
        TR.onClientError("XMLHttpRequest error when calling /rpc." +
                         " status: " + xhr.status +
                         " statusText: " + xhr.statusText +
                         " responseText: " + xhr.responseText);
      }
    });
  },

  assert: function(value, message) {
    if (!value)
      this.onClientError("Assertion failure: " + message);
  },

  init: function() {
    var pairs = document.location.search.substring(1).split('&');
    for (var i = 0; i < pairs.length; i++) {
      if (!pairs[i])
        continue;
      var pair = pairs[i].split('=');
      if (pair[1] === undefined)
        pair[1] = "1";
      this._params[pair[0]] = unescape(pair[1]);
    }

    for (var i = 0; i < this._statusStrings.length; i++) {
      var statusString = this._statusStrings[i];
      this._statuses[statusString] = i;
      // Handy shortcuts
      window[statusString] = i;
    }

    $("#testframe").attr("src", "about:blank");

    $(".messageBox").prepend("<div class='closeBox'>&#x2613; Close</div>")
                    .children(".closeBox")
                    .click(function() {
                      $(this).parent(".messageBox").hide();
                    });

    // Main page buttons

    $("#startButton").click(function() {
      if (!TR.canRunTests())
        return;
      TR.setStatus(RUNNING, "Started from Web Page");
      TR.runAllTests();
    });
    $("#stopButton").click(function() {
      if (TR._state.status == STOPPED)
        return;
      TR.setStatus(STOPPED, "Stopped from Web Page");
      TR.stopTests();
      TR.updateUI();
    });
    $("#loadTestsButton").click(function() {
      TR.showBox("#loadTestsBox");
    });
    $("#saveResultsButton").click(function() {
      $("#viewSaveResultsCompletedMessage").hide();
      TR.showBox("#viewSaveResults");
    });
    $("#clearResultsButton").click(function() {
      for (var i = 0; i < TR._state.tests.length; i++) {
        var test = TR._state.tests[i];
        delete test.result;
      }
      TR._counters = null;
      TR.rpc("clear_results", [], function() {
        this.loadState();
      });
    });
    $("#resetButton").click(function() {
      TR.rpc("reset", [], function() {
        this.loadState();
      });
    });

    // loadTests Box

    $("#loadLocalTestsButton").click(function() {
      $("#loadTestsError").hide().text("");
      var testsPath = $("#testsPath").val();

      var storeInfo = {
        name: "local",
        path: testsPath
      };
      TR.rpc("load_tests", [storeInfo], function(msg) {
        LOG("Got results " + msg);
        if (msg.success) {
          $("#loadTestsBox").hide();
          try {
            localStorage.W3TestRunnerLastTestsPath = testsPath;
          } catch(e) { }
          TR.loadState();
          return;
        }
        $("#loadTestsError").text(msg.message || "Failed to load tests, unknown Error").show();
      });
    });
    $("#testsPath").keypress(function(e) {
      if (e.keyCode == 13)
        $("#loadLocalTestsButton").click();
    });
    try {
      $("#testsPath").val(localStorage.W3TestRunnerLastTestsPath);
    } catch(e) { }

    this.loadState();
  },

  showBox: function(boxId) {
    $(".messageBox").hide();
    window.scrollTo(0, 0);
    $(boxId).show();
  },

  canRunTests: function() {
    return this._state.status != RUNNING && this._state.status != ERROR;
    // TODO: show in the UI that the tests couldn't be run?
  },

  stopTests: function() {
    if (this._runner) {
      this._runner.abort();
      LOG("Stopping tests");
      TR.rpc("suspend_timer", [this._runner.test.id, true], null, true);
      delete this._runner.test.running;
      this.updateTestStatus(this._runner.test);
      this._runner = null;
    }
  },

  onClientError: function(message) {
    this.setStatus(ERROR, "Client-side error: " + message);
  },

  setStatus: function(status, message, fromServer) {
    var oldStatus = TR._state.status;
    TR._state.status = status;
    TR._statusMessage = message;

    if (status == ERROR)
      this.stopTests();

    if (!fromServer && oldStatus != status) {
      this.rpc("set_status", [status, message], null, true);
    }
    TR.updateUI();
  },

  showResultDetail: function(test) {
    this.showBox("#resultDetail");
    $("#resultDetailTestId").text(test.id);
    $("#resultDetailTestType").text(test.type);
    $("#resultDetailStatus").text(test.result.status.toUpperCase());
    $("#resultDetailStatusMessage").text(test.result.status_message);

    $("#resultDetail .typeSpecific").hide();
    $("#resultDetail .typeSpecific." + test.type).show();

    if (test.type == "mochitest" || test.type == "browsertest") {
      $("#resultDetailPassCount").text(test.result.pass_count);
      $("#resultDetailFailCount").text(test.result.fail_count);
      $("#resultDetailLog").text(test.result.log);
    } else if (test.type == "reftest") {
      $("#resultDetailTestEqual").text(test.equal &&
                                       "Images should match" ||
                                       "Images should differ");
      $("#resultDetailPixelDiff").text(test.result.pixel_diff);
      jQuery(["1", "2", "diff"]).each(function() {
        var testUrl;
        if (this == "1")
          testUrl = test.url;
        else if (this == "2")
          testUrl = test.url2;
        if (testUrl)
          $("#resultDetailTestUrl" + this).attr("href", testUrl).text(testUrl);

        var imageUrl = test.result["image" + this];
        var ucf = this.substr(0, 1).toUpperCase() + this.substr(1);
        if (!imageUrl) {
          $("#resultDetailImage" + ucf).hide().attr("src", "");
          return;
        }
        imageUrl = Utils.fixupImageUrl(imageUrl);
        $("#resultDetailImage" + ucf).attr("src", imageUrl);
      })
    }
  },

  updateCountersFromTest: function(test) {
    if (!this._counters)
      return;
    var result = test.result;
    if (!result)
      return;
    this._counters.done++;
    if (result.status == "pass")
      this._counters.pass++;
    else if (result.status == "fail")
      this._counters.fail++;
    else
      this._counters.other++;
  },

  updateUI: function(test) {
    LOG("updateUI called");
    $("#currentTest").text("");
    $("#testStatus").html("");

    var status = this._state.status;
    $("body").attr("class", "status-" +
                   this._statusStrings[status].toLowerCase());
    if (status == RUNNING)
      $("#testsTable").addClass("running");
    else
      $("#testsTable").removeClass("running");

    var testCount = this._state.tests &&  this._state.tests.length || 0;

    if (!this._counters) {
      this._counters = {
        pass: 0, fail: 0, other: 0, done: 0, total: testCount
      };
      for (var i = 0; i < testCount; i++) {
        this.updateCountersFromTest(this._state.tests[i]);
      }
    }
    for (counterName in this._counters)
      $("#" + counterName + "Count").text(this._counters[counterName]);

    var percent = 0;
    if (testCount > 0)
      percent = 100 * (this._counters.done / testCount);
    $("#progressBar").width(percent.toFixed(0) + "%");

    $("#startButton").toggle(this.canRunTests() &&
                             (this._counters.done < testCount));
    $("#stopButton").toggle(status == RUNNING);
    $("#loadTestsButton").toggle(status != RUNNING);
    $("#saveResultsButton").toggle(status != RUNNING &&
                                   this._counters.done > 0);
    $("#clearResultsButton").toggle(status != RUNNING &&
                                    status != ERROR &&
                                    this._counters.done > 0);
    $("#resetButton").toggle(status != RUNNING);

    $("#status").text(this._statusStrings[status]);
    // TODO: strip the message if too long, or use CSS.
    $("#statusMessage").html(this._statusMessage);
    if (status == ERROR) {
      $("#statusMessage").append(" <a href='#'>more info</a>")
                         .find("a").click(function(e) {
                           e.preventDefault();
                           TR.showBox("#errorBox");
                         });
      $("#errorDetail").text(TR._statusMessage ||
                             "no detail");
      $("#errorBox").show();
    }

    if (test)
      this.updateTestStatus(test);
  },

  updateTestStatus: function(test) {
    // Using getElementById because the test identifier contains slashes which
    // are interpreted by jQuery.
    var row = document.getElementById("testid-" + test.id);
    var statusCell = $(row).find("td.status");

    if (statusCell.length == 0) {
      return;
    }

    statusCell.attr("class", "status");
    var status = test.result && test.result.status;
    if (test.running) {
      status = "running";
    }

    if (!status) {
      statusCell.html("<a href='#' class='run'>(run)</a>");
      statusCell.find("a.run").click(function(e) {
        e.preventDefault();
        if (!TR.canRunTests())
          return;
        TR.setStatus(RUNNING, "Running a single test");
        TR.runTest(test, function() {
          TR.setStatus(STOPPED, "Single test completed");
        });
      });
      statusCell.append("<a href='#' class='skip'>(skip)</a>");
      statusCell.find("a.skip").click(function(e) {
        e.preventDefault();
        if (TR._state.status == RUNNING)
          return;
        test.result = {
          status: "skipped"
        };
        TR.sendTestResult(test, false);
      });
      return;
    }

    statusCell.addClass("result-" + status);
    statusCell.html(status.toUpperCase() +
                    " <a href='#' class='detail'>(detail)</a>" +
                    " <a href='#' class='clear'>(clear)</a>");

    statusCell.find("a.detail").click(function(e) {
      e.preventDefault();
      TR.showResultDetail(test);
    });

    statusCell.find("a.clear").click(function(e) {
      e.preventDefault();
      delete test.result;
      TR.sendTestResult(test, false);
    });
  },

  updateTestsTable: function() {
    var testsTable = $("#testsTable");
    testsTable.hide();

    testsTable.find("tbody > tr").remove();

    for (var i = 0; i < this._state.tests.length; i++) {
      var test = this._state.tests[i];

      var tr = document.createElement("tr");
      tr.id = "testid-" + test.id;

      $(tr).html("<td class='status'></td>" +
                 "<td>" + test.type + "</td>" +
                 "<td>" + test.full_id +
                 " <a href='#' class='moreInfo'>(+ more info)</a>" +
                 " <a href='#' class='lessInfo'>(- less info)</a>" +
                 "</td>");

      $(tr).find("a.moreInfo").click(function(test) {
        return function(e) {
          e.preventDefault();

          var cell = $(this).parent();
          cell.find("a").toggle();
          if (cell.find(".testDetail").show().length > 0)
            return;

          function urlLink(url, title) {
            return "<dt>" + title + "</dt>" +
                   "<dd><a href='" + url + "' target='_blank'>" + url +
                   "</a></dd>"
          }

          var typeSpecificDetail = "";
          if (test.type == "mochitest" || test.type == "browsertest") {
            typeSpecificDetail = urlLink(test.url, "URL");
          } else if (test.type == "reftest") {
            typeSpecificDetail = "<dt>Comparison type</dt>" +
                                 "<dd>" + (test.equal &&
                                           "Images should match" ||
                                           "Images should differ") + "</dd>" +
                                 urlLink(test.url, "URL 1") +
                                 urlLink(test.url2, "URL 2");
          }

          cell.append("<div class='testDetail'>" +
                      "<dl>" +
                        "<dt>Test ID:</dt>" +
                        "<dd>" + test.id + "</dd>" +
                        // Not yet available:
                        //"<dt>Testsuite:</dt>" +
                        //"<dd>" + test.testsuite + "</dd>" +
                        //"<dt>Testgroup:</dt>" +
                        //"<dd>" + test.testgroup + "</dd>" +
                        typeSpecificDetail +
                      "</dl>" +
                      "</div>");
        };
      }(test));

      $(tr).find("a.lessInfo").hide().click(function(e) {
        e.preventDefault();
        $(this).parent().find("a").toggle().end()
                        .find(".testDetail").hide();
      });

      testsTable.append(tr);
      this.updateTestStatus(test);
    }
    testsTable.show();
  },

  loadState: function() {
    this.rpc("get_state", [], function(msg) {
      this._state = msg;
      LOG("current status: ", this._state.status);

      this.setStatus(this._state.status, this._state.status_message, true);

      $("#batchMode").text(this._state.batch);
      $("#totalTests").text(this._state.tests.length);

      this._counters = null;
      this._currentTestIndex = -1;

      this.updateUI();
      this.updateTestsTable();

      if (this._state.status == NEEDS_TESTS) {
        $("#loadTestsBox").show();
        return;
      }

      if (this._state.status == RUNNING && this._params.noAutoStart)
        this.setStatus(STOPPED, "Stopped due to noAutoStart param");

      if (this._state.status == STOPPED && !this._params.noAutoStart)
        this.setStatus(RUNNING, "Running all tests");

      if (this._state.status == RUNNING)
        this.runAllTests();
    });
  },

  // Tests running logic:

  sendTestResult: function(test, didStartNotify) {
    this.rpc("set_result",
             [test.id, test.result || {}, didStartNotify],
             function() {

      if (this._counters && test.result) {
        this.updateCountersFromTest(test);
      } else {
        // Having no result can happen either when a test is set as skipped or
        // when it was aborted. The counters update would differ in both cases
        // so just clear the counters to let updateUI recalculate them.
        this._counters = null;
      }

      TR.updateUI(test);
    }, true);
  },

  runTest: function(test, onDone) {
    this.assert(this._state.status == RUNNING,
                "runTest should be called when the status is RUNNING");

    LOG("***********  Running test " + test.id + "  ***********");
    $("#currentTest").text(test.id);
    test.running = true;
    this.updateTestStatus(test);

    this.assert(!this._runner, "A runner is already active");

    this.rpc("test_started", [test.id], null, true);

    var typeToClass = {
      mochitest: MochitestRunner,
      browsertest: BrowsertestRunner,
      reftest: ReftestRunner
    };
    var runnerClass = typeToClass[test.type]
    this.assert(runnerClass, "Unknown test type " + test.type);
    this._runner = new runnerClass(test, {
      onError: function(message) {
        TR.onClientError(message);
      },
      onMessage: function(message) {
        $("#testStatus").html(message);
      },
      onSuspendTimer: function(suspended) {
        LOG("onPauseTimer called");
        if (TR._state.timout <= 0)
          return;

        TR.rpc("suspend_timer", [test.id, suspended], null, true);
      },
      // Test is passed as argument from the runner instead of being
      // referenced from parent scope to work around a Firefox 3.7 bug:
      // https://bugzilla.mozilla.org/show_bug.cgi?id=517578
      onFinished: function(test) {
        LOG("Test finished with result", test.result, test);
        TR._runner = null;
        delete test.running;
        TR.sendTestResult(test, true);

        if (onDone)
          onDone();
      }
    }, this.rpc, this._state.batch, this._state.timeout);
    this._runner.test = test;

    this._runner.run();
  },

  runAllTests: function() {
    LOG("runAllTests called");
    this.assert(this._state.status == RUNNING,
                "runAllTests should be called when the status is RUNNING");

    var nextTest = this._state.tests[this._currentTestIndex];
    if (nextTest && nextTest.result)
      nextTest = null;
    if (!nextTest) {
      for (var i = 0; i < this._state.tests.length; i++) {
        var test = this._state.tests[i]
        if (test.result)
          continue;
        nextTest = test;
        this._currentTestIndex = i;
        break;
      }
    }

    if (!nextTest) {
      // TODO: this logic should also be used when running a single test
      // which is the last one.
      this.setStatus(FINISHED, "All tests completed");
      $("#viewSaveResultsCompletedMessage").show();
      TR.showBox("#viewSaveResults");
      return;
    }

    this.runTest(nextTest, function() {
      this._currentTestIndex++;
      if (TR._state.status == RUNNING) {
        TR.runAllTests();
      }
    });
  }
};

jQuery(function() {
  TR.init();
});
