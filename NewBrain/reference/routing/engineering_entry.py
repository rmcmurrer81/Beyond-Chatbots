"""Explicit frozen-source entry for disposable synthetic engineering only.

Root binds exact files before launch. Existing isolated NumPy bootstrap is
repeated in each process. No target cache or stage sys.path import is selected.
"""
import hashlib
import json
from pathlib import Path
import sys
import traceback
import types

NAMES = ('run_io','dialogue_decoder','routed_decoder','original_update_journal','extended_update_journal','original_continuation_state','continuation_state','available_state','original_history_archive','history_archive','branch_state','branch_history','probe_ledger','method_order','branch_language','method_entry','routing_engineering','synthetic_fixture','engineering_entry')


def need(ok, why):
    if not ok:
        raise RuntimeError(why)


def load_source(name, row, io=None, retained=None):
    need(name not in sys.modules and type(row) is dict and set(row) == {'path', 'bytes', 'sha256'} and
         type(row['bytes']) is int and 0 < row['bytes'] <= 65536, 'Fresh exact finite source module')
    path = Path(row['path'])
    if io is None:
        with path.open('rb') as handle:
            data = handle.read(row['bytes']+1)
    else:
        data = io.read(path, row['bytes'], source=True)
    need(len(data) == row['bytes'] and hashlib.sha256(data).hexdigest() == row['sha256'], 'Exact original source bytes')
    if retained is not None:
        retained['loaded_source_raw_hex'][name] = data.hex()
    module = types.ModuleType(name)
    module.__file__ = str(path.resolve())
    sys.modules[name] = module
    exec(compile(data, str(path), 'exec'), module.__dict__)
    if retained is not None:
        retained['loaded_module_origins'][name] = module.__file__
    return module


def main():
    need(len(sys.argv) == 2, 'One exact root-bound private contract')
    with Path(sys.argv[1]).open('rb') as handle:
        argraw = handle.read(32769)
    need(len(argraw) <= 32768, 'Complete bounded entry contract')
    args = json.loads(argraw)
    need(type(args) is dict and set(args) == {'schema', 'stage_root', 'stage_sources', 'bootstrap', 'inventory', 'experiment'}
         and args['schema'] == 'newbrain.routing230.synthetic-calibration-entry.v1', 'Closed selected entry')
    rows = args['stage_sources']
    need(type(rows) is dict and set(rows) == set(NAMES), 'Exactly nineteen selected source modules')
    run_io = load_source('run_io', rows['run_io'])
    io = run_io.RunIO(Path.cwd(), Path.cwd()/'STOP.json')
    io.charge(32769)
    io.charge(rows['run_io']['bytes']+1, source=True)
    io.source_root, io.bootstrap_root = Path(args['stage_root']).resolve(), Path(args['bootstrap']['path']).resolve().parent
    retained = {'phase': 'bootstrap', 'loaded_source_raw_hex': {}, 'loaded_module_origins': {},
                'stage_pins': [], 'manifest': None, 'pins': {}, 'census': None}
    graph_module = None
    try:
        def roster():
            found = tuple(io.source_root.iterdir())
            need(len(found) == 19 and {p.name for p in found} == {n+'.py' for n in NAMES} and
                 all(p.is_file() and p.suffix == '.py' for p in found), 'Refuse source caches/directories/extras')
        roster()
        for name in NAMES:
            row = rows[name]
            need(Path(row['path']).resolve() == io.source_root/(name+'.py'), 'Explicit selected source placement')
            data = io.read(row['path'], row['bytes'], source=True)
            need(len(data) == row['bytes'] and hashlib.sha256(data).hexdigest() == row['sha256'], 'Whole stage source pin')
            retained['stage_pins'].append(dict(row))
        graph_module = load_source('available_state', rows['available_state'], io, retained)
        bootstrap = load_source('numpy_bootstrap_common214', args['bootstrap'], io, retained)
        retained['phase'] = 'numpy-inventory'
        manifest, pins = bootstrap.prepare(io, args['inventory']['path'], args['inventory']['sha256'], retained)
        retained['manifest'], retained['pins'] = manifest, pins
        retained['phase'] = 'numpy-import'
        bootstrap.load_numpy(io, pins)
        retained['phase'] = 'numpy-linalg-import'
        import importlib
        importlib.import_module('numpy.linalg')
        retained['phase'] = 'common-import'
        for name in ('original_update_journal','extended_update_journal','dialogue_decoder','routed_decoder','original_continuation_state','continuation_state','original_history_archive','history_archive','branch_state','branch_history','probe_ledger','method_order','branch_language','method_entry','routing_engineering','synthetic_fixture'):
            target = load_source(name, rows[name], io, retained)
        before = io.source
        observed = bootstrap.census(io, pins, retained)
        need(io.source-before <= 8388608, 'Finite remaining eight-MiB observed source lane')
        retained['census'] = observed
        roster()
        selected = {str(Path(r['path']).resolve()).lower(): r for r in rows.values()}
        for module in observed['modules']:
            for file in module.get('files', []):
                path = Path(file['path']).resolve()
                if path.parent == io.source_root and file.get('exists', True):
                    expected = selected.get(str(path).lower())
                    need(expected is not None and file['bytes'] == expected['bytes'] and
                         file['sha256'] == expected['sha256'], 'Observed post-import stage source unchanged')
        need(len(io.observer_rows) == 3, 'Exact three bootstrap checkpoints before selected branch route')
        retained['phase'] = 'target-execute'
        return target.execute(args['experiment'], io=io, prepared_census=observed)
    except BaseException as primary:
        if retained['phase'] == 'target-execute':
            raise
        record = {'schema': 'newbrain.routing230.synthetic-calibration-bootstrap-failure.v1', 'retained': retained,
                  'original_traceback': ''.join(traceback.format_exception(primary)),
                  'IO_rows': io.rows, 'observers': io.observer_rows, 'preflight_failures': io.failure_details,
                  'failed_products': [{'name': r['name'], 'detail': r['detail'],
                      'raw_hex': r['raw'].hex() if type(r['raw']) is bytes else None} for r in io.failed_products],
                  'complete_unreturned_native_or_import_internal_capture': False}
        later_errors = []
        if graph_module is not None:
            try:
                graph, binary = graph_module.capture({'record': record, 'io': io, 'primary': primary},
                    (run_io.RunIO,), run_io.canonical)
                io.write('FAILED-AVAILABLE-DATA.bin', binary, graph_module.DATA_CAP, emergency=True)
                io.write('FAILED-AVAILABLE-STATE.json', run_io.canonical(graph), graph_module.GRAPH_CAP, emergency=True)
            except BaseException as later:
                later_errors.append(later)
            summary = {'schema': 'newbrain.routing230.synthetic-calibration-bootstrap-error-summary.v1',
                'original_traceback': ''.join(traceback.format_exception(primary)),
                'later_tracebacks': [''.join(traceback.format_exception(e)) for e in later_errors],
                'complete_supported_partial_bootstrap_in_graph_and_data': not later_errors,
                'unreturned_native_import_locals_retained': False}
            try:
                io.write('BOOTSTRAP-FAILURE.json', run_io.canonical(summary), 262144, emergency=True)
            except BaseException as later:
                later_errors.append(later)
        else:
            try:
                io.write('BOOTSTRAP-FAILURE.json', run_io.canonical(record), 2097152, emergency=True)
            except BaseException as later:
                later_errors.append(later)
        if later_errors:
            raise BaseExceptionGroup('Original branch bootstrap and capture failures', [primary]+later_errors)
        raise


if __name__ == '__main__':
    raise SystemExit(main())
