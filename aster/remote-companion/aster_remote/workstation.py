"""Outbound-only bridge; remote text can only become a pending NewBrain prompt."""
import argparse
import json
import os
from pathlib import Path
import ssl
import sqlite3
import time
from urllib.parse import urlsplit
from urllib.request import Request, build_opener, HTTPRedirectHandler, HTTPSHandler


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None  # Never forward a bearer credential to another destination.


class Client:
    def __init__(self, url, token, allow_loopback=False):
        u = urlsplit(url)
        if u.username or u.password or u.query or u.fragment or u.path not in {'', '/'}:
            raise ValueError('Use a plain relay origin, without credentials/path')
        local = allow_loopback and u.hostname in {'127.0.0.1', 'localhost', '::1'}
        if not u.hostname or (u.scheme != 'https' and not (local and u.scheme == 'http')):
            raise ValueError('Verified HTTPS required; explicit loopback test exception only')
        if not token or len(token) < 32:
            raise ValueError('Owner-provisioned workstation token required')
        self.url, self.token = url.rstrip('/'), token
        self.opener = build_opener(NoRedirect(), HTTPSHandler(context=ssl.create_default_context()))

    def call(self, path, data=None):
        request = Request(self.url + path, data=None if data is None else json.dumps(data, ensure_ascii=False, allow_nan=False).encode(),
                          headers={'Authorization': 'Bearer ' + self.token, 'Content-Type': 'application/json'})
        with self.opener.open(request, timeout=10) as response:
            raw = response.read(2 * 1024 * 1024 + 1)
            if len(raw) > 2 * 1024 * 1024:
                raise ValueError('Relay response too large')
            return json.loads(raw)


def receive_once(client, state):
    """Standalone mode: only for a state directory not already open in Aster."""
    from aster.storage import Store
    from .delivery import inbox, save_message, receipt
    count = 0
    for item in inbox(client.call('/v1/inbox')):
        store = Store(state)
        try:
            save_message(store, item)
        finally:
            store.close()
        # The transaction and writer lock are finished before network traffic.
        receipt(client, item)
        count += 1
    return count


def main():
    p = argparse.ArgumentParser(description='Foreground outbound-only Aster bridge; Ctrl-C stops immediately.')
    p.add_argument('--relay', required=True); p.add_argument('--state', required=True, type=Path)
    p.add_argument('--once', action='store_true'); p.add_argument('--allow-loopback-test', action='store_true')
    p.add_argument('--desktop', action='store_true', help='Open the desktop with opt-in outbound message polling')
    a = p.parse_args()
    if a.desktop and a.once:
        p.error('--desktop and --once are mutually exclusive')
    client = Client(a.relay, os.environ.get('ASTER_REMOTE_WORKSTATION_TOKEN'), a.allow_loopback_test)
    if a.desktop:
        from aster.desktop import launch
        return launch(a.state, remote_client=client)
    try:
        while True:
            try:
                print(json.dumps({'received': receive_once(client, a.state), 'backend': 'waiting_for_newbrain'}))
            except (OSError, ValueError, RuntimeError, sqlite3.Error) as exc:
                print('Connection/state unavailable; messages remain queued. ' + type(exc).__name__)
                if a.once:
                    return 1
            if a.once:
                return 0
            time.sleep(10)
    except KeyboardInterrupt:
        return 0


if __name__ == '__main__':
    raise SystemExit(main())
