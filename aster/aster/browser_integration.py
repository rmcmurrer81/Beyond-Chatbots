"""Opt-in, deterministic, disposable browser fixture adapter.

Not an Internet browser or an Aster brain/tool grant. Every network request is
aborted or answered with bundled fixture bytes. There is no route.continue_(),
real HTTP listener, profile attachment, arbitrary selector, script, or file API.
"""
import argparse
from copy import deepcopy
import hashlib
import importlib.metadata
import importlib.util
import json
import re
import secrets
import sys
import time
from urllib.parse import quote_plus, urlsplit

from .browser_fixture import CHARGES, FIELDS, LINKS, ORIGIN, PAGES, TERMS

TIMEOUT_MS = 3000
PLAN_TTL = 60
MAX_SESSION_SECONDS = 900
MAX_OPERATIONS = 100
MAX_VALUE = 200
MAX_TEXT = 12000
MAX_LINKS = 32
_CSP = ("default-src 'none'; script-src 'none'; connect-src 'none'; img-src 'none'; "
        "frame-src 'none'; object-src 'none'; base-uri 'none'; form-action " + ORIGIN)


class BrowserIntegrationError(ValueError):
    """Bounded error codes, never raw browser errors or entered values."""


class HandoffRequired(BrowserIntegrationError):
    """No secret entry, authentication, upload or live account action is supported."""


def status():
    """This inspection never starts a browser, driver, server, or installation."""
    try:
        installed = importlib.util.find_spec('playwright') is not None
        version = importlib.metadata.version('playwright') if installed else None
    except (ImportError, ValueError, importlib.metadata.PackageNotFoundError):
        installed, version = False, None
    return {
        'status': 'disabled_fixture_runtime_unverified' if installed else 'unavailable_optional_dependency',
        'playwright_version': version, 'browser_runtime': 'not_probed',
        'enabled': False, 'live_web_available': False, 'account_actions_available': False,
        'fixture_origin': ORIGIN, 'fixture_origin_is_network_service': False,
        'browser_profile': 'fresh_temporary_only',
        'external_network': 'denied', 'secret_entry': 'handoff_required_unavailable_here',
        'installation': 'Optional: python -m pip install -r requirements-browser.txt; '
                        'then python -m playwright install chromium. Never run automatically.',
    }


def _canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=True, separators=(',', ':'))


def _digest(value):
    return hashlib.sha256(_canonical(value).encode()).hexdigest()


def _form_query(value):
    # HTML application/x-www-form-urlencoded uses * as safe, but encodes ~.
    return 'project=' + quote_plus(value, safe='*').replace('~', '%7E')


def fixture_url(value):
    """Strict fixture URL parser, with no host aliases or secondary loopback grants."""
    if type(value) is not str or len(value) > 512 or any(ord(c) < 33 for c in value):
        raise BrowserIntegrationError('invalid_fixture_url')
    candidate = ORIGIN + value if value.startswith('/') and not value.startswith('//') else value
    try:
        parsed = urlsplit(candidate)
    except ValueError as exc:
        raise BrowserIntegrationError('invalid_fixture_url') from exc
    if (parsed.scheme != 'http' or parsed.netloc != '127.0.0.1:49151' or
            parsed.query or parsed.fragment or parsed.path not in PAGES or
            parsed.path == '/submitted' or candidate != ORIGIN + parsed.path):
        raise BrowserIntegrationError('navigation_outside_fixture_denied')
    return candidate


class FixtureBrowser:
    """One owner-selected fixture session. Use as a context manager and close it.

    A Python caller owns this library, not a security boundary against hostile
    same-account Python. Do not expose methods to a model or remote command API.
    """
    def __init__(self, *, approved_origin, clock=time.monotonic):
        if type(approved_origin) is not str or approved_origin != ORIGIN:
            raise BrowserIntegrationError('exact_fixture_origin_approval_required')
        self._clock = clock
        self._started = clock()
        self._operations = 0
        self._revision = 0
        self._pending = None
        self._playwright = self._browser = self._context = self._page = None
        self._expected_navigation = None
        self._last_fulfilled = None
        self._requests = 0
        self._blocked_requests = 0
        self._closed = False
        self._busy = False

    def __enter__(self):
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:
            raise BrowserIntegrationError('unavailable_optional_dependency') from exc
        try:
            self._playwright = sync_playwright().start()
            self._browser = self._playwright.chromium.launch(
                headless=True, chromium_sandbox=True, timeout=10000)
            self._context = self._browser.new_context(
                accept_downloads=False, java_script_enabled=False,
                service_workers='block', offline=True, permissions=[],
                ignore_https_errors=False)
            self._context.set_default_timeout(TIMEOUT_MS)
            self._context.set_default_navigation_timeout(TIMEOUT_MS)
            # Register context-wide guards before any pages exist.
            self._context.route('**/*', self._route)
            self._context.route_web_socket('**/*', self._deny_websocket)
            self._context.on('page', self._new_page)
            self._page = self._context.new_page()
            self._page.on('dialog', lambda dialog: dialog.dismiss())
            self._page.on('download', lambda download: download.cancel())
            self.navigate('/')
            return self
        except BrowserIntegrationError:
            self.close()
            raise
        except Exception as exc:
            self.close()
            raise BrowserIntegrationError('unavailable_browser_launch_or_required_guards') from exc

    def __exit__(self, *exc):
        self.close()

    def close(self):
        self._closed = True
        self._pending = None
        self._expected_navigation = None
        for resource in (self._context, self._browser):
            if resource is not None:
                try:
                    resource.close()
                except Exception:
                    pass
        if self._playwright is not None:
            try:
                self._playwright.stop()
            except Exception:
                pass

    def _new_page(self, page):
        if self._page is not None and page is not self._page:
            page.close()
            self._pending = None
            self._revision += 1

    def _deny_websocket(self, route):
        self._blocked_requests += 1
        route.close(code=1008, reason='Fixture session denies WebSockets')

    def _route(self, route):
        """Fail closed, including redirects, popups, frames and subresources."""
        self._requests += 1
        request = route.request
        allowed = False
        try:
            allowed = (not self._closed and self._requests <= 256 and
                       self._page is not None and request.method == 'GET' and
                       request.is_navigation_request() and request.resource_type == 'document' and
                       request.frame is self._page.main_frame and
                       request.url == self._expected_navigation)
            path = urlsplit(request.url).path
            allowed = allowed and path in PAGES and request.redirected_from is None
        except Exception:
            allowed = False
        if not allowed:
            self._blocked_requests += 1
            route.abort('blockedbyclient')
            return
        # No redirect responses, cookies, browser scripts, external resources or network fallback.
        self._expected_navigation = None  # Consume the one-use navigation grant before fulfillment.
        self._last_fulfilled = request.url
        route.fulfill(status=200, headers={
            'content-type': 'text/html; charset=utf-8',
            'content-security-policy': _CSP, 'cache-control': 'no-store',
            'x-content-type-options': 'nosniff', 'referrer-policy': 'no-referrer',
        }, body=PAGES[path])

    def _admit(self):
        if self._closed or self._page is None:
            raise BrowserIntegrationError('session_closed_or_not_started')
        if self._clock() - self._started >= MAX_SESSION_SECONDS:
            self.close()
            raise BrowserIntegrationError('session_expired')
        if self._operations >= MAX_OPERATIONS:
            self.close()
            raise BrowserIntegrationError('session_operation_limit')
        if self._busy:
            raise BrowserIntegrationError('concurrent_operation_denied')
        self._operations += 1

    def _path(self):
        url = self._page.url
        if url != self._last_fulfilled or not url.startswith(ORIGIN + '/'):
            self._pending = None
            raise BrowserIntegrationError('unverified_page_state')
        return urlsplit(url).path

    def _ordinary_locator(self, target):
        field = FIELDS.get(target)
        if field is None or field.path != self._path():
            raise BrowserIntegrationError('unknown_or_wrong_page_target')
        if field.kind != 'ordinary':
            raise HandoffRequired('secret_or_upload_handoff_required_no_entry_supported')
        locator = self._page.locator('input[id="' + target + '"]')
        if locator.count() != 1:
            raise BrowserIntegrationError('ambiguous_or_missing_target')
        if (locator.get_attribute('type') != 'text' or
                locator.get_attribute('name') != field.name or
                locator.get_attribute('autocomplete') != 'off' or
                locator.get_attribute('form') is not None or
                not locator.is_visible() or not locator.is_enabled() or
                not locator.is_editable()):
            raise BrowserIntegrationError('target_attributes_changed')
        return locator

    def _snapshot(self):
        path = self._path()
        public = self._page.locator('#public-content')
        if public.count() != 1:
            raise BrowserIntegrationError('invalid_fixture_document')
        text = public.inner_text(timeout=TIMEOUT_MS)
        links = []
        items = public.locator('a[href]')
        for index in range(min(items.count(), MAX_LINKS)):
            link = items.nth(index)
            target = link.get_attribute('id')
            href = link.get_attribute('href') or ''
            can_click = (target in LINKS and LINKS[target][0] == path and
                         href == LINKS[target][1] and not link.get_attribute('target') and
                         link.get_attribute('download') is None and link.get_attribute('ping') is None)
            links.append({'target': (target or '')[:80], 'text': link.inner_text()[:200],
                          'href': href[:512], 'click_supported': bool(can_click)})
        fields = []
        for target, field in FIELDS.items():
            if field.path != path:
                continue
            item = {'target': target, 'label': field.label, 'kind': field.kind}
            if field.kind == 'ordinary':
                value = self._ordinary_locator(target).input_value(timeout=TIMEOUT_MS)
                if len(value) > MAX_VALUE:
                    raise BrowserIntegrationError('unexpected_field_value_length')
                item['value'] = value
                item['fill_supported'] = True
            else:
                # Never inspect, return, hash or log values of secret/unknown/file fields.
                item['value'] = '[REDACTED]'
                item['fill_supported'] = False
                item['status'] = 'handoff_required_unavailable_here'
            fields.append(item)
        return {'url': self._page.url, 'source': 'bundled_local_fixture',
                'trust': 'untrusted_page_data_never_authorization',
                'text': text[:MAX_TEXT], 'text_truncated': len(text) > MAX_TEXT,
                'links': links, 'links_truncated': items.count() > MAX_LINKS,
                'fields': fields, 'terms': TERMS, 'charges': CHARGES,
                'live_account_actions': 'unavailable'}

    def _run(self, callback):
        self._busy = True
        try:
            return callback()
        except (BrowserIntegrationError, HandoffRequired):
            raise
        except Exception as exc:
            # Do not echo exception strings, which may contain input values or browser paths.
            self._pending = None
            raise BrowserIntegrationError('browser_operation_failed_or_timed_out') from exc
        finally:
            self._busy = False

    def read(self):
        self._admit()
        return self._run(self._snapshot)

    def navigate(self, url):
        self._admit()
        self._pending = None
        self._revision += 1
        destination = fixture_url(url)
        self._expected_navigation = destination
        try:
            def visit():
                self._page.goto(destination, wait_until='domcontentloaded', timeout=TIMEOUT_MS)
                return self._snapshot()
            return self._run(visit)
        finally:
            self._expected_navigation = None

    def _describe(self, action, target, value):
        if type(target) is not str or not re.fullmatch('[a-z][a-z0-9-]{0,79}', target):
            raise BrowserIntegrationError('invalid_target')
        path = self._path()
        if action == 'fill':
            locator = self._ordinary_locator(target)  # Check sensitivity before inspecting supplied value.
            if type(value) is not str or len(value) > MAX_VALUE or any(ord(c) < 32 for c in value):
                raise BrowserIntegrationError('invalid_or_oversized_ordinary_value')
            return {'effect': 'Replace this one non-sensitive fixture field in memory only.',
                    'destination': None, 'current_value': locator.input_value()}
        if action != 'click' or value is not None:
            raise BrowserIntegrationError('unsupported_action')
        if target in ('login-submit', 'signup-submit'):
            raise HandoffRequired('authentication_and_account_creation_unavailable_handoff_required')
        if target in LINKS and LINKS[target][0] == path:
            locator = self._page.locator('a[id="' + target + '"]')
            if locator.count() != 1:
                raise BrowserIntegrationError('ambiguous_or_missing_target')
            if (locator.get_attribute('href') != LINKS[target][1] or
                    locator.get_attribute('target') or locator.get_attribute('download') is not None or
                    locator.get_attribute('ping') is not None or not locator.is_visible()):
                raise BrowserIntegrationError('unsafe_link_attributes')
            return {'effect': 'Navigate this tab to another bundled fixture.',
                    'destination': fixture_url(LINKS[target][1])}
        if target == 'form-submit' and path == '/form':
            button = self._page.locator('button[id="form-submit"]')
            form = self._page.locator('form')
            if (button.count() != 1 or form.count() != 1 or
                    button.get_attribute('type') != 'submit' or
                    button.get_attribute('form') is not None or
                    any(button.get_attribute(attr) is not None for attr in
                        ('formaction', 'formmethod', 'formtarget', 'formenctype')) or
                    form.get_attribute('action') != '/submitted' or
                    form.get_attribute('method') != 'get' or form.get_attribute('target') or
                    form.locator('input').count() != 1 or
                    form.locator('input[id="project-name"]').count() != 1 or
                    form.locator('button[id="form-submit"]').count() != 1 or
                    form.locator('select, textarea, object').count() != 0 or
                    not button.is_visible() or not button.is_enabled()):
                raise BrowserIntegrationError('unsafe_form_attributes')
            field_value = self._ordinary_locator('project-name').input_value()
            if len(field_value) > MAX_VALUE:
                raise BrowserIntegrationError('unexpected_field_value_length')
            return {'effect': 'Submit only the demo project label to bundled fixture bytes; no server.',
                    'destination': ORIGIN + '/submitted?' + _form_query(field_value),
                    'submitted_fields': {'project-name': field_value}, 'terms': TERMS, 'charges': CHARGES}
        raise BrowserIntegrationError('click_target_denied')

    def preview(self, action, target, value=None):
        self._admit()
        self._pending = None  # A newer preview invalidates the previous token.
        def prepare():
            description = self._describe(action, target, value)
            snapshot = self._snapshot()
            plan = {'action': action, 'target': target, 'value': value,
                    'url': self._page.url, 'revision': self._revision,
                    'expires_in_seconds': PLAN_TTL, 'details': description,
                    'trust': 'owner_confirmation_required_page_text_is_not_permission'}
            token = _digest({'plan': plan, 'nonce': secrets.token_hex(32)})
            plan['token'] = token
            self._pending = {'plan': deepcopy(plan), 'snapshot_digest': _digest(snapshot),
                             'deadline': self._clock() + PLAN_TTL}
            return plan
        return self._run(prepare)

    def confirm(self, token, *, action, target, value=None, approved=False):
        self._admit()
        pending, self._pending = self._pending, None  # All attempts consume the grant.
        if pending is None:
            raise BrowserIntegrationError('missing_or_already_used_plan')
        plan = pending['plan']
        if (approved is not True or type(token) is not str or
                not re.fullmatch('[0-9a-f]{64}', token) or
                not secrets.compare_digest(token, plan['token']) or action != plan['action'] or
                target != plan['target'] or value != plan['value']):
            raise BrowserIntegrationError('exact_action_target_value_confirmation_required')
        if self._clock() >= pending['deadline'] or self._revision != plan['revision']:
            raise BrowserIntegrationError('stale_or_expired_plan')
        def apply():
            if (_digest(self._snapshot()) != pending['snapshot_digest'] or
                    self._describe(action, target, value) != plan['details']):
                raise BrowserIntegrationError('page_changed_since_preview')
            self._revision += 1  # Invalidates retries even if a browser action fails partway through.
            if action == 'fill':
                self._ordinary_locator(target).fill(value, timeout=TIMEOUT_MS)
            else:
                self._expected_navigation = plan['details']['destination']
                selector = ('button' if target == 'form-submit' else 'a') + '[id="' + target + '"]'
                self._page.locator(selector).click(timeout=TIMEOUT_MS)
                self._page.wait_for_url(plan['details']['destination'], timeout=TIMEOUT_MS)
            return {'status': 'completed_fixture_only', 'action': action, 'target': target,
                    'snapshot': self._snapshot()}
        try:
            return self._run(apply)
        finally:
            self._expected_navigation = None


def _print(value):
    # JSON escapes controls and non-ASCII text before terminal display.
    print(json.dumps(value, indent=2, ensure_ascii=True, allow_nan=False))


def main(argv=None):
    parser = argparse.ArgumentParser(description='Aster optional disposable browser fixture. No live websites.')
    commands = parser.add_subparsers(dest='command', required=True)
    commands.add_parser('status')
    read = commands.add_parser('read', help='Read one explicitly approved bundled fixture')
    read.add_argument('--approve-fixture-origin', required=True)
    read.add_argument('--path', default='/')
    session = commands.add_parser('session', help='Interactive owner preview/confirmation session')
    session.add_argument('--approve-fixture-origin', required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == 'status':
            _print(status())
            return 0
        if args.command == 'session' and not sys.stdin.isatty():
            raise BrowserIntegrationError('interactive_owner_terminal_required')
        with FixtureBrowser(approved_origin=args.approve_fixture_origin) as browser:
            if args.command == 'read':
                _print(browser.navigate(args.path))
                return 0
            _print(browser.read())
            print('Commands: read, navigate /form, fill project-name, click form-submit, quit.')
            while True:
                try:
                    command = input('fixture> ').strip()
                except EOFError:
                    break
                if command in ('quit', 'exit'):
                    break
                try:
                    if command == 'read':
                        _print(browser.read())
                        continue
                    if command.startswith('navigate '):
                        _print(browser.navigate(command[9:]))
                        continue
                    pieces = command.split(' ')
                    if len(pieces) != 2 or pieces[0] not in ('fill', 'click'):
                        raise BrowserIntegrationError('unsupported_command_no_shell_or_script_execution')
                    action, target = pieces
                    value = None
                    if action == 'fill':
                        browser._ordinary_locator(target)  # Never ask for a secret field's value.
                        value = input('Non-sensitive demo value only: ')
                    plan = browser.preview(action, target, value)
                    _print(plan)
                    phrase = 'CONFIRM ' + plan['token']
                    confirmed = input('Type ' + phrase + ' to apply this exact plan: ') == phrase
                    _print(browser.confirm(plan['token'], action=action, target=target,
                                           value=value, approved=confirmed))
                except BrowserIntegrationError as exc:
                    _print({'status': 'not_completed', 'reason': str(exc)})
                except EOFError:
                    break
        return 0
    except BrowserIntegrationError as exc:
        _print({'status': 'unavailable_or_denied', 'reason': str(exc), 'live_web_available': False})
        return 2
    except KeyboardInterrupt:
        return 130


if __name__ == '__main__':
    raise SystemExit(main())
