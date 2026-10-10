"""Finite child used only by the synthetic close-and-reopen test."""
import json
import hashlib
import os
from pathlib import Path
import sys
from .component import ComponentSource, PIN, canonical
from .fixtures import OWNER, event, consequence, metadata


def main():
    mode, path, *pins = sys.argv[1:]
    target = Path(path)
    source = ComponentSource(pin=pins[0] if pins else PIN)
    if mode.endswith('observed') or mode.startswith('crash-'):
        from . import persistence
        session = source.fresh(OWNER) if mode == 'train-observed' else source.restore(target.read_bytes(), owner_id=OWNER)
        observer = session.observer(experiment_id='aster-component-engineering', arm_id='numeric-value')
        if mode == 'train-observed':
            observer.observe_learn(metadata(), event(), consequence(), checkpoint_path=target)
        elif mode == 'correct-observed' or mode.startswith('crash-'):
            if mode.startswith('crash-'):
                replace = os.replace
                def crash(source, destination):
                    if mode == 'crash-after-replace':
                        replace(source, destination)
                    os._exit(66 if mode == 'crash-before-replace' else 67)
                persistence.os.replace = crash
            observer.observe_learn(metadata(corrected=True), event(), consequence(corrected=True), checkpoint_path=target)
        elif mode != 'restore-observed':
            raise ValueError('Unknown finite observed test phase')
        print(json.dumps({'prediction': session.model.predict(event()),
                          'checkpoint_sha256': hashlib.sha256(session.checkpoint()).hexdigest(),
                          'first_record_sha256': hashlib.sha256(canonical(observer.history()[0])).hexdigest(),
                          'receipts': len(session.model.receipts)}, sort_keys=True))
        return
    if mode == 'train':
        session = source.fresh(OWNER)
        session.model.learn(event(), consequence())
        session.model.learn(event(), consequence(corrected=True))
        # Exclusive creation. The parent supplies its own fresh temporary directory.
        with target.open('xb') as handle:
            handle.write(session.snapshot())
    elif mode == 'restore':
        with target.open('rb') as handle:
            raw = handle.read(70001)
        session = source.restore(raw, owner_id=OWNER)
    else:
        raise ValueError('Unknown finite test phase')
    print(json.dumps({'prediction': session.model.predict(event()),
                      'state': session.snapshot().decode('ascii'),
                      'receipts': len(session.model.receipts)}, sort_keys=True))


if __name__ == '__main__':
    main()
