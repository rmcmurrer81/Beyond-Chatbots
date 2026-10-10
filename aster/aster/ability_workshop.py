"""Reviewed, finite text recipes over immutable ability proposals.

This is an in-process allowlisted interpreter, NOT an OS sandbox. Python and
shell source remain inert. Nothing in this module reads user files at run time,
opens a network connection, generates code, or writes transformation output.
"""
from contextlib import contextmanager
import hashlib
import json
from pathlib import Path
import sqlite3
import sys
import time
import unicodedata

from .abilities import Abilities
from .files import MAX_BYTES as MAX_PROPOSAL_BYTES
from .storage import text, token

FORMAT = 'aster.text-recipe.v1'
MAX_SOURCE_BYTES = 32768
MAX_INPUT_BYTES = 16384
MAX_OUTPUT_BYTES = 32768
MAX_STEPS = 16
MAX_CASES = 16
MAX_CASE_BYTES = 262144


class WorkshopBlocked(ValueError):
    """A stable, non-sensitive reason a workflow transition is unavailable."""
    def __init__(self, reason):
        self.reason = reason
        super().__init__(reason)


def _digest(value):
    return hashlib.sha256(value).hexdigest()


def _json(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'),
                      ensure_ascii=False, allow_nan=False)


def _string(value, limit):
    if type(value) is not str or len(value) > limit:
        raise ValueError('Expected bounded UTF-8 text')
    try:
        size = len(value.encode('utf-8'))
    except UnicodeError as error:
        raise ValueError('Expected valid UTF-8 text') from error
    if size > limit:
        raise ValueError('Text exceeds the byte limit')
    return value


def _keys(value, required):
    if type(value) is not dict or set(value) != set(required):
        raise ValueError('Unknown or missing recipe fields')


def _unique_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('Duplicate JSON fields are forbidden')
        result[key] = value
    return result


def _constant(_):
    raise ValueError('Nonfinite JSON numbers are forbidden')


def _decode(source):
    if type(source) is not bytes or not source or len(source) > MAX_SOURCE_BYTES:
        raise ValueError('Recipe source must be 1–32768 UTF-8 bytes')
    try:
        recipe = json.loads(source.decode('utf-8'), object_pairs_hook=_unique_pairs,
                            parse_constant=_constant)
    except (UnicodeError, RecursionError) as error:
        raise ValueError('Recipe must be bounded UTF-8 JSON') from error
    _keys(recipe, ('format', 'steps'))
    if recipe['format'] != FORMAT or type(recipe['format']) is not str:
        raise ValueError('Unsupported recipe format; Python and shell remain inert')
    steps = recipe['steps']
    if type(steps) is not list or not 1 <= len(steps) <= MAX_STEPS:
        raise ValueError('A recipe requires 1–16 steps')
    for step in steps:
        if type(step) is not dict or type(step.get('op')) is not str:
            raise ValueError('Every step requires a supported operation')
        op = step['op']
        if op in ('strip', 'uppercase', 'lowercase'):
            _keys(step, ('op',))
        elif op in ('prefix', 'suffix'):
            _keys(step, ('op', 'text'))
            _string(step['text'], MAX_INPUT_BYTES)
        elif op == 'replace':
            _keys(step, ('op', 'old', 'new'))
            _string(step['old'], MAX_INPUT_BYTES)
            _string(step['new'], MAX_INPUT_BYTES)
            if not step['old']:
                raise ValueError('Replacement search text cannot be empty')
        else:
            raise ValueError('Unsupported operation; no code or shell execution')
    return recipe


def _transform(recipe, value):
    value = _string(value, MAX_INPUT_BYTES)
    for step in recipe['steps']:
        op = step['op']
        if op == 'strip':
            value = value.strip()
        elif op == 'uppercase':
            value = value.upper()
        elif op == 'lowercase':
            value = value.lower()
        elif op == 'prefix':
            value = step['text'] + value
        elif op == 'suffix':
            value = value + step['text']
        elif op == 'replace':
            # Reject multiplicative expansion before allocating its result.
            size = len(value.encode('utf-8')) + value.count(step['old']) * (
                len(step['new'].encode('utf-8')) - len(step['old'].encode('utf-8')))
            if size > MAX_OUTPUT_BYTES:
                raise WorkshopBlocked('output_limit')
            value = value.replace(step['old'], step['new'])
        if len(value.encode('utf-8')) > MAX_OUTPUT_BYTES:
            raise WorkshopBlocked('output_limit')
    return value


class AbilityWorkshop:
    """Explicit test → review → install → preview → run; no implicit execution.

    Store and Files must share the existing owner-local state. The existing
    Abilities API creates immutable proposals; recipe proposals declare no
    external permissions (permissions=[]). Reviews made through the older API
    cannot substitute for a test-receipt-bound Workshop review.
    """
    def __init__(self, store, files):
        if files.store is not store:
            raise ValueError('Files and Workshop must use the same Store')
        self.store = store
        self.abilities = Abilities(store, files)
        # Bind behavior to both implementation bytes and Python's Unicode runtime.
        self.engine = {'source_sha256': _digest(Path(__file__).read_bytes()),
                       'python_implementation': sys.implementation.name,
                       'python_version': list(sys.version_info),
                       'unicode_version': unicodedata.unidata_version}
        self.engine_sha256 = _digest(_json(self.engine).encode('utf-8'))
        store.db.executescript('''
        CREATE TABLE IF NOT EXISTS workshop_tests (
            id TEXT PRIMARY KEY, proposal_id TEXT NOT NULL REFERENCES ability_proposals(id),
            at REAL NOT NULL, source_sha256 TEXT NOT NULL, engine_sha256 TEXT NOT NULL,
            cases_sha256 TEXT NOT NULL, case_count INTEGER NOT NULL,
            passed INTEGER NOT NULL CHECK(passed IN (0,1)),
            results TEXT NOT NULL, receipt_sha256 TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS workshop_reviews (
            id TEXT PRIMARY KEY, proposal_id TEXT NOT NULL REFERENCES ability_proposals(id),
            at REAL NOT NULL, source_sha256 TEXT NOT NULL,
            test_receipt_id TEXT REFERENCES workshop_tests(id),
            source_review_seq INTEGER NOT NULL REFERENCES ability_reviews(seq),
            verdict TEXT NOT NULL CHECK(verdict IN ('approved','rejected')));
        CREATE TABLE IF NOT EXISTS workshop_installations (
            seq INTEGER PRIMARY KEY, name TEXT NOT NULL,
            proposal_id TEXT NOT NULL REFERENCES ability_proposals(id), at REAL NOT NULL,
            source_sha256 TEXT NOT NULL, review_id TEXT NOT NULL REFERENCES workshop_reviews(id),
            test_receipt_id TEXT NOT NULL REFERENCES workshop_tests(id),
            previous_seq INTEGER REFERENCES workshop_installations(seq), kind TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS workshop_plans (
            id TEXT PRIMARY KEY, proposal_id TEXT NOT NULL REFERENCES ability_proposals(id),
            at REAL NOT NULL, installation_seq INTEGER NOT NULL REFERENCES workshop_installations(seq),
            source_sha256 TEXT NOT NULL, engine_sha256 TEXT NOT NULL,
            review_id TEXT NOT NULL REFERENCES workshop_reviews(id),
            test_receipt_id TEXT NOT NULL REFERENCES workshop_tests(id),
            input_text TEXT NOT NULL, input_sha256 TEXT NOT NULL,
            output_text TEXT NOT NULL, output_sha256 TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS workshop_runs (
            id TEXT PRIMARY KEY, plan_id TEXT NOT NULL UNIQUE REFERENCES workshop_plans(id),
            at REAL NOT NULL, input_sha256 TEXT NOT NULL, output_sha256 TEXT NOT NULL);
        ''')
        for table in ('workshop_tests', 'workshop_reviews', 'workshop_installations',
                      'workshop_plans', 'workshop_runs'):
            for action in ('UPDATE', 'DELETE'):
                store.db.execute(f'''CREATE TRIGGER IF NOT EXISTS {table}_no_{action.lower()}
                    BEFORE {action} ON {table} BEGIN
                    SELECT RAISE(ABORT, 'Workshop history is append-only'); END''')
        store.db.commit()

    @contextmanager
    def _write(self, operation):
        try:
            with self.store.db:
                yield
        except (ValueError, OSError, sqlite3.Error) as error:
            try:
                with self.store.db:
                    self.store.event('workshop.failed', {'operation': operation,
                                                         'error_type': type(error).__name__})
            except sqlite3.Error:
                pass
            raise

    def _row(self, proposal_id, source_sha256=None):
        row = self.abilities._row(proposal_id)
        if _digest(bytes(row['source'])) != row['source_sha256']:
            raise WorkshopBlocked('source_integrity_failed')
        if source_sha256 is not None and source_sha256 != row['source_sha256']:
            raise WorkshopBlocked('source_hash_mismatch')
        return row

    def _recipe(self, row):
        if json.loads(row['permissions']) != []:
            raise WorkshopBlocked('external_permissions_unsupported')
        try:
            return _decode(bytes(row['source']))
        except ValueError as error:
            raise WorkshopBlocked('unsupported_recipe') from error

    def _latest_test(self, proposal_id):
        return self.store.db.execute('SELECT * FROM workshop_tests WHERE proposal_id=? '
                                     'ORDER BY rowid DESC LIMIT 1', (proposal_id,)).fetchone()

    def _latest_review(self, proposal_id):
        return self.store.db.execute('SELECT * FROM workshop_reviews WHERE proposal_id=? '
                                     'ORDER BY rowid DESC LIMIT 1', (proposal_id,)).fetchone()

    def _installation(self, name):
        self.abilities._name(name)
        return self.store.db.execute('SELECT * FROM workshop_installations WHERE name=? '
                                     'ORDER BY seq DESC LIMIT 1', (name,)).fetchone()

    @staticmethod
    def _receipt_body(receipt):
        return {key: receipt[key] for key in ('id', 'proposal_id', 'source_sha256',
                'engine_sha256', 'cases_sha256', 'case_count', 'passed', 'results')}

    def _passing_test(self, row, receipt_id):
        latest = self._latest_test(row['id'])
        if latest is None:
            raise WorkshopBlocked('tests_required')
        if latest['id'] != receipt_id:
            raise WorkshopBlocked('test_receipt_stale')
        if latest['source_sha256'] != row['source_sha256']:
            raise WorkshopBlocked('test_source_mismatch')
        if latest['engine_sha256'] != self.engine_sha256:
            raise WorkshopBlocked('test_engine_stale')
        if _digest(_json(self._receipt_body(latest)).encode('utf-8')) != latest['receipt_sha256']:
            raise WorkshopBlocked('test_receipt_integrity_failed')
        if latest['passed'] != 1:
            raise WorkshopBlocked('tests_failed')
        return latest

    def _gate(self, row):
        self._recipe(row)
        source_review = self.abilities._review(row['id'])
        review = self._latest_review(row['id'])
        if source_review is not None and source_review['verdict'] == 'rejected':
            raise WorkshopBlocked('review_rejected')
        if review is None or source_review is None:
            raise WorkshopBlocked('review_required')
        if review['verdict'] != 'approved':
            raise WorkshopBlocked('review_rejected')
        if (review['source_review_seq'] != source_review['seq']
                or source_review['source_sha256'] != row['source_sha256']
                or review['source_sha256'] != row['source_sha256']):
            raise WorkshopBlocked('review_stale')
        receipt = self._passing_test(row, review['test_receipt_id'])
        return review, receipt

    def test(self, proposal_id, source_sha256, cases):
        """Run 1–16 isolated examples in memory; persist hashes and actual results."""
        with self._write('test'):
            row = self._row(proposal_id, source_sha256)
            if type(source_sha256) is not str:
                raise WorkshopBlocked('source_hash_required')
            recipe = self._recipe(row)
            if type(cases) is not list or not 1 <= len(cases) <= MAX_CASES:
                raise ValueError('Provide 1–16 input/expected test cases')
            size = 0
            for case in cases:
                _keys(case, ('input', 'expected'))
                _string(case['input'], MAX_INPUT_BYTES)
                _string(case['expected'], MAX_OUTPUT_BYTES)
                size += len(case['input'].encode('utf-8')) + len(case['expected'].encode('utf-8'))
            if size > MAX_CASE_BYTES:
                raise ValueError('Combined test text exceeds 256 KiB')
            results = []
            for index, case in enumerate(cases):
                result = {'index': index, 'input_sha256': _digest(case['input'].encode('utf-8')),
                          'expected_sha256': _digest(case['expected'].encode('utf-8'))}
                try:
                    actual = _transform(recipe, case['input'])
                    result.update(passed=actual == case['expected'],
                                  actual_sha256=_digest(actual.encode('utf-8')), error=None)
                except WorkshopBlocked as error:
                    result.update(passed=False, actual_sha256=None, error=error.reason)
                results.append(result)
            receipt = {'id': token(), 'proposal_id': row['id'], 'at': time.time(),
                       'source_sha256': row['source_sha256'], 'engine_sha256': self.engine_sha256,
                       'cases_sha256': _digest(_json(cases).encode('utf-8')), 'case_count': len(cases),
                       'passed': int(all(r['passed'] for r in results)), 'results': _json(results)}
            receipt['receipt_sha256'] = _digest(_json(self._receipt_body(receipt)).encode('utf-8'))
            self.store.db.execute('INSERT INTO workshop_tests VALUES '
                '(:id,:proposal_id,:at,:source_sha256,:engine_sha256,:cases_sha256,:case_count,'
                ':passed,:results,:receipt_sha256)', receipt)
            self.store.event('workshop.tested', {'id': receipt['id'], 'proposal_id': row['id'],
                                               'passed': bool(receipt['passed']),
                                               'source_sha256': row['source_sha256']})
        receipt.update(passed=bool(receipt['passed']), results=results, tests_executed=True,
                       isolation='bounded_in_memory_interpreter', os_sandbox=False)
        return receipt

    def review(self, proposal_id, verdict, note, source_sha256, test_receipt_id=None):
        """An owner declaration binds the latest real test receipt and exact source."""
        with self._write('review'):
            row = self._row(proposal_id, source_sha256)
            if type(source_sha256) is not str:
                raise WorkshopBlocked('source_hash_required')
            if type(verdict) is not str or verdict not in ('approved', 'rejected'):
                raise ValueError('Review verdict must be approved or rejected')
            text(note, 2048)
            if verdict == 'approved':
                self._recipe(row)
                self._passing_test(row, test_receipt_id)
            elif test_receipt_id is not None:
                # A rejection may cite a failing receipt, but not an unrelated one.
                receipt = self._latest_test(row['id'])
                if receipt is None or receipt['id'] != test_receipt_id:
                    raise WorkshopBlocked('test_receipt_stale')
            at, id_ = time.time(), token()
            cursor = self.store.db.execute('INSERT INTO ability_reviews'
                '(proposal_id,at,verdict,note,source_sha256) VALUES (?,?,?,?,?)',
                (row['id'], at, verdict, note, row['source_sha256']))
            self.store.db.execute('INSERT INTO workshop_reviews VALUES (?,?,?,?,?,?,?)',
                (id_, row['id'], at, row['source_sha256'], test_receipt_id, cursor.lastrowid, verdict))
            self.store.event('workshop.reviewed', {'id': id_, 'proposal_id': row['id'],
                             'verdict': verdict, 'test_receipt_id': test_receipt_id,
                             'source_sha256': row['source_sha256']})
        return dict(self._latest_review(row['id']))

    def _record_install(self, row, review, receipt, previous_seq, kind):
        cursor = self.store.db.execute('INSERT INTO workshop_installations'
            '(name,proposal_id,at,source_sha256,review_id,test_receipt_id,previous_seq,kind) '
            'VALUES (?,?,?,?,?,?,?,?)', (row['name'], row['id'], time.time(), row['source_sha256'],
                                        review['id'], receipt['id'], previous_seq, kind))
        self.store.event('workshop.' + kind, {'installation_seq': cursor.lastrowid,
                         'proposal_id': row['id'], 'source_sha256': row['source_sha256']})
        return cursor.lastrowid

    def install(self, proposal_id, source_sha256, review_id):
        """Select a reviewed recipe. Does not run it or grant external permissions."""
        with self._write('install'):
            row = self._row(proposal_id, source_sha256)
            if type(source_sha256) is not str:
                raise WorkshopBlocked('source_hash_required')
            review, receipt = self._gate(row)
            if review['id'] != review_id:
                raise WorkshopBlocked('review_stale')
            current = self._installation(row['name'])
            if current is not None and current['proposal_id'] == row['id'] and current['review_id'] == review_id:
                raise WorkshopBlocked('already_installed')
            self._record_install(row, review, receipt, current['seq'] if current else None, 'installed')
        return self.get(row['id'])

    def rollback(self, name):
        """Append restoration of the prior installed version, only if still eligible."""
        with self._write('rollback'):
            current = self._installation(name)
            if current is None or current['previous_seq'] is None:
                raise WorkshopBlocked('no_prior_installation')
            previous = self.store.db.execute('SELECT * FROM workshop_installations WHERE seq=?',
                                             (current['previous_seq'],)).fetchone()
            row = self._row(previous['proposal_id'])
            review, receipt = self._gate(row)
            self._record_install(row, review, receipt, previous['previous_seq'], 'rolled_back')
        return self.get(row['id'])

    def _runnable(self, name):
        installation = self._installation(name)
        if installation is None:
            raise WorkshopBlocked('not_installed')
        row = self._row(installation['proposal_id'])
        review, receipt = self._gate(row)
        if (installation['review_id'] != review['id'] or installation['test_receipt_id'] != receipt['id']
                or installation['source_sha256'] != row['source_sha256']):
            raise WorkshopBlocked('installation_stale')
        return installation, row, review, receipt

    def preview_run(self, name, input_text):
        """Prepare exact in-memory inputs/output for review; no external side effects.

        The returned plan is single use. run(plan_id, input_sha256) is a separate
        explicit call. New tests, reviews or installations invalidate old plans.
        """
        with self._write('preview_run'):
            installation, row, review, receipt = self._runnable(name)
            input_text = _string(input_text, MAX_INPUT_BYTES)
            output = _transform(self._recipe(row), input_text)
            plan = {'id': token(), 'proposal_id': row['id'], 'at': time.time(),
                    'installation_seq': installation['seq'], 'source_sha256': row['source_sha256'],
                    'engine_sha256': self.engine_sha256, 'review_id': review['id'],
                    'test_receipt_id': receipt['id'], 'input_text': input_text,
                    'input_sha256': _digest(input_text.encode('utf-8')), 'output_text': output,
                    'output_sha256': _digest(output.encode('utf-8'))}
            self.store.db.execute('INSERT INTO workshop_plans VALUES '
                '(:id,:proposal_id,:at,:installation_seq,:source_sha256,:engine_sha256,:review_id,'
                ':test_receipt_id,:input_text,:input_sha256,:output_text,:output_sha256)', plan)
            self.store.event('workshop.run_prepared', {'id': plan['id'], 'proposal_id': row['id'],
                                                      'input_sha256': plan['input_sha256']})
        plan.update(status='awaiting_explicit_run', output_is_preview=True,
                    permissions_granted=[], external_effects=[])
        return plan

    def run(self, plan_id, input_sha256):
        """Explicit, single-use invocation of the exact previously previewed input."""
        with self._write('run'):
            text(plan_id, 64)
            plan = self.store.db.execute('SELECT * FROM workshop_plans WHERE id=?', (plan_id,)).fetchone()
            if plan is None:
                raise WorkshopBlocked('unknown_run_plan')
            if type(input_sha256) is not str or plan['input_sha256'] != input_sha256:
                raise WorkshopBlocked('input_hash_mismatch')
            if self.store.db.execute('SELECT 1 FROM workshop_runs WHERE plan_id=?', (plan_id,)).fetchone():
                raise WorkshopBlocked('run_plan_already_used')
            row = self._row(plan['proposal_id'])
            installation, row, review, receipt = self._runnable(row['name'])
            if (installation['seq'] != plan['installation_seq'] or row['id'] != plan['proposal_id']
                    or row['source_sha256'] != plan['source_sha256']
                    or review['id'] != plan['review_id'] or receipt['id'] != plan['test_receipt_id']
                    or self.engine_sha256 != plan['engine_sha256']):
                raise WorkshopBlocked('run_plan_stale')
            if _digest(plan['input_text'].encode('utf-8')) != input_sha256:
                raise WorkshopBlocked('run_plan_integrity_failed')
            output = _transform(self._recipe(row), plan['input_text'])
            if output != plan['output_text'] or _digest(output.encode('utf-8')) != plan['output_sha256']:
                raise WorkshopBlocked('run_plan_integrity_failed')
            id_ = token()
            self.store.db.execute('INSERT INTO workshop_runs VALUES (?,?,?,?,?)',
                (id_, plan_id, time.time(), input_sha256, plan['output_sha256']))
            self.store.event('workshop.ran', {'id': id_, 'plan_id': plan_id,
                                             'proposal_id': row['id'], 'output_sha256': plan['output_sha256']})
        return {'id': id_, 'plan_id': plan_id, 'proposal_id': row['id'], 'status': 'completed',
                'output_text': output, 'input_sha256': input_sha256, 'output_sha256': plan['output_sha256'],
                'permissions_granted': [], 'external_effects': [], 'code_executed': False,
                'recipe_interpreted': True, 'os_sandbox': False}

    def get(self, proposal_id):
        """Capability state for UI consumers; never treats a stored pointer as approval."""
        row = self._row(proposal_id)
        latest_test, review = self._latest_test(row['id']), self._latest_review(row['id'])
        installation = self._installation(row['name'])
        recorded = installation is not None and installation['proposal_id'] == row['id']
        reason = None
        try:
            gate_review, receipt = self._gate(row)
            if recorded and (installation['review_id'] != gate_review['id']
                             or installation['test_receipt_id'] != receipt['id']):
                reason = 'installation_stale'
        except WorkshopBlocked as error:
            reason = error.reason
        return {'id': row['id'], 'name': row['name'], 'version': row['version'],
                'source_sha256': row['source_sha256'], 'engine_sha256': self.engine_sha256,
                'status': ('installed' if recorded else 'ready_to_install') if reason is None else
                          ('installed_blocked' if recorded else 'blocked'),
                'blocked_reason': reason, 'installation_recorded': recorded,
                'installation_seq': installation['seq'] if recorded else None,
                'test_receipt_id': latest_test['id'] if latest_test else None,
                'tests_executed': latest_test is not None,
                'latest_tests_passed': bool(latest_test['passed']) if latest_test else None,
                'review_id': review['id'] if review else None,
                'can_run': bool(recorded and reason is None),
                'permissions_granted': [], 'python_execution_enabled': False,
                'shell_execution_enabled': False, 'os_sandbox': False}

    def source(self, proposal_id):
        """Inspect exact snapshotted source without interpretation or approval gates.

        Valid UTF-8 is returned verbatim, including unsupported Python/shell
        text. Invalid UTF-8 has source_text=None with an explicit reason. Treat
        source_text as untrusted display text; never evaluate it or render HTML.
        """
        row = self._row(proposal_id)
        source = bytes(row['source'])
        if len(source) > MAX_PROPOSAL_BYTES:
            raise WorkshopBlocked('source_inspection_limit')
        source_text, recipe, reason = None, None, None
        try:
            source_text = source.decode('utf-8')
        except UnicodeError:
            reason = 'invalid_utf8'
        if reason is None:
            try:
                recipe = self._recipe(row)
            except WorkshopBlocked as error:
                reason = error.reason
        return {'id': row['id'], 'name': row['name'], 'version': row['version'],
                'source_sha256': row['source_sha256'], 'source_bytes': len(source),
                'source_text': source_text, 'utf8_valid': source_text is not None,
                'recipe': recipe, 'recipe_supported': recipe is not None,
                'status': 'supported_recipe' if recipe is not None else 'unsupported_source',
                'unsupported_reason': reason, 'permissions_granted': [],
                'python_execution_enabled': False, 'shell_execution_enabled': False}

    def list(self):
        return [self.get(row['id']) for row in self.store.db.execute(
            'SELECT id FROM ability_proposals ORDER BY rowid DESC LIMIT 100').fetchall()]

    def history(self, name):
        self.abilities._name(name)
        rows = [dict(row) for row in self.store.db.execute(
            'SELECT * FROM workshop_installations WHERE name=? ORDER BY seq DESC LIMIT 100', (name,))]
        count = self.store.db.execute('SELECT COUNT(*) FROM workshop_installations WHERE name=?',
                                      (name,)).fetchone()[0]
        return {'name': name, 'installations': rows, 'count': count, 'truncated': count > len(rows)}

    def receipt(self, receipt_id):
        """Read an immutable test receipt without exposing example text."""
        text(receipt_id, 64)
        row = self.store.db.execute('SELECT * FROM workshop_tests WHERE id=?', (receipt_id,)).fetchone()
        if row is None:
            raise WorkshopBlocked('unknown_test_receipt')
        result = dict(row)
        result.update(passed=bool(row['passed']), results=json.loads(row['results']),
                      tests_executed=True, isolation='bounded_in_memory_interpreter', os_sandbox=False)
        return result

    def installed(self, name):
        """Current recorded version and live eligibility, including revocation."""
        row = self._installation(name)
        if row is None:
            return {'name': name, 'status': 'not_installed', 'can_run': False,
                    'installation_recorded': False, 'id': None}
        return self.get(row['proposal_id'])

    def status(self):
        """No model dependency, code execution, external permissions or OS sandbox."""
        names = self.store.db.execute('SELECT name, MAX(seq) AS latest FROM workshop_installations '
                                      'GROUP BY name ORDER BY latest DESC LIMIT 100').fetchall()
        count = self.store.db.execute('SELECT COUNT(DISTINCT name) FROM workshop_installations').fetchone()[0]
        return {'status': 'available', 'format': FORMAT, 'engine_sha256': self.engine_sha256,
                'engine': {**self.engine, 'python_version': list(self.engine['python_version'])},
                'capabilities': {'bounded_recipe_tests': 'available', 'reviewed_install': 'available',
                                 'rollback': 'available', 'explicit_pure_run': 'available',
                                 'python_execution': 'unsupported', 'shell_execution': 'unsupported',
                                 'file_writes': 'unsupported', 'code_generation': 'unavailable',
                                 'os_sandbox': 'unavailable'},
                'limits': {'source_bytes': MAX_SOURCE_BYTES, 'input_bytes': MAX_INPUT_BYTES,
                           'output_bytes': MAX_OUTPUT_BYTES, 'steps': MAX_STEPS,
                           'test_cases': MAX_CASES, 'combined_test_bytes': MAX_CASE_BYTES,
                           'wall_clock_timeout': None},
                'isolation': 'bounded_in_memory_interpreter', 'permissions_granted': [],
                'installed': [self.installed(row['name']) for row in names],
                'installation_names_count': count, 'truncated': count > len(names)}
