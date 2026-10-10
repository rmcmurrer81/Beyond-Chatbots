"""Bounded text-only remote delivery. This module never imports a job dispatcher."""
from dataclasses import dataclass
import math
import re
import time

MAX_TEXT = 4096
MAX_INBOX = 50
ID = re.compile(r'^[a-f0-9]{32}$')


@dataclass(frozen=True)
class Message:
    id: str
    body: str
    expires: float


def message(value):
    """Validate and copy at every trust boundary; queued text is immutable."""
    if isinstance(value, Message):
        value = {'id': value.id, 'body': value.body, 'expires': value.expires}
    now = time.time()
    if (type(value) is not dict or set(value) != {'id', 'body', 'expires'} or
            type(value['id']) is not str or not ID.fullmatch(value['id']) or
            type(value['body']) is not str or not value['body'].strip() or
            len(value['body'].encode('utf-8')) > MAX_TEXT or
            type(value['expires']) not in (int, float) or
            not math.isfinite(value['expires']) or
            not now < value['expires'] <= now + 86400):
        raise ValueError('Invalid or expired relay message')
    return Message(value['id'], value['body'], value['expires'])


def inbox(envelope):
    if type(envelope) is not dict or set(envelope) != {'messages'}:
        raise ValueError('Invalid inbox envelope')
    values = envelope['messages']
    if type(values) is not list or len(values) > MAX_INBOX:
        raise ValueError('Invalid inbox')
    return [message(value) for value in values]


def save_message(store, item):
    """Run on Store's owning thread. Return only after a durable transaction."""
    item = message(item)  # It may have expired while awaiting local confirmation.
    mid = 'remote-' + item.id
    with store.db:
        old = store.db.execute('SELECT body FROM prompts WHERE id=?', (mid,)).fetchone()
        if old and old[0] != item.body:
            raise ValueError('Remote ID conflict')
        if not old:
            store.db.execute('INSERT INTO prompts VALUES(?,?,?,?)',
                             (mid, time.time(), item.body, 'waiting_for_newbrain'))
            store.event('remote.prompt.saved', {'id': mid, 'status': 'waiting_for_newbrain'})
    return {'request_id': mid, 'status': 'waiting_for_newbrain', 'inserted': not bool(old)}


def receipt(client, item, stopping=lambda: False):
    # Stable content/expiry: lost POST responses can retry without new IDs.
    if stopping():
        raise PollingStopped()
    client.call('/v1/messages', {'id': item.id,
        'body': 'Message ' + item.id + ' saved on workstation. Waiting for NewBrain; no AI answer generated.',
        'expires': item.expires})
    if stopping():
        raise PollingStopped()
    client.call('/v1/ack', {'id': item.id})


class PollingStopped(Exception):
    pass
