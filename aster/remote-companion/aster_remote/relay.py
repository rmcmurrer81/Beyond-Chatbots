"""Single-owner, bounded durable mailbox. Use verified TLS outside loopback."""
import argparse
import hashlib
import hmac
import json
import math
import os
from pathlib import Path
import re
import sqlite3
import ssl
import time
from http.server import HTTPServer, BaseHTTPRequestHandler

MAX_BODY = 32768
MAX_TEXT = 4096
MAX_ROWS = 4096
ID = re.compile(r'^[a-f0-9]{32}$')


class Rejected(Exception):
    def __init__(self, code, message):
        self.code, self.message = code, message


class Mailbox:
    def __init__(self, path, owner, companion_token, workstation_token, grant_expires, clock=time.time):
        if not owner or len(owner) > 128:
            raise ValueError('One explicit owner is required')
        if any(not isinstance(t, str) or len(t) < 32 or len(t) > 256 for t in (companion_token, workstation_token)):
            raise ValueError('Two separately provisioned strong bearer tokens are required')
        if companion_token == workstation_token:
            raise ValueError('Roles require distinct tokens')
        if not math.isfinite(grant_expires) or not clock() < grant_expires <= clock() + 30 * 86400:
            raise ValueError('Grant must expire within 30 days')
        self.owner, self.clock, self.grant_expires = owner, clock, grant_expires
        self.tokens = {role: hashlib.sha256(token.encode()).digest() for role, token in
                       [('companion', companion_token), ('workstation', workstation_token)]}
        self.rates = {}
        # Caller must supply an owner-private path. Server runs one request at a time.
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        if self.db.execute('PRAGMA max_page_count=8192').fetchone()[0] > 8192:
            self.db.close()
            raise ValueError('Existing mailbox exceeds the database size cap')
        self.db.executescript('''CREATE TABLE IF NOT EXISTS messages (
          id TEXT NOT NULL, owner TEXT NOT NULL, sender TEXT NOT NULL, body TEXT NOT NULL,
          expires REAL NOT NULL, acked INTEGER NOT NULL DEFAULT 0, PRIMARY KEY(id,sender));
          CREATE TABLE IF NOT EXISTS binding(owner TEXT PRIMARY KEY);''')
        old = self.db.execute('SELECT owner FROM binding').fetchone()
        if old and old[0] != owner:
            self.db.close()
            raise ValueError('Mailbox belongs to a different owner')
        with self.db:
            self.db.execute('INSERT OR IGNORE INTO binding VALUES (?)', (owner,))

    def authenticate(self, bearer):
        if self.clock() >= self.grant_expires:
            raise Rejected(401, 'Pairing expired; renew through owner setup')
        digest = hashlib.sha256(bearer.encode()).digest()
        role = next((r for r, token in self.tokens.items() if hmac.compare_digest(token, digest)), None)
        if role is None:
            raise Rejected(401, 'Invalid owner credential')
        now = self.clock()
        bucket = [t for t in self.rates.get(role, []) if t > now - 60]
        if len(bucket) >= 120:
            raise Rejected(429, 'Rate limit; retry later')
        bucket.append(now)
        self.rates[role] = bucket
        return role

    def put(self, role, value):
        if type(value) is not dict or set(value) != {'id', 'body', 'expires'}:
            raise Rejected(400, 'Expected only id, body and expires')
        mid, body, expires = value['id'], value['body'], value['expires']
        if type(mid) is not str or not ID.fullmatch(mid):
            raise Rejected(400, 'Invalid message ID')
        if type(body) is not str or not body.strip() or len(body.encode()) > MAX_TEXT:
            raise Rejected(413, 'Message must contain 1–4096 UTF-8 bytes')
        if type(expires) not in (int, float) or not math.isfinite(expires) or not self.clock() < expires <= self.clock() + 86400:
            raise Rejected(400, 'Message expiry must be in the next 24 hours')
        with self.db:
            # Keep immutable IDs beyond maximum allowed replay window; then prune.
            self.db.execute('DELETE FROM messages WHERE expires < ?', (self.clock() - 86400,))
            old = self.db.execute('SELECT * FROM messages WHERE id=? AND sender=?', (mid, role)).fetchone()
            if old:
                if old['sender'] != role or old['body'] != body or old['expires'] != expires:
                    raise Rejected(409, 'Message ID already used with different content')
                return {'id': mid, 'status': 'already_queued'}
            if self.db.execute('SELECT COUNT(*) FROM messages WHERE sender=?', (role,)).fetchone()[0] >= MAX_ROWS // 2:
                raise Rejected(507, 'Mailbox full; retry after expiry')
            self.db.execute('INSERT INTO messages(id,owner,sender,body,expires) VALUES(?,?,?,?,?)',
                            (mid, self.owner, role, body, expires))
        return {'id': mid, 'status': 'queued_for_workstation' if role == 'companion' else 'queued_for_companion'}

    def inbox(self, role):
        return {'messages': [dict(r) for r in self.db.execute(
            'SELECT id,body,expires FROM messages WHERE owner=? AND sender != ? AND acked=0 AND expires>? ORDER BY rowid LIMIT 50',
            (self.owner, role, self.clock()))]}

    def ack(self, role, value):
        if type(value) is not dict or set(value) != {'id'} or type(value['id']) is not str or not ID.fullmatch(value['id']):
            raise Rejected(400, 'Expected message ID')
        with self.db:
            row = self.db.execute('SELECT sender FROM messages WHERE id=? AND owner=? AND sender != ?', (value['id'], self.owner, role)).fetchone()
            if not row or row[0] == role:
                raise Rejected(404, 'Incoming message not found')
            self.db.execute('UPDATE messages SET acked=1 WHERE id=? AND sender != ?', (value['id'], role))
        return {'status': 'acknowledged'}


class Relay(HTTPServer):
    allow_reuse_address = True
    def __init__(self, address, mailbox):
        self.mailbox = mailbox
        super().__init__(address, Handler)
        self.timeout = 5


class Handler(BaseHTTPRequestHandler):
    server_version = 'AsterRelay/0.1'
    def log_message(self, *args):
        pass  # Never log credentials or message bodies.

    def setup(self):
        super().setup()
        self.connection.settimeout(5)

    def output(self, status, body, content_type='application/json; charset=utf-8'):
        if not isinstance(body, bytes):
            body = json.dumps(body, allow_nan=False, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Referrer-Policy', 'no-referrer')
        self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'")
        self.send_header('Permissions-Policy', 'microphone=(), camera=(), geolocation=()')
        self.end_headers()
        self.wfile.write(body)

    def handle_request(self):
        try:
            if self.command == 'GET' and self.path in {'/', '/app.js', '/style.css', '/manifest.webmanifest', '/icon.svg', '/sw.js'}:
                names = {'/': 'index.html'}
                name = names.get(self.path, self.path[1:])
                mime = {'.html': 'text/html', '.js': 'text/javascript', '.css': 'text/css', '.webmanifest': 'application/manifest+json', '.svg': 'image/svg+xml'}
                self.output(200, (Path(__file__).parent.parent / 'web' / name).read_bytes(), mime[Path(name).suffix])
                return
            if self.path not in {'/v1/inbox', '/v1/messages', '/v1/ack'}:
                raise Rejected(404, 'Not found')
            expected = 'GET' if self.path == '/v1/inbox' else 'POST'
            if self.command != expected:
                raise Rejected(405, 'Method not allowed')
            if len(self.headers.get_all('Authorization', [])) > 1 or len(self.headers.get_all('Content-Length', [])) > 1:
                raise Rejected(400, 'Ambiguous headers')
            auth = self.headers.get('Authorization', '')
            if not auth.startswith('Bearer ') or len(auth) > 300:
                raise Rejected(401, 'Owner pairing required')
            role = self.server.mailbox.authenticate(auth[7:])
            if self.command == 'GET':
                self.output(200, self.server.mailbox.inbox(role)); return
            if self.headers.get_content_type() != 'application/json' or self.headers.get('Transfer-Encoding'):
                raise Rejected(400, 'Bounded JSON required')
            length = self.headers.get('Content-Length', '')
            if not length.isdecimal() or not 0 < int(length) <= MAX_BODY:
                raise Rejected(413, 'Invalid body size')
            data = json.loads(self.rfile.read(int(length)))
            result = self.server.mailbox.put(role, data) if self.path == '/v1/messages' else self.server.mailbox.ack(role, data)
            self.output(200, result)
        except Rejected as e:
            self.output(e.code, {'error': e.message})
        except (ValueError, UnicodeError, RecursionError):
            self.output(400, {'error': 'Invalid JSON'})
        except sqlite3.Error:
            self.output(503, {'error': 'Mailbox unavailable; retry later'})

    do_GET = do_POST = handle_request


def main():
    p = argparse.ArgumentParser(description='Opt-in single-owner mailbox. No credentials are generated.')
    p.add_argument('--host', default='127.0.0.1'); p.add_argument('--port', type=int, default=8765)
    p.add_argument('--database', required=True); p.add_argument('--cert'); p.add_argument('--key')
    a = p.parse_args()
    if a.host not in {'127.0.0.1', '::1', 'localhost'} and not (a.cert and a.key):
        p.error('Public binding requires TLS certificate and private key')
    required = ['ASTER_REMOTE_OWNER', 'ASTER_REMOTE_COMPANION_TOKEN', 'ASTER_REMOTE_WORKSTATION_TOKEN', 'ASTER_REMOTE_GRANT_EXPIRES']
    if any(not os.environ.get(k) for k in required):
        p.error('Missing owner-provisioned authentication configuration; see README')
    os.umask(0o077)
    box = Mailbox(a.database, *[os.environ[k] for k in required[:3]], float(os.environ[required[3]]))
    server = Relay((a.host, a.port), box)
    if a.cert and a.key:
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.minimum_version = ssl.TLSVersion.TLSv1_2
        context.load_cert_chain(a.cert, a.key)
        server.socket = context.wrap_socket(server.socket, server_side=True)
    try:
        print('Aster mailbox running. Ctrl-C stops it. Voice and AI replies are unavailable.')
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close(); box.db.close()


if __name__ == '__main__':
    main()
