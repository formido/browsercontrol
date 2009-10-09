from w3testrunner.browsers.browser import Browser

class DummyBrowser(Browser):
    """Extension of Browser that does nothing."""

    name = "dummy"
    nopath = True

    def launch(self):
        pass

    def is_alive(self):
        return True

    def terminate(self):
        pass
