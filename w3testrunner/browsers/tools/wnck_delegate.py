#!/usr/bin/python
"""Utility script to interact with windows using wnck on Linux.

A dedicated script is used instead of using the wnck module from the application
so that we don't need to deal with the GTK event loop (and its side effects).
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

    #print "App names:", [w.get_application().get_name() for w in windows]

    # Opera does not return "Opera" when calling w.get_application().get_name()
    # but the title of the window (for instance "page title - Opera").
    # That's why "in" is used instead of strict equality. This is suboptimal
    # because there could be false positives.
    windows = [w for w in windows if appname in w.get_application().get_name()]
    if cmd == "maximize":
        if len(windows) != 1:
            print "Did not find only one window to maximize (count: %s)" % \
                  len(windows)
            sys.exit(1)
        windows[0].maximize()
    elif cmd == "countwindows":
        print len(windows)
    else:
        print "Unknown command %s" % cmd
