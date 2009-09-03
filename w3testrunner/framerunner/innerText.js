
// TODO: remove jQuery dependency?

/**
 * Implementation from the WebKit layout test emulator project.
 */
function textDump_webkit_layout_test_emulator(consoleMessages, alerts, doc, dirName, fileName, dumpChildFrames)
{
    if (fileName == null) return;

    var NodeFilter = Components.interfaces.nsIDOMNodeFilter;
    var treeWalker = doc.createTreeWalker(
                        doc.body,
                        NodeFilter.SHOW_TEXT,
                        null,
                        false);

    var dump = consoleMessages + alerts;

    var util = Components.classes["@mozilla.org/inspector/dom-utils;1"]
                         .createInstance(Components.interfaces.inIDOMUtils);

    while (treeWalker.nextNode())
    {
        var node = treeWalker.currentNode;

        if (!util.isIgnorableWhitespace(node) &&
            util.getParentForNode(node, false).nodeName.toLowerCase() != 'script')
        {
            dump += node.nodeValue;
        }
    }
}

/**
 * This function tries to emulate WebKit element.innerText function on browser
 * that do not support it.
 * The WebKit implementation serializes to text a node trying to have the text
 * serialization match the HTML visual output.  That means that hidden elements
 * will not appear in the serialization and that whitespace (tabs, line breaks,
 * spaces) will be chosen by a non trivial algorithm.
 * See http://trac.webkit.org/browser/trunk/WebCore/editing/TextIterator.cpp.
 *
 * This implementation does not match WebKit regarding white space.  However it
 * should more or less match for non whitespace characters.
 */
function toInnerText_dom(node) {

  var TEXT_NODE = 3;
  var ELEMENT_NODE = 1;

  var state = {};

  function textContentNoScript(node) {

    var txt = "";

    if (node.nodeType == ELEMENT_NODE) {
      var nn = node.nodeName.toLowerCase();

      // XXX should use a stack for nested tables. See nsPlainTextSerializer::DoOpenContainer
      if ("tr" == nn)
        state.hasWrittenCellsForRow = false;
      if ("td" == nn || "th" == nn) {
        if (state.hasWrittenCellsForRow) {
          txt += "\t"
        }
        state.hasWrittenCellsForRow = true;
      }

      if ("br" == nn)
          txt += "\n";

      jQuery.each(node.childNodes, function() {
        txt += textContentNoScript(this);
      });
      return txt;
    }

    if (node.nodeType != TEXT_NODE)
      return txt;

    var parent = node.parentNode;
    var parentDisplay = jQuery.css(parent, "display");
    var parentVisibility = jQuery.css(parent, "visibility");

    if (parentDisplay == "none" || parentVisibility == "hidden")
        return txt;

    if ((parentDisplay == "block" || parentDisplay == "list-item") &&
        !node.previousSibling &&
        txt[txt.length - 1] != "\n")
        txt += "\n";

    if (window.args !== undefined && args.verbose)
        txt += "[("+parent.nodeName+","+parentDisplay+")" + node.nodeValue + "]";
    else
        txt += node.nodeValue;
    return txt;
  };

  return textContentNoScript(node);
}

function toInnerText(node) {

    var isOpera = (navigator.userAgent.indexOf("Opera") != -1);
    var isIE = navigator.appVersion.match(/MSIE/) == "MSIE";

    if (!isIE && !isOpera && node.innerText !== undefined)
        return node.innerText;

    return toInnerText_dom(node);
}
