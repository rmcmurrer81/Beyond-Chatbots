import argparse
import json
from pathlib import Path
from .runner import run


def main():
    parser=argparse.ArgumentParser(description='Reviewed two-link CAD/dynamics pilot; JSON data only')
    parser.add_argument('input',type=Path)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--seconds',type=float,default=60)
    parser.add_argument('--optimize',action='store_true')
    args=parser.parse_args()
    if args.input.stat().st_size > 100_000: parser.error('Input exceeds 100 KB')
    try:
        result=run(json.loads(args.input.read_text(encoding='utf-8')),args.output,seconds=args.seconds,optimize=args.optimize)
    except (ValueError,OSError) as exc: parser.error(str(exc))
    print(json.dumps({'status':result['status'],'report':str(args.output/'report.json'),'example_only':result['example_only']}))

if __name__=='__main__': main()
