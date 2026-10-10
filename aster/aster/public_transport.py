"""One anonymous, bounded public IPv4 HTTP(S) GET; all output is untrusted data.

No browser, cookies, proxy, redirects, retries, scripts, downloads or credentials.
Identity Content-Length and close-delimited bodies only. Transfer-Encoding
(including chunked) is deliberately unsupported in this conservative version.
Use only behind the disposable-worker supervisor: OS DNS resolution cannot be
interrupted reliably by a socket timeout. This module's five-second deadline
starts AFTER DNS; the supervisor owns the hard total deadline including DNS.

References: https://docs.python.org/3/library/http.client.html
https://docs.python.org/3/library/socket.html
https://docs.python.org/3/library/ssl.html
https://www.iana.org/assignments/iana-ipv4-special-registry/
https://www.iana.org/assignments/special-use-domain-names/
"""
import hashlib
import http.client
import io
import ipaddress
import os
import re
import socket
import ssl
import time
import unicodedata
from datetime import datetime, timezone
from html.parser import HTMLParser
from urllib.parse import parse_qsl, unquote, urljoin, urlsplit, urlunsplit

from .browser_actions import validate_url

MAX_BODY = 1024 * 1024
MAX_WIRE = MAX_BODY + 65536
MAX_HEADERS = 32768
MAX_HEADER_LINES = 65
MAX_LINE = 8192
MAX_TEXT = 12000
MAX_TITLE = 256
MAX_LINKS = 32
MAX_LINK_TEXT = 160
IO_DEADLINE = 5.0
# Block all special-purpose blocks, even globally reachable exceptions, so the
# policy does not change with the interpreter's ipaddress registry version.
_SPECIAL_NETS = tuple(ipaddress.IPv4Network(value) for value in (
    '0.0.0.0/8', '10.0.0.0/8', '100.64.0.0/10', '127.0.0.0/8',
    '169.254.0.0/16', '172.16.0.0/12', '192.0.0.0/24', '192.0.2.0/24',
    '192.31.196.0/24', '192.52.193.0/24', '192.88.99.0/24', '192.168.0.0/16',
    '192.175.48.0/24', '198.18.0.0/15', '198.51.100.0/24', '203.0.113.0/24',
    '224.0.0.0/4', '240.0.0.0/4'))
_SPECIAL_NAMES = frozenset(('alt', 'arpa', 'example', 'invalid', 'local', 'localhost', 'onion', 'test', 'internal',
    'intranet', 'corp', 'home', 'lan', 'localdomain'))
_PLATFORM_IPS = frozenset(('168.63.129.16',))
_SECRET_KEYS = frozenset(('awsaccesskeyid', 'accesskey', 'xamzalgorithm', 'xamzdate',
    'xamzexpires', 'xamzsignedheaders', 'xgoogalgorithm', 'xgoogdate', 'xgoogexpires',
    'xgoogsignedheaders', 'password', 'passwd', 'pwd', 'token', 'apikey', 'secret',
    'auth', 'authorization', 'session', 'sessionid', 'credential', 'signature'))
_CODES = frozenset(('invalid_url', 'nonpublic_host', 'nonpublic_address',
    'ipv6_unsupported', 'dns_failed', 'dns_no_ipv4', 'dns_invalid', 'peer_mismatch',
    'tls_failed', 'timeout', 'connection_failed', 'invalid_response', 'header_limit',
    'wire_limit', 'body_limit', 'incomplete_body', 'unsupported_framing',
    'unsupported_encoding', 'unsupported_media', 'unsupported_attachment',
    'unsupported_status', 'redirect_review_required', 'redirect_blocked',
    'http_error', 'ok'))


class PublicFetchError(ValueError):
    """Only a bounded static code crosses the worker boundary."""
    def __init__(self, code):
        self.code = code if code in _CODES else 'connection_failed'
        super().__init__(self.code)


def _public_address(value):
    try:
        address = ipaddress.ip_address(value)
    except ValueError:
        raise PublicFetchError('dns_invalid') from None
    if address.version != 4:
        raise PublicFetchError('ipv6_unsupported')
    if (not address.is_global or address.is_multicast or address.is_reserved
            or str(address) in _PLATFORM_IPS
            or any(address in network for network in _SPECIAL_NETS)):
        raise PublicFetchError('nonpublic_address')
    return str(address)


def validate_public_url(value):
    """Syntax and public-name/literal-IP policy only; no DNS or network I/O."""
    try:
        normalized = validate_url(value)
        parsed = urlsplit(normalized)
        if parsed.port not in (None, 443 if parsed.scheme == 'https' else 80):
            raise PublicFetchError('invalid_url')
        decoded = normalized
        for _ in range(len(normalized)):
            next_value = unquote(decoded, errors='strict')
            if '\\' in next_value:
                raise PublicFetchError('invalid_url')
            if next_value == decoded:
                break
            decoded = next_value
        expanded = urlsplit(decoded)
        for component in (expanded.query, expanded.fragment, expanded.path.replace('/', '&')):
            for key, _ in parse_qsl(component.replace(';', '&'), keep_blank_values=True):
                key = re.sub('[^a-z0-9]', '', key.lower())
                if key in _SECRET_KEYS or key.endswith(('token', 'secret', 'password', 'credential', 'signature')):
                    raise PublicFetchError('invalid_url')
        host = parsed.hostname
        try:
            ipaddress.ip_address(host)
        except ValueError:
            if '.' not in host or any(host == name or host.endswith('.' + name) for name in _SPECIAL_NAMES):
                raise PublicFetchError('nonpublic_host')
        else:
            _public_address(host)
        return normalized
    except PublicFetchError:
        raise
    except (ValueError, TypeError, UnicodeError):
        raise PublicFetchError('invalid_url') from None


def _resolve(host, port):
    try:
        ipaddress.ip_address(host)
    except ValueError:
        try:
            # The terminal dot disables resolver search-suffix expansion. Only
            # this call resolves the name; socket.connect receives numeric IPv4.
            answers = socket.getaddrinfo(host + '.', port, socket.AF_INET,
                                         socket.SOCK_STREAM, socket.IPPROTO_TCP)
        except OSError:
            raise PublicFetchError('dns_failed') from None
        if not answers:
            raise PublicFetchError('dns_no_ipv4')
        if len(answers) > 64:
            raise PublicFetchError('dns_invalid')
        addresses = []
        for family, kind, protocol, _, sockaddr in answers:
            if (family != socket.AF_INET or kind != socket.SOCK_STREAM
                    or protocol != socket.IPPROTO_TCP or len(sockaddr) != 2 or sockaddr[1] != port):
                raise PublicFetchError('dns_invalid')
            # Reject the entire answer set if ANY A record is unsafe.
            addresses.append(_public_address(sockaddr[0]))
        return addresses[0]
    return _public_address(host)


def _remaining(deadline):
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise PublicFetchError('timeout')
    return min(IO_DEADLINE, remaining)


def _tls_context():
    # Unlike create_default_context(), this never reads SSLKEYLOGFILE. Load
    # compiled platform CA paths explicitly, never SSL_CERT_FILE/SSL_CERT_DIR.
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    context.set_alpn_protocols(['http/1.1'])
    paths = ssl.get_default_verify_paths()
    cafile = paths.openssl_cafile if paths.openssl_cafile and os.path.isfile(paths.openssl_cafile) else None
    capath = paths.openssl_capath if paths.openssl_capath and os.path.isdir(paths.openssl_capath) else None
    if cafile or capath:
        context.load_verify_locations(cafile=cafile, capath=capath)
    if os.name == 'nt':
        for store in ('ROOT', 'CA'):
            for cert, encoding, trust in ssl.enum_certificates(store):
                if encoding == 'x509_asn' and (trust is True or ssl.Purpose.SERVER_AUTH.oid in trust):
                    context.load_verify_locations(cadata=cert)
    # PROTOCOL_TLS_CLIENT sets CERT_REQUIRED and check_hostname; never weaken.
    return context


class _DeadlineRaw(io.RawIOBase):
    def __init__(self, sock, deadline):
        super().__init__()
        self.sock, self.deadline, self.received = sock, deadline, 0
        # Keep the socket file alive when http.client closes its connection
        # handle for a close-delimited response. SocketIO owns that reference.
        self.file = sock.makefile('rb', buffering=0)

    def readable(self):
        return True

    def readinto(self, buffer):
        self.sock.settimeout(_remaining(self.deadline))
        size = min(len(buffer), MAX_WIRE - self.received + 1)
        count = self.file.readinto(memoryview(buffer)[:size])
        self.received += count
        if self.received > MAX_WIRE:
            raise PublicFetchError('wire_limit')
        return count

    def close(self):
        if not self.closed:
            self.file.close()
        super().close()


class _WireReader:
    """Bound header framing before http.client's standard HTTP parser sees it."""
    def __init__(self, sock, deadline):
        self.stream = io.BufferedReader(_DeadlineRaw(sock, deadline), buffer_size=8192)
        self.header_bytes = self.lines = 0
        self.in_headers = True

    def readline(self, limit=-1):
        line = self.stream.readline(min(MAX_LINE + 1, limit) if limit >= 0 else MAX_LINE + 1)
        if self.in_headers:
            self.lines += 1
            self.header_bytes += len(line)
            if len(line) > MAX_LINE or self.header_bytes > MAX_HEADERS or self.lines > MAX_HEADER_LINES:
                raise PublicFetchError('header_limit')
            if not line.endswith(b'\r\n'):
                raise PublicFetchError('invalid_response')
            if self.lines == 1:
                if not re.fullmatch(rb'HTTP/1\.[01] [2-5][0-9]{2}(?: [\x20-\x7e]*)?\r\n', line):
                    raise PublicFetchError('invalid_response')
            elif line == b'\r\n':
                self.in_headers = False
            elif not re.fullmatch(rb"[!#$%&'*+.^_`|~0-9A-Za-z-]+:[\x20-\x7e\t]*\r\n", line):
                raise PublicFetchError('invalid_response')
        return line

    def read(self, amount=-1):
        return self.stream.read(amount)

    def flush(self):
        self.stream.flush()

    def close(self):
        self.stream.close()


class _ResponseSocket:
    def __init__(self, sock, deadline):
        self.sock, self.deadline = sock, deadline

    def makefile(self, mode):
        if mode != 'rb':
            raise PublicFetchError('invalid_response')
        return _WireReader(self.sock, self.deadline)


class _PinnedConnection(http.client.HTTPConnection):
    def __init__(self, host, port, address, secure, deadline):
        super().__init__(host, port, timeout=IO_DEADLINE)
        self.address, self.secure, self.deadline = address, secure, deadline
        # HTTPResponse only needs makefile; retain stdlib parsing on bounded I/O.
        self.response_class = lambda sock, **kwargs: http.client.HTTPResponse(
            _ResponseSocket(sock, self.deadline), **kwargs)

    def connect(self):
        raw = socket.socket(socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP)
        try:
            raw.settimeout(_remaining(self.deadline))
            raw.connect((self.address, self.port))
            self._verify_peer(raw)
            if self.secure:
                context = _tls_context()
                raw.settimeout(_remaining(self.deadline))
                raw = context.wrap_socket(raw, server_hostname=self.host)
                self._verify_peer(raw)
            raw.settimeout(_remaining(self.deadline))
            self.sock = raw
        except BaseException:
            raw.close()
            raise

    def _verify_peer(self, sock):
        peer = sock.getpeername()
        if len(peer) != 2 or peer[0] != self.address or peer[1] != self.port:
            raise PublicFetchError('peer_mismatch')
        _public_address(peer[0])


def _plain(value):
    # Preserve ordinary whitespace; drop controls, bidi/invisible and invalid
    # Unicode. Strings remain plain text, never trusted markup or instructions.
    return ' '.join(''.join(char if not unicodedata.category(char).startswith('C')
                           or char in '\n\r\t' else ' ' for char in value).split())


def _safe_link(base, href):
    if type(href) is not str or not href or len(href) > 4096:
        return None
    # urljoin strips some controls; validate the supplied reference BEFORE it.
    if any(unicodedata.category(c).startswith('C') or c.isspace() for c in href):
        return None
    try:
        result = validate_public_url(urljoin(base, href))
    except (PublicFetchError, ValueError):
        return None
    original, candidate = urlsplit(base), urlsplit(result)
    if original.scheme == 'https' and candidate.scheme != 'https':
        return None
    if candidate.fragment or href.startswith('#'):
        def document_identity(parts):
            return (parts.scheme, parts.hostname, parts.port or (443 if parts.scheme == 'https' else 80),
                    parts.path, parts.query)
        if document_identity(original) == document_identity(candidate):
            return None
    return result


class _Extractor(HTMLParser):
    _ignored = frozenset(('script', 'style', 'form', 'iframe', 'frame', 'frameset',
        'svg', 'math', 'object', 'embed', 'template', 'noscript', 'textarea',
        'select', 'button', 'canvas', 'audio', 'video'))
    _void = frozenset(('area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input',
        'link', 'meta', 'param', 'source', 'track', 'wbr', 'frame'))

    def __init__(self, source):
        super().__init__(convert_charrefs=True)
        self.source, self.parts, self.title_parts, self.links = source, [], [], []
        self.skip, self.in_title, self.anchor = [], False, None
        self.count = self.title_count = 0
        self.truncated = {'body': False, 'text': False, 'title': False, 'links': False}

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        hidden = 'hidden' in attrs or (attrs.get('aria-hidden') or '').lower() == 'true'
        if self.skip or tag in self._ignored or hidden:
            if tag not in self._void:
                self.skip.append(tag)
            return
        if tag == 'title':
            self.in_title = True
        elif tag == 'a':
            self._finish_anchor()
            target = _safe_link(self.source, attrs.get('href'))
            if target and 'download' not in attrs:
                self.anchor = {'url': target, 'text': ''}

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        # In HTML, a slash does not close a non-void form/script/etc. Suppress
        # malformed ignored subtrees conservatively rather than exposing them.
        if tag in self._void:
            self.handle_endtag(tag)

    def handle_endtag(self, tag):
        if self.skip:
            if tag in self.skip:
                del self.skip[len(self.skip) - 1 - self.skip[::-1].index(tag):]
            return
        if tag == 'title':
            self.in_title = False
        elif tag == 'a':
            self._finish_anchor()

    def _finish_anchor(self):
        if self.anchor:
            if len(self.links) < MAX_LINKS:
                self.anchor['text'] = _plain(self.anchor['text'])[:MAX_LINK_TEXT]
                if not any(item['url'] == self.anchor['url'] for item in self.links):
                    self.links.append(self.anchor)
            else:
                self.truncated['links'] = True
            self.anchor = None

    def handle_data(self, data):
        if self.skip:
            return
        clean = _plain(data)
        if not clean:
            return
        if self.in_title:
            remaining = MAX_TITLE - self.title_count
            piece = (' ' if self.title_parts else '') + clean
            if remaining:
                self.title_parts.append(piece[:remaining])
                self.title_count += min(len(piece), remaining)
            self.truncated['title'] |= len(piece) > remaining
            return
        remaining = MAX_TEXT - self.count
        piece = (' ' if self.parts else '') + clean
        if remaining > 0:
            self.parts.append(piece[:remaining])
            self.count += min(len(piece), remaining)
        self.truncated['text'] |= len(piece) > remaining
        if self.anchor:
            remaining = MAX_LINK_TEXT - len(self.anchor['text'])
            self.anchor['text'] += (' ' + clean)[:max(0, remaining)]


def _extract(body, media, charset, source):
    try:
        decoded = body.decode(charset, errors='strict')
    except UnicodeError:
        raise PublicFetchError('unsupported_encoding') from None
    if media == 'text/plain':
        text = _plain(decoded)
        return '', text[:MAX_TEXT], [], {'body': False, 'text': len(text) > MAX_TEXT,
                                        'links': False, 'title': False}
    parser = _Extractor(source)
    parser.feed(decoded)
    parser.close()
    parser._finish_anchor()
    return (_plain(''.join(parser.title_parts))[:MAX_TITLE],
            _plain(''.join(parser.parts))[:MAX_TEXT], parser.links, parser.truncated)


def _header(response, name):
    values = response.headers.get_all(name, [])
    if len(values) > 1:
        raise PublicFetchError('invalid_response')
    return values[0].strip() if values else None


def fetch_public(url):
    """Fetch exactly one URL. Raises PublicFetchError with a static error code.

    Returned links have passed syntax/name/IP-literal checks, NOT DNS checks;
    any later explicit fetch must revalidate and pin its own public DNS answer.
    A 'read' result means an inert static response, not browser rendering or
    trustworthy content. No hidden request, redirect, or resource is followed.
    """
    requested = validate_public_url(url)
    parsed = urlsplit(requested)
    source = urlunsplit((parsed.scheme, parsed.netloc, parsed.path, parsed.query, ''))
    port = 443 if parsed.scheme == 'https' else 80
    address = _resolve(parsed.hostname, port)
    connection = _PinnedConnection(parsed.hostname, port, address, parsed.scheme == 'https',
                                   time.monotonic() + IO_DEADLINE)
    response = None
    result = {'status': 'unsupported', 'requested_url': requested, 'source_url': source,
        'title': '', 'text': '', 'links': [], 'body_sha256': '',
        'truncated': {'body': False, 'text': False, 'links': False, 'title': False},
        'reason': 'unsupported_status', 'fetched_at': datetime.now(timezone.utc).isoformat(),
        'selected_peer': address, 'tls_verified': False, 'untrusted_content': True,
        'http_status': None}
    try:
        # This is already a validated absolute URL path. urlunsplit with an
        # empty authority can rewrite leading //, changing the selected target.
        target = parsed.path + ('?' + parsed.query if parsed.query else '')
        connection.request('GET', target, headers={'Host': parsed.netloc,
            'Accept': 'text/html, text/plain', 'Accept-Encoding': 'identity',
            'Connection': 'close', 'User-Agent': 'Aster-Public-Reader/1'})
        result['tls_verified'] = parsed.scheme == 'https'
        response = connection.getresponse()
        result['http_status'] = response.status
        # Inspect duplicates before making any status-dependent decisions.
        critical = {name: _header(response, name) for name in ('Content-Length',
            'Transfer-Encoding', 'Content-Encoding', 'Content-Type',
            'Content-Disposition', 'Location', 'Trailer')}
        if 300 <= response.status < 400:
            target = _safe_link(source, critical['Location'])
            result.update(status='redirect', reason='redirect_review_required' if target else 'redirect_blocked',
                          links=[{'url': target, 'text': 'Redirect destination'}] if target else [])
            return result
        if response.status >= 400:
            result.update(status='failed', reason='http_error')
            return result
        if response.status != 200:
            return result
        if critical['Transfer-Encoding'] is not None or critical['Trailer'] is not None:
            result['reason'] = 'unsupported_framing'
            return result
        length = critical['Content-Length']
        if length is not None and not re.fullmatch(r'[0-9]{1,10}', length):
            raise PublicFetchError('invalid_response')
        if length is not None and int(length) > MAX_BODY:
            result['reason'], result['truncated']['body'] = 'body_limit', True
            return result
        if critical['Content-Encoding'] is not None and critical['Content-Encoding'].lower() != 'identity':
            result['reason'] = 'unsupported_encoding'
            return result
        if critical['Content-Disposition'] is not None:
            result['reason'] = 'unsupported_attachment'
            return result
        match = re.fullmatch(r'(text/(?:html|plain))(?:\s*;\s*charset\s*=\s*(?:"([a-zA-Z0-9_-]+)"|([a-zA-Z0-9_-]+)))?\s*',
                             critical['Content-Type'] or '', re.IGNORECASE)
        if not match:
            result['reason'] = 'unsupported_media'
            return result
        charset = (match.group(2) or match.group(3) or 'utf-8').lower()
        charsets = {'utf-8': 'utf-8-sig', 'utf8': 'utf-8-sig', 'us-ascii': 'ascii',
                    'ascii': 'ascii', 'iso-8859-1': 'iso-8859-1', 'windows-1252': 'cp1252'}
        if charset not in charsets:
            result['reason'] = 'unsupported_encoding'
            return result
        chunks, size = [], 0
        while True:
            _remaining(connection.deadline)
            chunk = response.read(min(65536, MAX_BODY - size + 1))
            if not chunk:
                break
            size += len(chunk)
            if size > MAX_BODY:
                raise PublicFetchError('body_limit')
            chunks.append(chunk)
        if length is not None and size != int(length):
            raise PublicFetchError('incomplete_body')
        body = b''.join(chunks)
        title, text, links, truncated = _extract(body, match.group(1).lower(), charsets[charset], source)
        result.update(status='read', reason='ok', title=title, text=text, links=links,
                      truncated=truncated, body_sha256=hashlib.sha256(body).hexdigest())
        return result
    except PublicFetchError:
        raise
    except ssl.SSLError:
        raise PublicFetchError('tls_failed') from None
    except (TimeoutError, socket.timeout):
        raise PublicFetchError('timeout') from None
    except (http.client.HTTPException, UnicodeError, ValueError):
        raise PublicFetchError('invalid_response') from None
    except OSError:
        raise PublicFetchError('connection_failed') from None
    finally:
        if response is not None:
            response.close()
        connection.close()
