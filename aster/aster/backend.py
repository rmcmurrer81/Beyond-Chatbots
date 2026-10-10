"""Fail-closed NewBrain boundary. This is a proposed Aster contract, not NewBrain's API."""
from dataclasses import dataclass
from typing import Protocol
import time
from .storage import text, token


@dataclass(frozen=True)
class BrainRequest:
    request_id: str
    subject_id: str
    prompt: str
    # Memory access will require separately selected, subject-scoped records.
    protocol: str = 'aster.newbrain.proposed.v1'


class QualifiedNewBrain(Protocol):
    """Future reviewed implementation; no runtime loader or network endpoint exists."""
    def respond(self, request: BrainRequest) -> dict: ...


def status():
    return {'backend': 'newbrain', 'available': False, 'fallback': None,
            'reason': 'No qualified NewBrain conversational interface is connected.',
            'protocol': 'aster.newbrain.proposed.v1', 'autonomous_execution': False}


def talk(store, prompt):
    text(prompt)
    id_ = token()
    with store.db:
        store.db.execute('INSERT INTO prompts VALUES (?,?,?,?)',
                         (id_, time.time(), prompt, 'waiting_for_newbrain'))
        store.event('prompt.saved', {'id': id_, 'status': 'waiting_for_newbrain'})
    return {'request_id': id_, 'status': 'waiting_for_newbrain',
            'message': 'Your message is saved. NewBrain is not connected; no AI answer was generated.',
            'backend': status()}
