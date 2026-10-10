import json
import os
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import urlopen
from aster_remote.relay import Mailbox, Relay, Rejected
from aster_remote.workstation import Client, receive_once

# Non-secret test fixtures only; never valid for a deployed service.
PHONE = 'test-companion-' + 'x' * 40
PC = 'test-workstation-' + 'y' * 40


class RemoteTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name)
        self.box = Mailbox(self.path / 'relay.sqlite', 'test-owner', PHONE, PC, time.time() + 600)
        self.server = Relay(('127.0.0.1', 0), self.box)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.url = 'http://127.0.0.1:' + str(self.server.server_port)
        self.phone = Client(self.url, PHONE, True)
        self.pc = Client(self.url, PC, True)
        self.item = {'id': 'a' * 32, 'body': '<img src=x onerror=alert(1)> Hello Aster', 'expires': time.time() + 300}

    def tearDown(self):
        self.server.shutdown(); self.server.server_close(); self.thread.join(); self.box.db.close(); self.tmp.cleanup()

    def test_real_roundtrip_and_no_generated_answer(self):
        self.assertEqual(self.phone.call('/v1/messages', self.item)['status'], 'queued_for_workstation')
        self.assertEqual(receive_once(self.pc, self.path / 'aster'), 1)
        receipt = self.phone.call('/v1/inbox')['messages'][0]
        self.assertIn('Waiting for NewBrain; no AI answer generated.', receipt['body'])
        self.phone.call('/v1/ack', {'id': receipt['id']})
        self.assertEqual(self.phone.call('/v1/inbox')['messages'], [])
        from aster.storage import Store
        store = Store(self.path / 'aster')
        try:
            self.assertEqual(len(store.rows('prompts')), 1)
            self.assertEqual(store.rows('prompts')[0]['body'], self.item['body'])
            self.assertEqual(store.rows('jobs'), [])
        finally: store.close()

    def test_full_unicode_batch_fits_transport_and_reaches_workstation(self):
        for i in range(50):
            self.phone.call('/v1/messages', {**self.item, 'id': format(i, '032x'), 'body': ('é' * 2048 if i % 2 else '\x01' * 4095 + 'x')})
        self.assertEqual(len(self.pc.call('/v1/inbox')['messages']), 50)
        self.assertEqual(receive_once(self.pc, self.path / 'aster'), 50)
        self.assertEqual(len(self.phone.call('/v1/inbox')['messages']), 50)

    def test_full_prompt_queue_reserves_delivery_receipt_capacity(self):
        with patch('aster_remote.relay.MAX_ROWS', 4):
            for i in range(2):
                self.phone.call('/v1/messages', {**self.item, 'id': format(i, '032x')})
            with self.assertRaises(HTTPError) as err:
                self.phone.call('/v1/messages', self.item)
            self.assertEqual(err.exception.code, 507)
            self.assertEqual(receive_once(self.pc, self.path / 'aster'), 2)
            self.assertEqual(len(self.phone.call('/v1/inbox')['messages']), 2)
            self.assertEqual(self.pc.call('/v1/inbox')['messages'], [])

    def test_malformed_inbox_fails_closed_without_state_creation(self):
        class BrokenRelay:
            def call(self, path): return {'unexpected': []}
        with self.assertRaises(ValueError): receive_once(BrokenRelay(), self.path / 'aster')
        self.assertFalse((self.path / 'aster').exists())

    def test_reconnect_duplicate_and_conflicting_replay(self):
        self.phone.call('/v1/messages', self.item)
        self.assertEqual(Client(self.url, PHONE, True).call('/v1/messages', self.item)['status'], 'already_queued')
        with self.assertRaises(HTTPError) as err:
            self.phone.call('/v1/messages', {**self.item, 'body': 'changed'})
        self.assertEqual(err.exception.code, 409)
        self.assertEqual(len(self.pc.call('/v1/inbox')['messages']), 1)

    def test_lost_receipt_ack_never_duplicates_workstation_prompt(self):
        self.phone.call('/v1/messages', self.item)
        original = self.pc.call
        def fail_ack(path, data=None):
            if path == '/v1/ack': raise OSError('simulated lost connection')
            return original(path, data)
        self.pc.call = fail_ack
        with self.assertRaises(OSError): receive_once(self.pc, self.path / 'aster')
        self.pc.call = original
        receive_once(self.pc, self.path / 'aster')
        from aster.storage import Store
        store = Store(self.path / 'aster')
        try: self.assertEqual(len(store.rows('prompts')), 1)
        finally: store.close()
        self.assertEqual(len(self.phone.call('/v1/inbox')['messages']), 1)

    def test_wrong_owner_missing_auth_and_role(self):
        for action in [lambda: urlopen(self.url + '/v1/inbox'), lambda: Client(self.url, 'wrong-' + 'z' * 40, True).call('/v1/inbox')]:
            with self.assertRaises(HTTPError) as err: action()
            self.assertEqual(err.exception.code, 401)
        with self.assertRaises(HTTPError) as err:
            self.phone.call('/v1/messages', {**self.item, 'owner': 'another-owner'})
        self.assertEqual(err.exception.code, 400)
        self.phone.call('/v1/messages', self.item)
        self.assertEqual(self.phone.call('/v1/inbox')['messages'], [])
        with self.assertRaises(HTTPError): self.phone.call('/v1/ack', {'id': self.item['id']})
        with self.assertRaises(ValueError): Mailbox(self.path / 'relay.sqlite', 'other-owner', PHONE, PC, time.time()+600)

    def test_expired_grant_and_message_size(self):
        for change in [{'expires': time.time()-1}, {'expires': float('nan')}, {'body': 'é' * 4096}, {'body': ''}, {'id': '../escape'}]:
            with self.assertRaises((HTTPError, ValueError)): self.phone.call('/v1/messages', {**self.item, **change})
        self.box.grant_expires = time.time()-1
        with self.assertRaises(HTTPError) as err: self.phone.call('/v1/inbox')
        self.assertEqual(err.exception.code, 401)

    def test_rate_limit_and_auth_fail_closed(self):
        for _ in range(120): self.box.authenticate(PHONE)
        with self.assertRaises(Rejected) as err: self.box.authenticate(PHONE)
        self.assertEqual(err.exception.code, 429)
        with self.assertRaises(ValueError): Mailbox(':memory:', 'owner', '', PC, time.time()+600)
        with self.assertRaises(ValueError): Client('http://example.com', PC)
        with self.assertRaises(ValueError): Client('https://example.com/evil', PC)

    def test_sqlite_durability_expiry_and_html_headers(self):
        self.phone.call('/v1/messages', self.item)
        extra = Mailbox(self.path / 'relay.sqlite', 'test-owner', PHONE, PC, time.time()+600)
        try: self.assertEqual(extra.inbox('workstation')['messages'][0]['body'], self.item['body'])
        finally: extra.db.close()
        self.box.clock = lambda: self.item['expires'] + 1
        self.assertEqual(self.box.inbox('workstation')['messages'], [])
        with urlopen(self.url + '/') as r:
            self.assertIn("frame-ancestors 'none'", r.headers['Content-Security-Policy'])
            self.assertIn('microphone=()', r.headers['Permissions-Policy'])
        source = (Path(__file__).parent.parent / 'web/app.js').read_text()
        self.assertNotIn('innerHTML', source)
        self.assertIn('li.textContent = item.body', source)
        self.assertNotIn('getUserMedia', source)


if __name__ == '__main__': unittest.main()
