#!/usr/bin/python
"""Utility script to interact with windows using wnck on Linux.

Why using a dedicated script for this? That's because we don't want to deal with
the GTK event loop (and its side effects) in the main application.
"""

import sys
import wnck

if __name__ == "__main__":
    screen = wnck.screen_get_default()
    screen.force_update()
    windows = screen.get_windows()

    if len(sys.argv) != 3:
        print "Usage: %s {maximize|countwindows} APPNAME"
        sys.exit(1)

    cmd, appname = sys.argv[1:]

    #print  [w.get_application().get_name() for w in windows]

    # XXX Opera does not return "Opera", but the title of the window "page title - Opera".
    # So use "in" instead of strict equality. This sucks because there could easily be
    # false positives.
    windows = [w for w in windows if appname in w.get_application().get_name()]
    if cmd == "maximize":
        if len(windows) != 1:
            print "Did not find only one window to maximize (count: %s)" % len(windows)
            sys.exit(1)
        windows[0].maximize()
    elif cmd == "countwindows":
        print len(windows)
    else:
        print "Unknown command %s" % cmd
