import argparse
import json
import os
from pathlib import Path
import sys
import sqlite3
from .backend import status, talk
from .apps import discover
from .files import Files
from .jobs import Jobs
from .storage import Store


def main(argv=None):
    p = argparse.ArgumentParser(description='Aster: a NewBrain-only workstation foundation. No AI backend is connected.')
    p.add_argument('--state', type=Path, default=Path.cwd() / '.aster-state', help='Private owner-controlled state directory')
    sub = p.add_subparsers(dest='command', required=True)
    sub.add_parser('status')
    inspection = sub.add_parser('inspect-state', help='Bounded read-only stored-state diagnostic; no startup writes or recovery')
    inspection.add_argument('--limit', type=int, default=20, help='Rows per section, from 1 to 50')
    sub.add_parser('provider-status', help='Read-only app-provider preparation status; no Store or live service')
    browser = sub.add_parser('browser', help='Review and explicitly open a URL or search in your default browser')
    bs = browser.add_subparsers(dest='browser_command', required=True)
    bs.add_parser('status')
    for kind in ['url', 'source', 'search']:
        item = bs.add_parser(kind)
        item.add_argument('value', help='Exact public HTTP(S) URL or exact search text; no private context is added')
        item.add_argument('--approve', action='store_true', help='Approve this exact browser handoff')
        item.add_argument('--plan-sha256', help='SHA-256 returned by the preview of this exact command')
    support = sub.add_parser('support', help='Local supporting modules; use catalog for operations and argument examples')
    support.add_argument('module', choices=['catalog', 'ability', 'memory', 'library', 'communications', 'media', 'resources'])
    support.add_argument('operation', nargs='?', default='status')
    support.add_argument('--args-json', default='{}', help='Exact JSON argument object; see support catalog')
    support.add_argument('--approve', action='store_true', help='Explicitly approve this one bounded local mutation')
    sub.add_parser('desktop', help='Open the local desktop control panel; no network service')
    memory = sub.add_parser('memory', help='Local RAM pressure and Aster-only job admission policy')
    ms = memory.add_subparsers(dest='memory_command', required=True)
    ms.add_parser('status')
    mc = ms.add_parser('configure')
    mc.add_argument('--high-percent', type=float, required=True)
    mc.add_argument('--resume-percent', type=float, required=True)
    startup = sub.add_parser('startup', help='Review optional Windows sign-in startup; never enabled automatically')
    startup.set_defaults(startup_command='plan', action='enable')
    ss = startup.add_subparsers(dest='startup_command')
    sp = ss.add_parser('plan'); sp.add_argument('--action', choices=['enable', 'disable'], default='enable')
    ss.add_parser('status')
    for name in ['enable', 'disable']:
        sx = ss.add_parser(name); sx.add_argument('--plan-digest', required=True)
    sub.add_parser('voice', help='Verify the supplied prerecorded voice audition; no playback or synthesis')
    apps = sub.add_parser('apps'); apps.add_argument('--catalog', type=Path)
    adapter = sub.add_parser('app-export', help='Explicit workspace-only research exports; no live app connection')
    ax = adapter.add_subparsers(dest='export_command', required=True)
    for name in ['status', 'list', 'selected', 'clear-selection']:
        ax.add_parser(name)
    am = ax.add_parser('preview-manifest'); am.add_argument('path')
    am = ax.add_parser('register'); am.add_argument('path'); am.add_argument('--sha256', required=True); am.add_argument('--approve', action='store_true')
    for name in ['preview-export', 'select']:
        ae = ax.add_parser(name); ae.add_argument('manifest_id'); ae.add_argument('project_id'); ae.add_argument('path')
        if name == 'select':
            ae.add_argument('--sha256', required=True); ae.add_argument('--approve', action='store_true')
    for name in ['inspect', 'read']:
        ae = ax.add_parser(name); ae.add_argument('--selection-id')
        if name == 'read': ae.add_argument('--record-id')
    ad = ax.add_parser('disable'); ad.add_argument('manifest_id'); ad.add_argument('--approve', action='store_true')
    t = sub.add_parser('talk'); t.add_argument('text')
    m = sub.add_parser('remember'); m.add_argument('text'); m.add_argument('--source', default='user'); m.add_argument('--supersedes')
    h = sub.add_parser('history'); h.add_argument('kind', choices=['memories','events','prompts','jobs','changes'])
    r = sub.add_parser('read'); r.add_argument('path')
    w = sub.add_parser('write'); w.add_argument('path'); w.add_argument('text')
    d = sub.add_parser('trash'); d.add_argument('path')
    u = sub.add_parser('undo'); u.add_argument('change_id')
    sub.add_parser('recover')
    j = sub.add_parser('queue'); j.add_argument('action'); j.add_argument('args_json'); j.add_argument('--budget', type=float, default=5)
    sub.add_parser('run-one')
    for name in ['pause','resume','cancel']:
        x = sub.add_parser(name); x.add_argument('job_id')
    abilities = sub.add_parser('ability', help='Versioned source proposals; execution and activation stay disabled')
    ab = abilities.add_subparsers(dest='ability_command', required=True)
    ab.add_parser('list')
    ag = ab.add_parser('get'); ag.add_argument('proposal_id')
    ac = ab.add_parser('propose'); ac.add_argument('name'); ac.add_argument('path'); ac.add_argument('--permissions-json', default='[]'); ac.add_argument('--supersedes')
    ar = ab.add_parser('review'); ar.add_argument('proposal_id'); ar.add_argument('--verdict', choices=['approved', 'rejected'], required=True); ar.add_argument('--note', required=True); ar.add_argument('--source-sha256', required=True)
    ase = ab.add_parser('select'); ase.add_argument('proposal_id')
    arb = ab.add_parser('rollback'); arb.add_argument('name')
    args = p.parse_args(argv)
    if args.command == 'startup' and args.startup_command is None:
        args.startup_command = 'plan'
    store = files = None
    try:
        if args.command == 'inspect-state':
            from .inspection import inspect_state
            result = inspect_state(args.state, limit=args.limit)
            print(json.dumps(result, indent=2, ensure_ascii=False, allow_nan=False))
            return 0 if result['status'] in {'available', 'partial'} else 2
        if args.command == 'provider-status':
            from .provider_gateway import status as provider_status
            print(json.dumps(provider_status(), indent=2, ensure_ascii=False, allow_nan=False))
            return 0
        if args.command == 'browser':
            from . import browser_actions
            if args.browser_command == 'status':
                result = browser_actions.status()
            elif args.approve:
                result = browser_actions.open_reviewed(args.browser_command, args.value,
                    approved=True, expected_sha256=args.plan_sha256)
            else:
                result = browser_actions.plan(args.browser_command, args.value)
            print(json.dumps(result, indent=2, ensure_ascii=False, allow_nan=False))
            return 2 if result.get('status') in {'launch_failed', 'launch_unknown'} else 0
        if args.command == 'startup':
            from . import startup as startup_helper
            if args.startup_command == 'plan':
                result = startup_helper.plan(args.state, action=args.action)
            elif args.startup_command == 'status':
                result = startup_helper.status(args.state)
            else:
                if not sys.stdin.isatty():
                    raise ValueError('Startup changes require interactive owner review in a terminal; no settings changed')
                def confirm_startup(plan):
                    print(json.dumps(plan, indent=2, ensure_ascii=False, allow_nan=False))
                    phrase = args.startup_command.upper() + ' ASTER STARTUP'
                    print('This changes Windows sign-in startup for the current user only.')
                    try:
                        return input('Type ' + phrase + ' to apply this exact reviewed plan: ') == phrase
                    except EOFError:
                        return False
                action = getattr(startup_helper, args.startup_command)
                result = action(args.state, reviewed_plan_digest=args.plan_digest, confirm=confirm_startup)
            print(json.dumps(result, indent=2, ensure_ascii=False, allow_nan=False))
            return 0
        if args.command == 'desktop':
            from .desktop import launch
            return launch(args.state)
        if args.command == 'voice':
            from .voice import inspect_voice
            print(json.dumps(inspect_voice(), indent=2, ensure_ascii=False, allow_nan=False))
            return 0
        store = Store(args.state); files = Files(store); jobs = Jobs(store, files)
        cmd = args.command
        if cmd == 'status': result = {'identity': store.identity(), 'backend': status(),
            'working': ['persistent prompts and append-only memories', 'scoped file writes, reversible trash and undo',
                        'explicit finite queued actions, pause/resume/cancel before execution', 'manual research links',
                        'local desktop control panel (requires Tk and graphical session)',
                        'owner-selected workspace research export snapshots; no live app commands',
                        'explicitly reviewed default-browser URL, source and search handoffs',
                        'read-only prerecorded voice inspection', 'versioned inert source proposals; reviewed bounded text recipes',
                        'support modules: private memory search, scoped references, local communications drafts, PCM audio trim and resource admission'],
            'not_available': ['AI conversation', 'autonomous planning', 'arbitrary program execution', 'general code ability activation', 'desktop control', 'live speech synthesis', 'phone calling'],
            'platform': {'file_adapter': type(files).__name__,
                         'scope': 'local fixed NTFS; ASCII workspace names; no reparse/UNC/ADS' if os.name == 'nt' else 'owner-controlled POSIX workspace'},
            'workspace': str(files.root), 'limits': {'max_file_bytes': 262144, 'concurrent_commands': 1,
            'jobs_per_run': 1, 'budget': 'soft measured wall time, not hard OS resource isolation'}}
        elif cmd == 'support':
            from .support import catalog, invoke, parse_args
            result = catalog() if args.module == 'catalog' else invoke(store, files, jobs,
                args.module, args.operation, parse_args(args.args_json), approved=args.approve)
        elif cmd == 'apps': result = discover(args.catalog)
        elif cmd == 'memory':
            from .system_control import configure_memory
            from .app_relief import status as relief_status
            if args.memory_command == 'configure':
                result = configure_memory(store, args.high_percent, args.resume_percent)
            else:
                result = {'memory': jobs.memory_guard.sample(force=True),
                          'external_app_relief': relief_status()}
        elif cmd == 'app-export':
            from .app_adapters import AppAdapters
            exports = AppAdapters(store, files)
            op = args.export_command
            if op == 'status': result = exports.status()
            elif op == 'list': result = exports.list()
            elif op == 'selected': result = exports.selected()
            elif op == 'clear-selection': result = exports.clear_selection()
            elif op == 'preview-manifest': result = exports.preview_manifest(args.path)
            elif op == 'register': result = exports.register(args.path, expected_sha256=args.sha256, approved=args.approve)
            elif op == 'preview-export': result = exports.preview_export(args.manifest_id, args.project_id, args.path)
            elif op == 'select': result = exports.select(args.manifest_id, args.project_id, args.path, expected_sha256=args.sha256, approved=args.approve)
            elif op == 'inspect': result = exports.inspect(args.selection_id)
            elif op == 'read': result = exports.read(args.selection_id, args.record_id)
            else: result = exports.disable(args.manifest_id, approved=args.approve)
        elif cmd == 'ability':
            from .abilities import Abilities
            registry = Abilities(store, files)
            if args.ability_command == 'list': result = registry.list()
            elif args.ability_command == 'get': result = registry.get(args.proposal_id)
            elif args.ability_command == 'propose': result = registry.create(args.name, args.path, json.loads(args.permissions_json), args.supersedes)
            elif args.ability_command == 'review': result = registry.review(args.proposal_id, args.verdict, args.note, args.source_sha256)
            elif args.ability_command == 'select': result = registry.select(args.proposal_id)
            else: result = registry.rollback(args.name)
        elif cmd == 'talk': result = talk(store, args.text)
        elif cmd == 'remember': result = {'id': store.remember(args.text, args.source, args.supersedes)}
        elif cmd == 'history':
            if args.kind == 'memories':
                from .private_memory import PrivateMemory
                result = PrivateMemory(store).search(include_superseded=True, limit=100)
            else: result = store.rows(args.kind)
        elif cmd == 'read': result = {'path': args.path, 'text': files.read(args.path).decode('utf-8')}
        elif cmd == 'write': result = {'change_id': files.change(args.path, args.text.encode())}
        elif cmd == 'trash': result = {'change_id': files.change(args.path, None, 'trash')}
        elif cmd == 'undo': result = {'change_id': files.undo(args.change_id)}
        elif cmd == 'recover':
            result = {'files': files.recover(), 'interrupted_jobs': jobs.recover()}
            result['recovery_required'] = bool(store.db.execute(
                "SELECT 1 FROM changes WHERE status='prepared' LIMIT 1").fetchone())
        elif cmd == 'queue': result = {'id': jobs.submit(args.action, json.loads(args.args_json), args.budget)}
        elif cmd == 'run-one': result = jobs.run_one()
        else: result = {'status': jobs.control(args.job_id, cmd)}
        print(json.dumps(result, indent=2, ensure_ascii=False, allow_nan=False))
        return 3 if cmd == 'recover' and result['recovery_required'] else 0
    except (ValueError, OSError, RuntimeError, sqlite3.Error) as exc:
        print(json.dumps({'error': str(exc)}), file=sys.stderr); return 2
    finally:
        if files: files.close()
        if store: store.close()


if __name__ == '__main__':
    raise SystemExit(main())
