"""Fresh-process replay helper for a bounded synthetic suffix, without truth."""
import base64
import json
from pathlib import Path
import sys
from .tracker import Tracker


def main():
    checkpoint, inputs, output = map(Path,sys.argv[1:])
    if checkpoint.is_symlink() or checkpoint.stat().st_size>16384:
        raise ValueError('Checkpoint bound')
    if inputs.is_symlink() or inputs.stat().st_size>1_200_000:
        raise ValueError('Replay input bound')
    tracker=Tracker.from_bytes(checkpoint.read_bytes())
    rows=json.loads(inputs.read_text(encoding='utf-8'))
    if type(rows) is not list or len(rows)>64:
        raise ValueError('Replay count bound')
    predictions=[tracker.observe(base64.b64decode(r['rgb'],validate=True),r['timestamp_ms']) for r in rows]
    with output.open('x',encoding='utf-8',newline='\n') as stream:
        json.dump({'predictions':predictions,'checkpoint':tracker.to_bytes().decode('utf-8')},stream,allow_nan=False)
        stream.write('\n')


if __name__=='__main__': main()
