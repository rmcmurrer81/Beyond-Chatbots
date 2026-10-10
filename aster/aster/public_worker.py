"""Fixed disposable static-reader entry point. No user-selectable execution mode."""
import json
from pathlib import Path
import sys

# -I removes cwd and user packages. Load only this reviewed sibling package.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from aster.public_transport import PublicFetchError, fetch_public

MAX_INPUT = 8192
MAX_OUTPUT = 512 * 1024


def main():
    try:
        raw = sys.stdin.buffer.read(MAX_INPUT + 1)
        if len(raw) > MAX_INPUT:
            raise ValueError
        request = json.loads(raw.decode('ascii'))
        if type(request) is not dict or set(request) != {'url'} or type(request['url']) is not str:
            raise ValueError
        result = fetch_public(request['url'])
    except PublicFetchError as exc:
        result = {'status': 'failed', 'reason': exc.code}
    except Exception:
        result = {'status': 'failed', 'reason': 'worker_failed'}
    encoded = json.dumps(result, ensure_ascii=True, allow_nan=False, separators=(',', ':')).encode('ascii')
    if len(encoded) > MAX_OUTPUT:
        encoded = b'{"status":"failed","reason":"worker_failed"}'
    sys.stdout.buffer.write(encoded)
    sys.stdout.buffer.flush()


if __name__ == '__main__':
    main()
