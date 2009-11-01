import os

from w3testrunner.browsers.browser import BrowserLin, BrowserWin, BrowserMac

class FirefoxMixin(object):
    name = "firefox"
    needs_temporary_profile_dir = True
    process_name = "firefox"

    def initialize_profile(self):
        """Sets up the standard testing profile.

        Adapted from
        http://hg.mozilla.org/mozilla-central/file/tip/build/automation.py.in
        """

        prefs = []

        part = """\
user_pref("browser.dom.window.dump.enabled", true);
user_pref("dom.allow_scripts_to_close_windows", true);
user_pref("dom.disable_open_during_load", false);
user_pref("dom.max_script_run_time", 0); // no slow script dialogs
user_pref("dom.max_chrome_script_run_time", 0);
user_pref("dom.popup_maximum", -1);
user_pref("signed.applets.codebase_principal_support", true);
user_pref("security.warn_submit_insecure", false);
user_pref("browser.shell.checkDefaultBrowser", false);
user_pref("shell.checkDefaultClient", false);
user_pref("browser.warnOnQuit", false);
user_pref("accessibility.typeaheadfind.autostart", false);
user_pref("javascript.options.showInConsole", true);
user_pref("layout.debug.enable_data_xbl", true);
user_pref("browser.EULA.override", true);
user_pref("javascript.options.jit.content", true);
user_pref("gfx.color_management.force_srgb", true);
user_pref("network.manage-offline-status", false);
user_pref("test.mousescroll", true);
user_pref("security.default_personal_cert", "Select Automatically"); // Need to client auth test be w/o any dialogs
user_pref("network.http.prompt-temp-redirect", false);
user_pref("svg.smil.enabled", true); // Needed for SMIL mochitests until bug 482402 lands
user_pref("media.cache_size", 100);
user_pref("security.warn_viewing_mixed", false);

user_pref("geo.wifi.uri", "http://localhost:8888/tests/dom/tests/mochitest/geolocation/network_geolocation.sjs");
user_pref("geo.wifi.testing", true);

user_pref("camino.warn_when_closing", false); // Camino-only, harmless to others

// Make url-classifier updates so rare that they won't affect tests
user_pref("urlclassifier.updateinterval", 172800);
// Point the url-classifier to the local testing server for fast failures
user_pref("browser.safebrowsing.provider.0.gethashURL", "http://localhost:8888/safebrowsing-dummy/gethash");
user_pref("browser.safebrowsing.provider.0.keyURL", "http://localhost:8888/safebrowsing-dummy/newkey");
user_pref("browser.safebrowsing.provider.0.lookupURL", "http://localhost:8888/safebrowsing-dummy/lookup");
user_pref("browser.safebrowsing.provider.0.updateURL", "http://localhost:8888/safebrowsing-dummy/update");
"""
        prefs.append(part)

        # write the preferences
        prefsFile = open(self.profile_dir + "/" + "user.js", "a")
        prefsFile.write("".join(prefs))
        prefsFile.close()

    def prepare_launch(self):
        super(FirefoxMixin, self).prepare_launch()
        self.cmd = [self.browser_info.path, "-no-remote",
                    "-profile", self.profile_dir]

class FirefoxWin(FirefoxMixin, BrowserWin):
    directory = "Mozilla Firefox"

    def __init__(self, browser_info):
        super(FirefoxWin, self).__init__(browser_info)


class FirefoxLin(FirefoxMixin, BrowserLin):
    executable = "firefox"
    appname = "Firefox"

    def __init__(self, browser_info):
        super(FirefoxLin, self).__init__(browser_info)

        assert browser_info.path.endswith(self.process_name)

        # Official Firefox builds launch the firefox-bin process from the
        # firefox scripts.
        official_executable = os.path.join(os.path.dirname(browser_info.path),
                                           "firefox-bin")
        if os.path.isfile(official_executable):
            self.process_name = "firefox-bin"


class FirefoxMac(FirefoxMixin, BrowserMac):
    process_name = "firefox-bin"
    # TODO
