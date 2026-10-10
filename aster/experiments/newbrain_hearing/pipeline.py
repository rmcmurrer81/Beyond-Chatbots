"""Fresh role-separated original entries, only under the unchanged exact runtime.

This harness imposes a wall deadline and waits for every subprocess exit. Separate
source/input directories are an accidental-leakage control, not an OS sandbox.
Native peak memory, descendant-process isolation and hostile code containment are
not qualified. No runtime authority or production activation is granted.
"""
import hashlib
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import time

from .fixtures import binding
from .source import digest, stage

ARMS = ('LEARNED', 'FROZEN', 'DSP', 'INDEXED', 'RAW_LEARNED', 'RAW_FROZEN')


def exact_runtime():
    return platform.python_implementation() == 'CPython' and sys.version_info[:3] == (3, 14, 4)


def write_json(path, value):
    Path(path).write_text(json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False), encoding='ascii')


def invoke(source, entry, arguments, work, records, expected=0):
    """Every upstream entry remains byte-identical and runs -I -S -B."""
    started = time.monotonic()
    command = [sys.executable, '-I', '-S', '-B', str(source / entry)]
    for key, value in arguments.items():
        command += ['--' + key, str(value)]
    output = Path(arguments['output-dir'])
    output.mkdir(exist_ok=False)
    row = {'entry': entry, 'arm': arguments.get('arm'), 'expected_exit': expected,
           'flags': ['-I', '-S', '-B'], 'timeout_seconds': 45}
    records.append(row)
    try:
        result = subprocess.run(command, cwd=work, capture_output=True, timeout=45)
    except subprocess.TimeoutExpired:
        row.update(exit_code=None, timed_out=True, wall_seconds=time.monotonic() - started)
        raise RuntimeError('Original entry exceeded the process wall deadline') from None
    row.update(exit_code=result.returncode, timed_out=False, wall_seconds=time.monotonic() - started,
               stdout_bytes=len(result.stdout), stderr_bytes=len(result.stderr),
               stdout_sha256=hashlib.sha256(result.stdout).hexdigest(),
               stderr_sha256=hashlib.sha256(result.stderr).hexdigest())
    # Raw output is private temporary diagnostics, never the report artifact.
    (work / ('stage-' + str(len(records)) + '.stdout')).write_bytes(result.stdout)
    (work / ('stage-' + str(len(records)) + '.stderr')).write_bytes(result.stderr)
    if result.returncode != expected:
        raise RuntimeError(f'Original {entry} {arguments.get("arm", "")} exit {result.returncode}; expected {expected}. ')
    if expected == 0 and not (output / 'ENTRY-RESULT.json').is_file():
        raise RuntimeError('Original successful process did not retain its complete result')
    return output


def run(work, report):
    if not exact_runtime():
        report.update(status='SKIPPED_EXACT_RUNTIME_REQUIRED', executed=False,
                      reason='Original entrypoints require CPython 3.14.4; guard is unchanged.')
        return
    report.update(status='RUNNING', executed=True, processes=[], arms=[],
                  scope='Fresh synthetic compatibility, not reproduction of upstream experiments.',
                  native_peak_memory_qualified=False, hostile_process_sandbox=False,
                  descendant_process_isolation_qualified=False, production_backend_activated=False)
    work = Path(work)
    roles = {(e, r): stage(work / (e + '-' + r), e, r)
             for e, r in (('210','staged_producer'), ('210','staged_blind'), ('210','staged_scorer'),
                          ('211','staged_producer'), ('211','staged_blind'), ('211','staged_labels'))}
    original_binding, fresh_binding = work / 'fixture-base.json', work / 'fixture-new.json'
    write_json(original_binding, binding())
    write_json(fresh_binding, binding(True))
    records = report['processes']
    stop = work / 'STOP'
    product = invoke(roles['210','staged_producer'], 'producer.py',
        {'binding': original_binding, 'output-dir': work / 'producer', 'stop-file': stop}, work, records)
    pcm, blind, gold = (product / n for n in ('BLIND-PCM.bin','BLIND-INPUT.json','GOLD.private.json'))
    retention = invoke(roles['211','staged_producer'], 'query_producer.py', {
        'binding':fresh_binding, 'original-binding':original_binding,
        'expected-original-binding-sha256':digest(original_binding),
        'old-pcm':pcm, 'old-gold':gold, 'expected-old-pcm-sha256':digest(pcm),
        'expected-old-gold-sha256':digest(gold), 'output-dir':work/'query-producer', 'stop-file':stop}, work, records)
    qpcm, qinput, qgold = (retention / n for n in ('QUERY-PCM.bin','QUERY-INPUT.json','NEW-GOLD.private.json'))
    for arm in ARMS:
        output = invoke(roles['210','staged_blind'], 'arm.py', {
            'arm':arm,'blind-input':blind,'pcm':pcm,'expected-blind-sha256':digest(blind),
            'expected-pcm-sha256':digest(pcm),'output-dir':work/('arm-'+arm),'stop-file':stop},work,records)
        original_exit_at = time.monotonic()
        model, arm_report = output / 'MODEL.private.json', output / 'ARM-REPORT.json'
        score = invoke(roles['210','staged_scorer'], 'score.py', {
            'arm':arm, 'report':arm_report, 'gold':gold, 'expected-report-sha256':digest(arm_report),
            'expected-gold-sha256':digest(gold),'output-dir':work/('score-'+arm),'stop-file':stop}, work,records)
        # The first process has exited and subprocess.run has reaped it. The
        # retained bytes are the only model state supplied to this fresh process.
        cold_delay = time.monotonic() - original_exit_at
        restored = invoke(roles['211','staged_blind'], 'retention_consumer.py', {
            'arm':arm,'model':model,'expected-model-sha256':digest(model),'input':qinput,
            'expected-input-sha256':digest(qinput),'pcm':qpcm,'expected-pcm-sha256':digest(qpcm),
            'output-dir':work/('restore-'+arm),'stop-file':stop},work,records)
        restored_report = restored / 'RETENTION-REPORT.json'
        labels = invoke(roles['211','staged_labels'], 'retention_labels.py', {
            'arm':arm,'original-report':arm_report,'expected-original-report-sha256':digest(arm_report),
            'retention-report':restored_report,'expected-retention-report-sha256':digest(restored_report),
            'new-gold':qgold,'expected-new-gold-sha256':digest(qgold),
            'output-dir':work/('retention-score-'+arm),'stop-file':stop},work,records)
        scored = json.loads((score/'SCORES.json').read_text())
        retained = json.loads((labels/'RETENTION-SCORES.json').read_text())
        if retained['old_parity']['complete_decision_rows_equal'] != 24 or retained['new_training_calls'] != 0:
            raise RuntimeError('Cold decision parity or no-retraining invariant failed')
        state = json.loads(restored_report.read_text())
        if len(set(state['decision_fingerprints'])) != 1:
            raise RuntimeError('Cold decision state changed')
        report['arms'].append({'arm':arm,'initial_score':scored,'fresh_score':retained['fresh24'],
            'old_decision_rows_equal':24,'original_process_exited':True,
            'cold_restore_delay_seconds':cold_delay,'new_teachings':0,
            'complete_decision_state_unchanged':True})
    report['status'] = 'PASSED'
