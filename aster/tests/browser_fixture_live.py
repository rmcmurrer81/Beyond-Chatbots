"""Required real-engine fixture qualification. No skips or system-browser fallback.

Run explicitly; ordinary unittest discovery intentionally excludes this file.
"""
import unittest

from aster.browser_integration import BrowserIntegrationError, FixtureBrowser, HandoffRequired
from aster.browser_fixture import ORIGIN


class LiveBrowserFixtureTests(unittest.TestCase):
    def setUp(self):
        self.browser = FixtureBrowser(approved_origin=ORIGIN).__enter__()

    def tearDown(self):
        self.browser.close()

    def confirm(self, plan):
        return self.browser.confirm(plan['token'], action=plan['action'],
            target=plan['target'], value=plan['value'], approved=True)

    def test_real_engine_read_links_fill_and_one_use_submission(self):
        home = self.browser.read()
        self.assertEqual(len(home['links']), 4)
        self.assertTrue(all(link['click_supported'] for link in home['links']))
        self.confirm(self.browser.preview('click', 'form-link'))
        self.confirm(self.browser.preview('fill', 'project-name', 'Demo project + one *~'))
        form = self.browser.read()
        self.assertEqual(form['fields'][0]['value'], 'Demo project + one *~')
        plan = self.browser.preview('click', 'form-submit')
        self.assertIn('0 USD', plan['details']['charges'])
        self.assertIn('No account', plan['details']['terms'])
        result = self.confirm(plan)
        self.assertIn('Fixture submitted', result['snapshot']['text'])
        with self.assertRaisesRegex(BrowserIntegrationError, 'already_used'):
            self.confirm(plan)

    def test_malicious_fixture_is_data_and_all_links_denied(self):
        before = self.browser._requests
        result = self.browser.navigate('/attacks')
        self.assertIn('UNTRUSTED TEST TEXT', result['text'])
        self.assertFalse(any(link['click_supported'] for link in result['links']))
        self.assertTrue(all(field['value'] == '[REDACTED]' for field in result['fields']))
        for link in result['links']:
            with self.subTest(target=link['target']), self.assertRaises(BrowserIntegrationError):
                self.browser.preview('click', link['target'])
        self.assertEqual(len(self.browser._context.pages), 1)
        self.assertIsNone(self.browser._pending)
        # Page JS is disabled and all browser networking is offline/routed, never continued.
        self.assertGreaterEqual(self.browser._requests, before + 1)

    def test_browser_initiated_external_and_redirect_navigation_is_blocked(self):
        # Direct engine calls are used only by this adversarial test, never exposed by the adapter.
        # Aborted private navigations can asynchronously commit Chromium's error page.
        # Inspect the denial, then discard that session rather than racing same-tab recovery.
        self.browser.close()
        blocked = 0
        for destination in ('https://example.com/', ORIGIN + '/redirect', 'http://127.0.0.1:80/'):
            with self.subTest(destination=destination), FixtureBrowser(approved_origin=ORIGIN) as probe:
                before = probe._blocked_requests
                with self.assertRaises(Exception):
                    probe._page.goto(destination, timeout=1000)
                self.assertGreater(probe._blocked_requests, before)
                blocked += probe._blocked_requests - before
        self.assertGreaterEqual(blocked, 3)

    def test_signup_login_secret_entry_and_submission_unavailable(self):
        for path, secret, submit in [('/signup', 'signup-password', 'signup-submit'),
                                    ('/login', 'login-password', 'login-submit')]:
            result = self.browser.navigate(path)
            self.assertEqual(result['live_account_actions'], 'unavailable')
            with self.assertRaises(HandoffRequired):
                self.browser.preview('fill', secret, 'never-input-this')
            with self.assertRaises(HandoffRequired):
                self.browser.preview('click', submit)
            self.assertNotIn('never-input-this', str(self.browser.read()))

    def test_navigation_invalidates_old_confirmation(self):
        self.browser.navigate('/form')
        plan = self.browser.preview('fill', 'project-name', 'demo')
        self.browser.navigate('/login')
        with self.assertRaises(BrowserIntegrationError):
            self.confirm(plan)


if __name__ == '__main__':
    unittest.main()
