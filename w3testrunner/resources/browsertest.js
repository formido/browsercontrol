// Inspired by MochiKit SimpleTest.js and Mozilla's modified version.
//
// http://trac.mochikit.com/browser/mochikit/trunk/tests/SimpleTest/SimpleTest.js
// http://mxr.mozilla.org/mozilla-central/source/testing/mochitest/tests/SimpleTest/SimpleTest.js
//
// Assertion functions inspired by QUnit (http://docs.jquery.com/QUnit).
// http://github.com/jquery/qunit/raw/master/qunit/qunit.js

(function() {

//  --------------- Internal state and functions -----------------

var _parentListener = null;
if (typeof(parent) != "undefined" && parent.BrowsertestListener) {
  _parentListener = parent.BrowsertestListener;
}

var _assertions = [];

function _logAssertion(assertion) {
  if (!_parentListener)
    return;
  _parentListener.logAssertion(assertion);
};

//  --------------- Utilities -----------------

// Test for equality any JavaScript type.
// Discussions and reference: http://philrathe.com/articles/equiv
// Test suites: http://philrathe.com/tests/equiv
// Author: Philippe Rathé <prathe@gmail.com>
var _equiv = function () {

    var innerEquiv; // the real equiv function
    var callers = []; // stack to decide between skip/abort functions


    // Determine what is o.
    function hoozit(o) {
        if (o.constructor === String) {
            return "string";

        } else if (o.constructor === Boolean) {
            return "boolean";

        } else if (o.constructor === Number) {

            if (isNaN(o)) {
                return "nan";
            } else {
                return "number";
            }

        } else if (typeof o === "undefined") {
            return "undefined";

        // consider: typeof null === object
        } else if (o === null) {
            return "null";

        // consider: typeof [] === object
        } else if (o instanceof Array) {
            return "array";

        // consider: typeof new Date() === object
        } else if (o instanceof Date) {
            return "date";

        // consider: /./ instanceof Object;
        //           /./ instanceof RegExp;
        //          typeof /./ === "function"; // => false in IE and Opera,
        //                                          true in FF and Safari
        } else if (o instanceof RegExp) {
            return "regexp";

        } else if (typeof o === "object") {
            return "object";

        } else if (o instanceof Function) {
            return "function";
        } else {
            return undefined;
        }
    }

    // Call the o related callback with the given arguments.
    function bindCallbacks(o, callbacks, args) {
        var prop = hoozit(o);
        if (prop) {
            if (hoozit(callbacks[prop]) === "function") {
                return callbacks[prop].apply(callbacks, args);
            } else {
                return callbacks[prop]; // or undefined
            }
        }
    }

    var callbacks = function () {

        // for string, boolean, number and null
        function useStrictEquality(b, a) {
            if (b instanceof a.constructor || a instanceof b.constructor) {
                // to catch short annotaion VS 'new' annotation of a declaration
                // e.g. var i = 1;
                //      var j = new Number(1);
                return a == b;
            } else {
                return a === b;
            }
        }

        return {
            "string": useStrictEquality,
            "boolean": useStrictEquality,
            "number": useStrictEquality,
            "null": useStrictEquality,
            "undefined": useStrictEquality,

            "nan": function (b) {
                return isNaN(b);
            },

            "date": function (b, a) {
                return hoozit(b) === "date" && a.valueOf() === b.valueOf();
            },

            "regexp": function (b, a) {
                return hoozit(b) === "regexp" &&
                    a.source === b.source && // the regex itself
                    a.global === b.global && // and its modifers (gmi) ...
                    a.ignoreCase === b.ignoreCase &&
                    a.multiline === b.multiline;
            },

            // - skip when the property is a method of an instance (OOP)
            // - abort otherwise,
            //   initial === would have catch identical references anyway
            "function": function () {
                var caller = callers[callers.length - 1];
                return caller !== Object &&
                        typeof caller !== "undefined";
            },

            "array": function (b, a) {
                var i;
                var len;

                // b could be an object literal here
                if ( ! (hoozit(b) === "array")) {
                    return false;
                }

                len = a.length;
                if (len !== b.length) { // safe and faster
                    return false;
                }
                for (i = 0; i < len; i++) {
                    if ( ! innerEquiv(a[i], b[i])) {
                        return false;
                    }
                }
                return true;
            },

            "object": function (b, a) {
                var i;
                var eq = true; // unless we can proove it
                var aProperties = [], bProperties = []; // collection of strings

                // comparing constructors is more strict than using instanceof
                if ( a.constructor !== b.constructor) {
                    return false;
                }

                // stack constructor before traversing properties
                callers.push(a.constructor);

                for (i in a) { // be strict: don't ensures hasOwnProperty and go deep

                    aProperties.push(i); // collect a's properties

                    if ( ! innerEquiv(a[i], b[i])) {
                        eq = false;
                    }
                }

                callers.pop(); // unstack, we are done

                for (i in b) {
                    bProperties.push(i); // collect b's properties
                }

                // Ensures identical properties name
                return eq && innerEquiv(aProperties.sort(), bProperties.sort());
            }
        };
    }();

    innerEquiv = function () { // can take multiple arguments
        var args = Array.prototype.slice.apply(arguments);
        if (args.length < 2) {
            return true; // end transition
        }

        return (function (a, b) {
            if (a === b) {
                return true; // catch the most you can
            } else if (a === null || b === null || typeof a === "undefined" || typeof b === "undefined" || hoozit(a) !== hoozit(b)) {
                return false; // don't lose time with error prone cases
            } else {
                return bindCallbacks(a, callbacks, [b, a]);
            }

        // apply transition with (1..n) arguments
        })(args[0], args[1]) && arguments.callee.apply(this, args.splice(1, args.length -1));
    };

    return innerEquiv;

}();

/**
 * jsDump
 * Copyright (c) 2008 Ariel Flesler - aflesler(at)gmail(dot)com | http://flesler.blogspot.com
 * Licensed under BSD (http://www.opensource.org/licenses/bsd-license.php)
 * Date: 5/15/2008
 * @projectDescription Advanced and extensible data dumping for Javascript.
 * @version 1.0.0
 * @author Ariel Flesler
 * @link {http://flesler.blogspot.com/2008/05/jsdump-pretty-dump-of-any-javascript.html}
 */
var _jsDump = (function() {
	function quote( str ) {
		return '"' + str.toString().replace(/"/g, '\\"') + '"';
	};
	function literal( o ) {
		return o + '';
	};
	function join( pre, arr, post ) {
		var s = jsDump.separator(),
			base = jsDump.indent(),
			inner = jsDump.indent(1);
		if ( arr.join )
			arr = arr.join( ',' + s + inner );
		if ( !arr )
			return pre + post;
		return [ pre, inner + arr, base + post ].join(s);
	};
	function array( arr ) {
		var i = arr.length,	ret = Array(i);
		this.up();
		while ( i-- )
			ret[i] = this.parse( arr[i] );
		this.down();
		return join( '[', ret, ']' );
	};

	var reName = /^function (\w+)/;

	var jsDump = {
		parse:function( obj, type ) { //type is used mostly internally, you can fix a (custom)type in advance
			var	parser = this.parsers[ type || this.typeOf(obj) ];
			type = typeof parser;

			return type == 'function' ? parser.call( this, obj ) :
				   type == 'string' ? parser :
				   this.parsers.error;
		},
		typeOf:function( obj ) {
			var type = typeof obj,
				f = 'function';//we'll use it 3 times, save it
			return type != 'object' && type != f ? type :
				!obj ? 'null' :
				obj.exec ? 'regexp' :// some browsers (FF) consider regexps functions
				obj.getHours ? 'date' :
				obj.scrollBy ?  'window' :
				obj.nodeName == '#document' ? 'document' :
				obj.nodeName ? 'node' :
				obj.item ? 'nodelist' : // Safari reports nodelists as functions
				obj.callee ? 'arguments' :
				obj.call || obj.constructor != Array && //an array would also fall on this hack
					(obj+'').indexOf(f) != -1 ? f : //IE reports functions like alert, as objects
				'length' in obj ? 'array' :
				type;
		},
		separator:function() {
			return this.multiline ?	this.HTML ? '<br />' : '\n' : this.HTML ? '&nbsp;' : ' ';
		},
		indent:function( extra ) {// extra can be a number, shortcut for increasing-calling-decreasing
			if ( !this.multiline )
				return '';
			var chr = this.indentChar;
			if ( this.HTML )
				chr = chr.replace(/\t/g,'   ').replace(/ /g,'&nbsp;');
			return Array( this._depth_ + (extra||0) ).join(chr);
		},
		up:function( a ) {
			this._depth_ += a || 1;
		},
		down:function( a ) {
			this._depth_ -= a || 1;
		},
		setParser:function( name, parser ) {
			this.parsers[name] = parser;
		},
		// The next 3 are exposed so you can use them
		quote:quote,
		literal:literal,
		join:join,
		//
		_depth_: 1,
		// This is the list of parsers, to modify them, use jsDump.setParser
		parsers:{
			window: '[Window]',
			document: '[Document]',
			error:'[ERROR]', //when no parser is found, shouldn't happen
			unknown: '[Unknown]',
			'null':'null',
			undefined:'undefined',
			'function':function( fn ) {
				var ret = 'function',
					name = 'name' in fn ? fn.name : (reName.exec(fn)||[])[1];//functions never have name in IE
				if ( name )
					ret += ' ' + name;
				ret += '(';

				ret = [ ret, this.parse( fn, 'functionArgs' ), '){'].join('');
				return join( ret, this.parse(fn,'functionCode'), '}' );
			},
			array: array,
			nodelist: array,
			arguments: array,
			object:function( map ) {
				var ret = [ ];
				this.up();
				for ( var key in map )
					ret.push( this.parse(key,'key') + ': ' + this.parse(map[key]) );
				this.down();
				return join( '{', ret, '}' );
			},
			node:function( node ) {
				var open = this.HTML ? '&lt;' : '<',
					close = this.HTML ? '&gt;' : '>';

				var tag = node.nodeName.toLowerCase(),
					ret = open + tag;

				for ( var a in this.DOMAttrs ) {
					var val = node[this.DOMAttrs[a]];
					if ( val )
						ret += ' ' + a + '=' + this.parse( val, 'attribute' );
				}
				return ret + close + open + '/' + tag + close;
			},
			functionArgs:function( fn ) {//function calls it internally, it's the arguments part of the function
				var l = fn.length;
				if ( !l ) return '';

				var args = Array(l);
				while ( l-- )
					args[l] = String.fromCharCode(97+l);//97 is 'a'
				return ' ' + args.join(', ') + ' ';
			},
			key:quote, //object calls it internally, the key part of an item in a map
			functionCode:'[code]', //function calls it internally, it's the content of the function
			attribute:quote, //node calls it internally, it's an html attribute value
			string:quote,
			date:quote,
			regexp:literal, //regex
			number:literal,
			'boolean':literal
		},
		DOMAttrs:{//attributes to dump from nodes, name=>realName
			id:'id',
			name:'name',
			'class':'className'
		},
		HTML:true,//if true, entities are escaped ( <, >, \t, space and \n )
		indentChar:'   ',//indentation unit
		multiline:true //if true, items in a collection, are separated by a \n, else just a space.
	};

	return jsDump;
})();


//  --------------- Assertion functions -----------------

/**
 * Asserts true.
 * @example ok("foo" in obj2, "obj2 has no foo property");
**/
function ok(a, message) {
  message = _assertions.length + " | " + (a ? "pass" : "fail") +
            " | " + (message || "(no message)");
  var assertion = {
    result: !!a,
    message: message
  };
  _assertions.push(assertion);
  _logAssertion(assertion);
};

function _comparisonAssertion(result, actual, expected, message) {
  ok(result, result ? expected :
             "expected: " + _jsDump.parse(expected) + " got: " +
             _jsDump.parse(actual));
};

/**
 * Checks that the first two arguments are equal, with an optional message.
 * Prints out both actual and expected values.
 *
 * Prefered to ok(actual == expected, message)
 *
 * @example equals(obj1, 22, "obj1 value is not correct");
 *
 * @param Object actual
 * @param Object expected
 * @param String message (optional)
**/
function equals(actual, expected, message) {
  _comparisonAssertion(expected == actual, actual, expected, message);
};
// Alias for Mochitest compatibility.
var is = equals;

function same(actual, expected, message) {
  _comparisonAssertion(_equiv(actual, expected), actual, expected, message);
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
};

function _createElementFunc(name) {
  return function() {
    var args = [name];
    for (var i = 0; i < arguments.length; i++) {
      args.push(arguments[i]);
    }
    return _createElement.apply(null, args);
  }
};

// shortcuts
var A = _createElementFunc("a");
var SPAN = _createElementFunc("span");
var DIV = _createElementFunc("div");
var LINK = _createElementFunc("link");

/**
 * Makes an assertions report, returns it as a DIV element.
**/
function _createReportDiv() {

  var passed = 0;
  var failed = 0;

  var results = [];
  for (var i = 0; i < _assertions.length; i++) {
    var assertion = _assertions[i];
    var cls;
    if (assertion.result) {
      passed++;
      cls = "assertion_pass";
    } else {
      failed++;
      cls = "assertion_fail";
    }
    results.push(DIV({"class": cls}, assertion.message));
  }

  var summary_class = ((failed == 0) ? 'all_pass' : 'some_fail');

  return DIV({'class': 'show_assertion_fail', 'id': 'assertions_report'},
    DIV({'class': 'assertions_summary ' + summary_class},
      DIV({'class': 'asssertions_passed'}, "Passed: " + passed),
      DIV({'class': 'assertoins_failed'}, "Failed: " + failed)
    ),
    results
  );
};

/**
 * Toggle visibility for divs with a specific class.
**/
function _toggleReportDivClass(cls, event) {
  var reportDiv = document.getElementById('assertions_report');

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
function _showReport() {
  // Add css stylesheet.
  var cssLink = LINK({'rel': 'stylesheet', 'type': 'text/css',
                      'href': '/browsertest.css'}, null);
  var head = document.getElementsByTagName("head")[0];
  if (head)
    head.appendChild(cssLink);

  var togglePassed = A({'href': '#'}, "Toggle passed assertions");
  var toggleFailed = A({'href': '#'}, "Toggle failed assertions");
  togglePassed.onclick = function(event) {
    _toggleReportDivClass('show_assertion_pass', event);
  };
  toggleFailed.onclick = function(event) {
    _toggleReportDivClass('show_assertion_fail', event);
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
function finish() {
  if (_assertions.length == 0)
    ok(false, "No assertions were run.");

  _showReport();
  if (_parentListener) {
    _parentListener.testFinished();
  }
};

// NOTE: The onerror callback is not implemented on Opera and WebKit, so we
// can't rely on it to catch all tests errors.
var _oldOnError = window.onerror;
window.onerror = function simpletestOnerror(errorMsg, url, lineNumber) {
  window.onerror = null;
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
};


//  --------------- Public symbols export -----------------

window.Browsertest = {
  // Privileged functions here.
};

var globals = ["ok", "is", "equals", "same", "finish"];
for (var i = 0; i < globals.length; i++) {
  var fn = globals[i];
  window[fn] = eval(fn);
  Browsertest[fn] = this[fn];
}

})();
