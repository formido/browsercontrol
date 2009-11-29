class StoreException(Exception):
    pass

class TestStore(object):
    # Subclasses that can load tests multiple times should set this to False.
    load_once = True

    def __init__(self, runner, store_info):
        self.runner = runner
        self.store_info = store_info

    def load(self, metadata):
        """Load the tests and return them as a list.

        Implementors may also need to setup environment for running the loaded
        tests."""
        raise NotImplemented()

    def save(self, metadata):
        """Save the tests results."""
        pass

    def cleanup(self):
        """Cleanup everything the loader has setup for running the tests."""
        pass

    @classmethod
    def add_options(cls, parser):
        """Override this to add specific options for this parser."""
        pass

    @classmethod
    def options_to_store_info(cls, options):
        """Build and return a store_info dict from the given options or
        return None if the options don't contain relevant information for this
        store."""
        return None
