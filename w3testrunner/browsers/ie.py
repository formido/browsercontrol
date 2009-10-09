from w3testrunner.browsers.browser import BrowserLin, BrowserWin

class IE(BrowserWin):
    name = "ie"
    process_name = "iexplore"
    executable = "iexplore"
    directory = "Internet Explorer"
