#!/bin/bash
# Wrapper scripts for running Xvfb

#XVFB_OPTS="-fbdir /tmp/fb"
XVFB_OPTS=

xvfb-run -s  "-screen 0 1024x1500x24 $XVFB_OPTS" $*
