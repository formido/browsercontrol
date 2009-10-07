class LoaderException(Exception):
    pass

class TestsLoader(object):
    def __init__(self, runner, load_info):
        self.runner = runner
        self.load_info = load_info

    def load(self):
        """Load the tests and return them as a list.

        Implementors may also need to setup environment for running the loaded
        tests."""
        raise NotImplemented()

    def cleanup(self):
        """Cleanup everything the loader has setup for running the tests."""
        pass

    @classmethod
    def add_options(cls, parser):
        """Override this to add specific options for this parser."""
        pass

    @classmethod
    def maybe_load_tests(cls, runner):
        """Override to load tests on Runner initialization. If tests are to
        be loaded, this method should return a load_info object or None
        otherwise."""
        return None
