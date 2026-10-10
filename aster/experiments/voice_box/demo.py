"""Explicit offline voice-box CLI. Export only: never opens or plays sound."""
import argparse
import sys
from .protocol import VoiceError, canonical, demo_plan, need, parse_json, validate
from .storage import inspect_bundle, read_plain, recheck_bundle, render_bundle


class _Parser(argparse.ArgumentParser):
    def error(self, message):
        self.exit(2, 'error: invalid_arguments\n')


def main(argv=None):
    parser = _Parser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True, parser_class=_Parser)
    for name in ('demo', 'render', 'inspect', 'recheck', 'from-text-lab'):
        cmd = commands.add_parser(name)
        cmd.add_argument('--owner', default='synthetic_aster')
        if name in ('inspect', 'recheck'):
            cmd.add_argument('--bundle', required=True)
        else:
            cmd.add_argument('--output', required=True, help='New directory beneath an existing trusted parent')
        if name == 'render':
            cmd.add_argument('--intent', required=True, help='Bounded manual-gesture JSON intent')
        if name == 'from-text-lab':
            cmd.add_argument('--text-state', required=True)
            cmd.add_argument('--method', default='INTERLEAVED')
            cmd.add_argument('--split', default='new')
            cmd.add_argument('--case-index', type=int, default=0)
    args = parser.parse_args(argv)
    try:
        if args.command == 'inspect':
            result = inspect_bundle(args.bundle, args.owner)
        elif args.command == 'recheck':
            result = recheck_bundle(args.bundle, args.owner)
        else:
            if args.command == 'demo':
                plan = demo_plan(args.owner)
            elif args.command == 'render':
                plan = validate(parse_json(read_plain(args.intent, 32768)), args.owner)
                need(plan['origin']['kind'] == 'manual_gestures', 'use_verified_lab_adapter')
            else:
                from .bridge import from_text_lab
                plan = from_text_lab(args.text_state, args.owner, args.method, args.split, args.case_index)
            result = render_bundle(args.output, plan)
        print(canonical(result).decode('ascii'), end='')
        return 0
    except VoiceError as exc:
        print('error: ' + str(exc), file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print('error: operation_cancelled', file=sys.stderr)
        return 130
    except Exception:
        print('error: voice_box_failed', file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
