"""Explicit, reviewed HTTP(S) handoff to the OS default browser.

No page fetching, prompt parsing, saved profile access, queue/replay, or model.
Plans live only in memory. The launcher never uses a shell command string or
the BROWSER environment variable, and cannot attest that a page loaded.
"""
import hashlib
import ipaddress
import json
import os
import re
import subprocess
import sys
import unicodedata
from urllib.parse import parse_qsl, quote, unquote, urlsplit, urlunsplit

MAX_URL = 4096
MAX_QUERY = 1000
SEARCH_BASE = 'https://www.google.com/search?q='
_SECRET_KEYS = {'password', 'passwd', 'pwd', 'token', 'accesstoken', 'refreshtoken',
                'idtoken', 'apikey', 'key', 'secret', 'clientsecret', 'authorization',
                'auth', 'session', 'sessionid', 'sid', 'code', 'assertion', 'signature',
                'credential', 'credentials', 'sig', 'sastoken'}


def _text(value, limit, label):
    if type(value) is not str or not value or len(value) > limit:
        raise ValueError(label + ' must be nonempty text within the length limit')
    if any(unicodedata.category(char).startswith('C') for char in value):
        raise ValueError(label + ' cannot contain control, invisible, or invalid characters')
    return value


def validate_url(value):
    """Conservative absolute URL syntax check, not a site trust/safety verdict."""
    _text(value, MAX_URL, 'URL')
    if not value.isascii() or any(c.isspace() or c in '\\"<>`{}|^' for c in value):
        raise ValueError('Use an ASCII HTTP(S) URL with spaces and Unicode percent-encoded')
    if re.search(r'%(?![0-9a-fA-F]{2})', value):
        raise ValueError('URL has a malformed percent escape')
    # Browsers and servers decode escapes differently. Reject encoded controls
    # and structural backslashes, including nested encodings, before the OS
    # sees the URL. Encoded query backslashes are harmless literal search data.
    decoded = value
    structural = value.split('?', 1)[0].split('#', 1)[0]
    for _ in range(len(value)):
        try:
            next_value = unquote(decoded, errors='strict')
            structural = unquote(structural, errors='strict')
        except UnicodeError as exc:
            raise ValueError('URL has invalid encoded text') from exc
        if '\\' in structural or any(unicodedata.category(c).startswith('C') for c in next_value):
            raise ValueError('URL cannot contain encoded controls or backslashes')
        if next_value == decoded:
            break
        decoded = next_value
    try:
        parsed = urlsplit(value)
        host, port = parsed.hostname, parsed.port
    except ValueError as exc:
        raise ValueError('URL host or port is malformed') from exc
    if parsed.scheme not in {'http', 'https'} or not parsed.netloc or not host:
        raise ValueError('Only absolute http:// or https:// URLs are supported')
    if parsed.username is not None or parsed.password is not None or '@' in parsed.netloc:
        raise ValueError('Credential-bearing URLs are forbidden; sign in manually in the browser')
    if '%' in parsed.netloc or parsed.netloc.endswith(':') or port == 0:
        raise ValueError('URL host or port is malformed')
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        if ':' in host or len(host) > 253 or not all(
                re.fullmatch(r'[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?', part)
                for part in host.split('.')):
            raise ValueError('URL host is malformed')
        # WHATWG browsers treat a numeric final label (including bare "0x")
        # as IPv4. Only the canonical addresses accepted above are supported.
        if re.fullmatch(r'(?:0x[0-9a-f]*|[0-9]+)', host.split('.')[-1], re.IGNORECASE):
            raise ValueError('Use an unambiguous dotted IPv4 address')
        netloc = host.lower()
    else:
        netloc = '[' + str(address) + ']' if address.version == 6 else str(address)
    if port is not None:
        netloc += ':' + str(port)
    # Prevent common credential and signed-login URL formats from being passed
    # around as ordinary source links. This is not general secret detection.
    for component in (parsed.query, parsed.fragment, urlsplit(decoded).query, urlsplit(decoded).fragment):
        for key, _ in parse_qsl(component.replace(';', '&'), keep_blank_values=True):
            key = re.sub('[^a-z0-9]', '', key.lower())
            if key in _SECRET_KEYS or key.endswith(('token', 'secret', 'password', 'signature', 'credential')):
                raise ValueError('URL contains a credential-like parameter; use a public source URL')
    return urlunsplit((parsed.scheme, netloc, parsed.path or '/', parsed.query, parsed.fragment))


def _search_url(value):
    _text(value, MAX_QUERY, 'Search query')
    if not value.strip():
        raise ValueError('Search query cannot be blank')
    url = SEARCH_BASE + quote(value, safe='')
    if len(url) > MAX_URL:
        raise ValueError('Encoded search URL exceeds the length limit; shorten the query')
    return url


def _validate_search_url(url):
    # Query text is data, not another URL. A literal "%0A" or "&code=example"
    # must stay safely percent-encoded instead of being reinterpreted by the
    # general source-URL credential/recursive-escape policy.
    if type(url) is not str or not url.startswith(SEARCH_BASE):
        raise ValueError('Generated search must use the fixed search destination')
    try:
        query = unquote(url[len(SEARCH_BASE):], errors='strict')
    except UnicodeError as exc:
        raise ValueError('Generated search contains invalid encoding') from exc
    if _search_url(query) != url:
        raise ValueError('Generated search URL changed after encoding')
    return url


def plan(kind, value):
    if kind not in {'url', 'search', 'source'}:
        raise ValueError('Choose url, search, or source')
    if kind == 'search':
        url = _search_url(value)
    else:
        url = validate_url(value)
    fields = {'kind': kind, 'url': url}
    digest = hashlib.sha256(json.dumps(fields, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    return {**fields, 'plan_sha256': digest, 'status': 'review_required',
            'source_verification': 'URL syntax only; owner must verify the destination',
            'message': 'Review the exact URL before opening. Your default browser may send cookies or use an existing '
                       'signed-in session. Opening can contact this site and its redirects. Aster does not read the '
                       'page or verify connectivity, page contents, or trustworthiness.',
            'search_provider': 'Google' if kind == 'search' else None,
            'private_context_added': False, 'page_load_verified': False}


def status():
    return {'available': sys.platform in {'win32', 'linux', 'darwin'},
            'mode': 'explicit_reviewed_default_browser_handoff',
            'platform': sys.platform, 'browser_installation_verified': False,
            'page_reading': False, 'form_control': False, 'automatic_opening': False,
            'persisted_requests': False, 'page_load_verified': False,
            'message': 'An explicit local URL/search/source review is required. Launching is not proof that a page loaded.'}


def _launch(url, *, generated_search=False):
    """Fixed platform adapters only. Returns an outcome, never a page claim."""
    # Revalidate at the final OS boundary, including direct internal callers.
    if type(generated_search) is not bool:
        raise ValueError('Invalid browser launch mode')
    url = _validate_search_url(url) if generated_search else validate_url(url)
    try:
        if sys.platform == 'win32':
            os.startfile(url, 'open')
        elif sys.platform in {'linux', 'darwin'}:
            if sys.platform == 'linux' and not (os.environ.get('DISPLAY') or os.environ.get('WAYLAND_DISPLAY')):
                return 'launch_failed', 'No local graphical browser session is available.'
            executable = '/usr/bin/xdg-open' if sys.platform == 'linux' else '/usr/bin/open'
            # No PATH lookup and no BROWSER override. xdg-open delegates only to
            # the configured desktop association, not an arbitrary input command.
            environment = dict(os.environ)
            environment.pop('BROWSER', None)
            environment['PATH'] = '/usr/bin:/bin'
            result = subprocess.run([executable, url], shell=False, stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10, check=False, env=environment)
            if result.returncode != 0:
                return 'launch_failed', 'The default-browser launcher reported a failure. Check the browser association.'
        else:
            return 'launch_failed', 'This platform has no supported default-browser adapter.'
    except subprocess.TimeoutExpired:
        return 'launch_unknown', 'The launcher timed out; a browser may already be open. Check it before retrying.'
    except (OSError, AttributeError, NotImplementedError):
        return 'launch_failed', 'The default browser could not be launched. Check the installed browser and desktop association.'
    return 'launch_requested', 'The OS accepted the browser request. Page loading and Internet access are unverified.'


def open_reviewed(kind, value, *, approved=False, expected_sha256=None):
    reviewed = plan(kind, value)
    if approved is not True or expected_sha256 != reviewed['plan_sha256']:
        raise ValueError('Explicit approval and the exact reviewed plan SHA-256 are required')
    outcome, message = (_launch(reviewed['url'], generated_search=True) if kind == 'search'
                        else _launch(reviewed['url']))
    return {'kind': kind, 'url': reviewed['url'], 'status': outcome, 'message': message,
            'page_load_verified': False, 'internet_access_verified': False,
            'private_context_added': False, 'retry_automatically': False}
