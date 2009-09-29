// Inspired by MochiKit SimpleTest.js and Mozilla's modified version.
//
// http://trac.mochikit.com/browser/mochikit/trunk/tests/SimpleTest/SimpleTest.js
// http://mxr.mozilla.org/mozilla-central/source/testing/mochitest/tests/SimpleTest/SimpleTest.js

(function() {

//  --------------- Internal state and functions -----------------

var _parentRunner = null;
if (typeof(parent) != "undefined" && parent.BrowserTestRunner) {
  _parentRunner = parent.BrowserTestRunner;
}

_tests = [];

// TODO should pass the test object to the parent and let it format the log
// message itself.
_logResult = function(test, passString, failString) {
  if (!_parentRunner)
    return;
  var msg = test.result ? passString : failString;
  msg += " | " + test.name;
  var diag = test.diag ? " - " + test.diag : "";
  if (test.result) {
    _parentRunner.logger.log(msg);
  } else {
    _parentRunner.logger.error(msg + diag);
  }
};

//  --------------- Assertion functions -----------------

/**
 * Something like assert.
**/
ok = function (condition, name, diag) {
  var test = {'result': !!condition, 'name': name, 'diag': diag};
  _logResult(test, "TEST-PASS", "TEST-UNEXPECTED-FAIL");
  _tests.push(test);
};

// XXX repr() was removed from the failure message.
// Implement something equivalent?

/**
 * Roughly equivalent to ok(a==b, name)
**/
is = function (a, b, name) {
  ok(a == b, name, "got " + a + ", expected " + b);
};

isnot = function (a, b, name) {
  ok(a != b, name, "Didn't expect " + a + ", but got it.");
};

//  isDeeply() implementation

DNE = {dne: 'Does not exist'};
LF = "\r\n";

_isRef = function (object) {
  var type = typeof(object);
  return type == 'object' || type == 'function';
};

_typeOf = function (object) {
  var c = Object.prototype.toString.apply(object);
  var name = c.substring(8, c.length - 1);
  if (name != 'Object') return name;
  // It may be a non-core class. Try to extract the class name from
  // the constructor function. This may not work in all implementations.
  if (/function ([^(\s]+)/.test(Function.toString.call(object.constructor))) {
    return RegExp.$1;
  }
  // No idea. :-(
  return name;
};

_isa = function (object, clas) {
  return _typeOf(object) == clas;
};

_deepCheck = function (e1, e2, stack, seen) {
  var ok = false;
  // Either they're both references or both not.
  var sameRef = !(!_isRef(e1) ^ !_isRef(e2));
  if (e1 == null && e2 == null) {
    ok = true;
  } else if (e1 != null ^ e2 != null) {
    ok = false;
  } else if (e1 == DNE ^ e2 == DNE) {
    ok = false;
  } else if (sameRef && e1 == e2) {
    // Handles primitives and any variables that reference the same
    // object, including functions.
    ok = true;
  } else if (_isa(e1, 'Array') && _isa(e2, 'Array')) {
    ok = _eqArray(e1, e2, stack, seen);
  } else if (typeof e1 == "object" && typeof e2 == "object") {
    ok = _eqAssoc(e1, e2, stack, seen);
  } else {
    // If we get here, they're not the same (function references must
    // always simply rererence the same function).
    stack.push({ vals: [e1, e2] });
    ok = false;
  }
  return ok;
};

_eqArray = function (a1, a2, stack, seen) {
  // Return if they're the same object.
  if (a1 == a2) return true;

  // JavaScript objects have no unique identifiers, so we have to store
  // references to them all in an array, and then compare the references
  // directly. It's slow, but probably won't be much of an issue in
  // practice. Start by making a local copy of the array to as to avoid
  // confusing a reference seen more than once (such as [a, a]) for a
  // circular reference.
  for (var j = 0; j < seen.length; j++) {
    if (seen[j][0] == a1) {
      return seen[j][1] == a2;
    }
  }

  // If we get here, we haven't seen a1 before, so store it with reference
  // to a2.
  seen.push([ a1, a2 ]);

  var ok = true;
  // Only examines enumerable attributes. Only works for numeric arrays!
  // Associative arrays return 0. So call _eqAssoc() for them, instead.
  var max = a1.length > a2.length ? a1.length : a2.length;
  if (max == 0) return _eqAssoc(a1, a2, stack, seen);
  for (var i = 0; i < max; i++) {
    var e1 = i > a1.length - 1 ? DNE : a1[i];
    var e2 = i > a2.length - 1 ? DNE : a2[i];
    stack.push({ type: 'Array', idx: i, vals: [e1, e2] });
    if ((ok = _deepCheck(e1, e2, stack, seen))) {
      stack.pop();
    } else {
      break;
    }
  }
  return ok;
};

_eqAssoc = function (o1, o2, stack, seen) {
  // Return if they're the same object.
  if (o1 == o2) return true;

  // JavaScript objects have no unique identifiers, so we have to store
  // references to them all in an array, and then compare the references
  // directly. It's slow, but probably won't be much of an issue in
  // practice. Start by making a local copy of the array to as to avoid
  // confusing a reference seen more than once (such as [a, a]) for a
  // circular reference.
  seen = seen.slice(0);
  for (var j = 0; j < seen.length; j++) {
    if (seen[j][0] == o1) {
      return seen[j][1] == o2;
    }
  }

  // If we get here, we haven't seen o1 before, so store it with reference
  // to o2.
  seen.push([ o1, o2 ]);

  // They should be of the same class.

  var ok = true;
  // Only examines enumerable attributes.
  var o1Size = 0; for (var i in o1) o1Size++;
  var o2Size = 0; for (var i in o2) o2Size++;
  var bigger = o1Size > o2Size ? o1 : o2;
  for (var i in bigger) {
    var e1 = o1[i] == undefined ? DNE : o1[i];
    var e2 = o2[i] == undefined ? DNE : o2[i];
    stack.push({ type: 'Object', idx: i, vals: [e1, e2] });
    if ((ok = _deepCheck(e1, e2, stack, seen))) {
      stack.pop();
    } else {
      break;
    }
  }
  return ok;
};

_formatStack = function (stack) {
  var variable = '$Foo';
  for (var i = 0; i < stack.length; i++) {
    var entry = stack[i];
    var type = entry['type'];
    var idx = entry['idx'];
    if (idx != null) {
      if (/^\d+$/.test(idx)) {
        // Numeric array index.
        variable += '[' + idx + ']';
      } else {
        // Associative array index.
        idx = idx.replace("'", "\\'");
        variable += "['" + idx + "']";
      }
    }
  }

  var vals = stack[stack.length-1]['vals'].slice(0, 2);
  var vars = [
    variable.replace('$Foo',     'got'),
    variable.replace('$Foo',     'expected')
  ];

  var out = "Structures begin differing at:" + LF;
  for (var i = 0; i < vals.length; i++) {
    var val = vals[i];
    if (val == null) {
      val = 'undefined';
    } else {
      val == DNE ? "Does not exist" : "'" + val + "'";
    }
  }

  out += vars[0] + ' = ' + vals[0] + LF;
  out += vars[1] + ' = ' + vals[1] + LF;

  return '    ' + out;
};


isDeeply = function (it, as, name) {
  var ok;
  // ^ is the XOR operator.
  if (_isRef(it) ^ _isRef(as)) {
    // One's a reference, one isn't.
    ok = false;
  } else if (!_isRef(it) && !_isRef(as)) {
    // Neither is an object.
    ok = is(it, as, name);
  } else {
    // We have two objects. Do a deep comparison.
    var stack = [], seen = [];
    if ( _deepCheck(it, as, stack, seen)) {
      ok = ok(true, name);
    } else {
      ok = ok(false, name, _formatStack(stack));
    }
  }
  return ok;
};

//  --------------- Table of results displayed in the browser -----------------

function _createElement(name, attrs) {
  var el = document.createElement(name);
  if (attrs) {
    for (var key in attrs) {
      el.setAttribute(key, attrs[key]);
    }
  }
  var children = [];
  for (var i = 2; i < arguments.length; i++) {
    children.push(arguments[i]);
  }

  function appendContent(parent, content) {
    if (!content)
      return;
    if (content instanceof Array) {
      for (var i = 0; i < content.length; i++) {
        appendContent(parent, content[i]);
      }
      return;
    }
    if (typeof(content) == "string") {
      parent.innerHTML += content;
      return;
    }
    parent.appendChild(content);
  }
  appendContent(el, children);

  return el;
}

function _createElementFunc(name) {
  return function() {
    var args = [name];
    for (var i = 0; i < arguments.length; i++) {
      args.push(arguments[i]);
    }
    return _createElement.apply(null, args);
  }
}

// shortcuts
var A = _createElementFunc("a");
var SPAN = _createElementFunc("span");
var DIV = _createElementFunc("div");
var LINK = _createElementFunc("link");

/**
 * Makes a test report, returns it as a DIV element.
**/
_createReportDiv = function () {

  var passed = 0;
  var failed = 0;

  var results = [];
  for (var i = 0; i < _tests.length; i++) {
    var test = _tests[i];
    var cls, msg;
    var diag = test.diag ? " - " + test.diag : "";
    if (test.result) {
      passed++;
      cls = "test_ok";
      msg = "passed | " + test.name;
    } else {
      failed++;
      cls = "test_not_ok";
      msg = "failed | " + test.name + diag;
    }
    results.push(DIV({"class": cls}, msg));
  }

  var summary_class = ((failed == 0) ? 'all_pass' : 'some_fail');

  return DIV({'class': 'show_test_not_ok', 'id': 'tests_report'},
    DIV({'class': 'tests_summary ' + summary_class},
      DIV({'class': 'tests_passed'}, "Passed: " + passed),
      DIV({'class': 'tests_failed'}, "Failed: " + failed)
    ),
    results
  );
};

/**
 * Toggle visibility for divs with a specific class.
**/
_toggleReportDivClass = function (cls, event) {
  var reportDiv = document.getElementById('tests_report');

  if (reportDiv.className.search('(^|\\s)' + cls + '(\\s|$)') != -1) {
    reportDiv.className = reportDiv.className.replace(
                            new RegExp('(^|\\s)' + cls + '(\\s|$)'),
                            RegExp.$1 + ' ' + RegExp.$2);
  } else {
    reportDiv.className += ' ' + cls;
  }

  if (event)
    event.preventDefault();
};

/**
 * Shows the report in the browser
**/
_showReport = function() {
  // Add css stylesheet.
  var cssLink = LINK({'rel': 'stylesheet', 'type': 'text/css',
                      'href': '/browsertest.css'}, null);
  var head = document.getElementsByTagName("head")[0];
  if (head)
    head.appendChild(cssLink);

  var togglePassed = A({'href': '#'}, "Toggle passed checks");
  var toggleFailed = A({'href': '#'}, "Toggle failed checks");
  togglePassed.onclick = function(event) {
    _toggleReportDivClass('show_test_ok', event);
  };
  toggleFailed.onclick = function(event) {
    _toggleReportDivClass('show_test_not_ok', event);
  };
  var body = document.body;  // Handles HTML documents
  if (!body) {
    // Do the XML thing.
    body = document.getElementsByTagNameNS("http://www.w3.org/1999/xhtml",
                                           "body")[0];
  }
  var firstChild = body.childNodes[0];
  var addNode;
  if (firstChild) {
    addNode = function (el) {
      body.insertBefore(el, firstChild);
    };
  } else {
    addNode = function (el) {
      body.appendChild(el)
    };
  }
  addNode(togglePassed);
  addNode(SPAN(null, "&nbsp;"));
  addNode(toggleFailed);
  addNode(_createReportDiv());
};

//  --------------- Workflow functions -----------------

/**
 * Finishes the tests.
**/
finish = function () {
  if (_tests.length == 0)
    ok(false, "No checks actually run.");

  _showReport();
  if (_parentRunner) {
    // XXX pass document?
    _parentRunner.testFinished(document);
  }
};

// NOTE: The onerror callback is not implemented on Opera and WebKit, so we
// can't rely on it to catch all tests errors.
var _oldOnError = window.onerror;
window.onerror = function simpletestOnerror(errorMsg, url, lineNumber) {
  var funcIdentifier = "[browsertest.js, window.onerror] ";

  ok(false, funcIdentifier + "An error occurred", errorMsg);

  if (_oldOnError) {
    try {
      // Ignore return value: always run default handler.
      _oldOnError(errorMsg, url, lineNumber);
    } catch (e) {
      ok(false, funcIdentifier + "Exception thrown by _oldOnError()", e);
      if (e.stack)
        ok(false, funcIdentifier + "JavaScript error stack:\n" + e.stack);
    }
  }

  // Need to call finish() manually here, yet let the test actually end first.
  setTimeout(finish, 0);
}


//  --------------- Public symbols export -----------------

window.ok = ok;
window.is = is;
window.isnot = isnot;
window.isDeeply = isDeeply;
window.finish = finish;

window.BrowserTest = {
  // Privileged functions here.
};

})();
