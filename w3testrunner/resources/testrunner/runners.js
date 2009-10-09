
var Runner = Class.extend({
  init: function(test, callbacks, rpcFunc, batch, timeoutDurationSec) {
    this._finished = false;
    this._hangTimeout = null;

    this._test = test;
    this._callbacks = callbacks;
    this._rpcFunc = rpcFunc;
    this._batch = batch;
    this._timeoutDurationMS = timeoutDurationSec * 1000;

    this._result = {
      status: "fail"
    };
  },

  _hangTimeoutCallback: function() {
    LOG("Hang timeout called");
    this._result.status = "timeout";
    this._result.status_message = "Timeout detected from client side";
    this._finish();
  },

  _stopHangTimeout: function() {
    if (!this._hangTimeout)
      return;

    clearTimeout(this._hangTimeout);
    this._hangTimeout = null;
  },

  _setupHangTimeout: function() {
    this._stopHangTimeout();

    if (this._timeoutDurationMS <= 0)
      return;

    var self = this;
    this._hangTimeout = setTimeout(function() {
      self._hangTimeoutCallback();
    }, this._timeoutDurationMS);
  },

  _activity: function(message) {
    if (this._finished)
      return;
    this._callbacks.onMessage(message);
    this._setupHangTimeout();
  },

  _finish: function(wasAborted) {
    this._finished = true;
    this._cleanup();
    if (!wasAborted) {
      this._test.result = this._result;
      // pass the tests to the callback because of
      // https://bugzilla.mozilla.org/show_bug.cgi?id=517578
      this._callbacks.onFinished(this._test);
    }
    this._test = null;
  },

  _runInternal: function() {
    throw Error("Not implemented");
  },

  _cleanup: function() {
    this._stopHangTimeout();
    this._iframe.src = "about:blank";
  },

  run: function() {
    if (this._finished)
      return;

    this._iframe = document.getElementById('testframe');
    this._setupHangTimeout();
    this._runInternal();
  },

  resume: function() {
  },

  abort: function() {
    this._finish(true);
  }
});

var MochitestRunner = Runner.extend({
  _runInternal: function() {
    this._result.pass_count = 0;
    this._result.fail_count = 0;
    this._result.log = "";

    var self = this;

    function checkState(funcName) {
      if (self._finished) {
        self._callbacks.onError(funcName + " called when test is finished");
        return true;
      }
      if (!self._test) {
        self._callbacks.onError(funcName + " called when no test is active");
        return true;
      }
      return false;
    }

    // Mochitests expect a "TestRunner" object on the parent frame with the
    // following properties:
    TestRunner.logEnabled = true;
    TestRunner.currentTestURL = this._test.url;
    TestRunner.logger = {
      log: function(str) {
        if (checkState("TestRunner.logger.log"))
          return;

        LOG("TestRunner.logger.log called from test ", self._test.id, str);
        self._result.pass_count += 1;
        self._result.log += str + "\n";
      },
      error: function(str) {
        if (checkState("TestRunner.logger.error"))
          return;

        LOG("TestRunner.logger.error called from test ", self._test.id, str);
        self._result.fail_count += 1;
        self._result.log += str + "\n";
      }
    };
    TestRunner.testFinished = function(doc) {
      if (checkState("TestRunner.testFinished"))
        return;

      LOG("TestRunner.testFinished called from test");
      if (self._result.fail_count == 0)
        self._result.status = "pass";
      self._finish();
    };

    this._iframe.src = this._test.url;
    this._iframe.name = this._test.url;

    this._activity("Frame loaded with test URL");
  },

  _cleanup: function() {
    this._super();
    delete TestRunner.logEnabled;
    delete TestRunner.currentTestURL;
    delete TestRunner.logger;
    delete TestRunner.testFinished;
  }
});

// This object is accessed from the frame running Browsertests.
var BrowsertestListener = {
  _runner: null,
  _checkState: function(funcName) {
    if (!this._runner) {
      LOG("Error: " + funcName + "called when no runner is active");
      // XXX this error should probably be propagated, but we don't have a
      // _callbacks object to use.
      return true;
    }
    if (this._runner._finished) {
      self._callbacks.onError(funcName + " called when test is finished");
      return true;
    }
    if (!this._runner._test) {
      self._callbacks.onError(funcName + " called when no test is active");
      return true;
    }
    return false;
  },

  logAssertion: function(assertion) {
    if (this._checkState("logAssertion"))
      return;

    LOG("BrowsertestListener.logAssertion called from test ",
        this._runner._test.id, assertion);

    if (assertion.result)
      this._runner._result.pass_count += 1;
    else
      this._runner._result.fail_count += 1;

    this._runner._result.log += assertion.message + "\n";
  },

  testFinished: function() {
    if (this._checkState("testFinished"))
      return;

    LOG("BrowsertestListener.testFinished called from test");

    if (this._runner._result.fail_count == 0)
      this._runner._result.status = "pass";
    this._runner._finish();
  }
};

var BrowsertestRunner = Runner.extend({
  _runInternal: function() {
    this._result.pass_count = 0;
    this._result.fail_count = 0;
    this._result.log = "";

    BrowsertestListener._runner = this;

    this._iframe.src = this._test.url;
    this._iframe.name = this._test.url;

    this._activity("Frame loaded with test URL");
  },

  _cleanup: function() {
    this._super();
    BrowsertestListener._runner = null;
  }
});


var ReftestRunner = Runner.extend({
  _states: [
    "loadUrl1",
    "takeScreenshot1",
    "loadUrl2",
    "takeScreenshot2AndCompare",
    "testFinished"
  ],
  _currentState: 0,
  _screenshot1Id: -1,

  init: function() {
    this._super.apply(this, arguments);

    ReftestRunner.activeRunner = this;
    if (!ReftestRunner.uiInitialized) {
      ReftestRunner.uiInitialized = true;

      $("#reftestContinueButton").click(function() {
        if (!ReftestRunner.activeRunner)
          return;

        $("#screenShotFailure").hide();
        ReftestRunner.activeRunner._callbacks.onSuspendTimer(false);
        ReftestRunner.activeRunner._setupHangTimeout();
        ReftestRunner.activeRunner._handleState();
      });
    }
  },

  _screenshotFailure: function(msg, nextStateName) {
    if (this._batch) {
      // XXX try to recover by asking the server to bring the browser window
      // to front?
      this._result.status = "error";
      this._result.status_message = msg.message;
      // TODO: save the failing image? (privacy concern if whole desktop screenshot)
      this._finish();
      return;
    }
    // No indexOf on IE!
    this._currentState = jQuery.inArray(nextStateName, this._states);

    this._stopHangTimeout();
    this._callbacks.onSuspendTimer(true);

    $("#screenShotFailureErrorMessage").text(msg.message);

    var errorImageUrl = Utils.fixupImageUrl(msg.error_image);
    $("#screenshotImageLink").attr("href", errorImageUrl);
    TR.showBox("#screenShotFailure");
  },

  _handleState: function() {
    if (this._finished)
      return;

    LOG("TestRunner.handleReftest called, current state: " +
        this._states[this._currentState] + " (" +  this._currentState + ")");

    var self = this;
    function loadUrl(url, callback) {
      $(self._iframe).one("load", function(e) {
        LOG("Frame loaded");
        // Some screenshots are blank if _handleState is called directly.
        // The load event may be fired before the OS has repainted the
        // frame.
        setTimeout(function() {
          self._handleState();
        }, 10);
      });
      self._iframe.src = url;
    }

    switch (this._states[this._currentState]) {
      case "loadUrl1":
        loadUrl(this._test.url);

        break;
      case "takeScreenshot1":
        window.scrollTo(0, 0);
        this._rpcFunc("take_screenshot1", [], function(msg) {
          LOG("Got message from server", msg);
          self._handleState(msg);
        });

        break;
      case "loadUrl2":
        var msg = arguments[0];

        if (!msg.success) {
          this._screenshotFailure(msg, "takeScreenshot1");
          return;
        }

        this._screenshot1Id = msg.screenshot1_id;
        loadUrl(this._test.url2);

        break;
      case "takeScreenshot2AndCompare":
        window.scrollTo(0, 0);
        this._rpcFunc("take_screenshot2_and_compare",
                      [this._screenshot1Id,
                       // always_save parameter:
                       this._test.equal ? "if_pixel_diff_gt_0" :
                                          "if_pixel_diff_eq_0"],
                      function(msg) {
                        self._handleState(msg);
                      });

        break;
      case "testFinished":
        var msg = arguments[0];

        if (!msg.success) {
          this._screenshotFailure(msg, "takeScreenshot2AndCompare");
          return;
        }

        var equal = msg.pixel_diff == 0;

        var testPassed = (equal == this._test.equal);
        LOG("test status: ", testPassed);

        this._result.status = testPassed && "pass" || "fail";
        this._result.pixel_diff = msg.pixel_diff;
        this._result.image1 = msg.image1;
        this._result.image2 = msg.image2;
        this._result.imagediff = msg.imagediff;
        this._finish();
    }
    this._currentState++;
  },

  _runInternal: function() {
    LOG("running reftest");

    this._result.pixel_diff = 0;
    this._result.image1 = null;
    this._result.image2 = null;
    this._result.imagediff = null;

    this._currentState = 0;
    this._handleState();
  },

  _cleanup: function() {
    this._super();
    ReftestRunner.activeRunner = null;
  }
});
