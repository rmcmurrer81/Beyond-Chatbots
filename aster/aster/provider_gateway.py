"""Read-only app-provider preparation status; unrelated to talk() persistence."""
from aster_provider import APP_IDS, PROTOCOL, readiness


def status():
    return {
        'stage': 'contract_preparation_only',
        'protocol': PROTOCOL,
        'allowed_apps': sorted(APP_IDS),
        'readiness': readiness().to_dict(),
        'listener_started': False,
        'live_ipc': False,
        'personal_memory_access': False,
        'training': False,
        'production_backend_activated': False,
        'fallback': None,
    }
