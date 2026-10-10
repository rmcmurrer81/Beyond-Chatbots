"""Hash-checked, private-module import of two exact generic NewBrain sources."""
from contextlib import contextmanager
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys
import threading

ROOT = Path(__file__).resolve().parents[2]
PIN = 'cbf43167b2a9f3df7b61c1e0d9497d26115a2c94'
VENDOR = ROOT / 'vendor' / 'newbrain_vision' / PIN
_LOCK = threading.RLock()


def load():
    # An explicit lab invocation, never application startup, configures threading.
    for key in ('OMP_NUM_THREADS', 'OPENBLAS_NUM_THREADS', 'MKL_NUM_THREADS', 'NUMEXPR_NUM_THREADS'):
        if 'numpy' in sys.modules and os.environ.get(key) != '1':
            raise RuntimeError('Start a fresh process with numerical thread limits set to 1')
        os.environ[key] = '1'
    import numpy as np
    if np.__version__ != '2.3.5':
        raise RuntimeError('This experiment requires the separately installed numpy==2.3.5')
    manifest = json.loads((VENDOR / 'manifest.json').read_text(encoding='utf-8'))
    for name, entry in manifest['files'].items():
        raw = (VENDOR / name).read_bytes()
        if hashlib.sha256(raw).hexdigest() != entry['sha256']:
            raise ValueError('Vendored source integrity failure: ' + name)
    with _LOCK:
        modules = {}
        old = sys.modules.get('visual_dataset')
        try:
            for name in ('visual_dataset', 'visual_model'):
                spec = importlib.util.spec_from_file_location('_aster_vision_' + name, VENDOR / (name + '.py'))
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)
                modules[name] = module
                if name == 'visual_dataset':
                    sys.modules[name] = module
        finally:
            if old is None:
                sys.modules.pop('visual_dataset', None)
            else:
                sys.modules['visual_dataset'] = old
    return modules['visual_dataset'], modules['visual_model']
