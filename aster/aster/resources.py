"""Admission budgets for Aster's finite queue, not OS process isolation.

No process is launched or killed. RAM requests are owner estimates checked before
an on-demand job; the existing MemoryGuard still controls every job. GPU jobs
fail closed until a measured GPU executor exists.
"""
import json
import time

MIB = 1024 * 1024


def integer(value, low, high, label):
    if type(value) is not int or not low <= value <= high:
        raise ValueError(f'{label} must be an integer from {low} to {high}')
    return value


class ResourceSupervisor:
    def __init__(self, store):
        self.store = store
        store.db.executescript('''
        CREATE TABLE IF NOT EXISTS resource_policy (
            id INTEGER PRIMARY KEY CHECK(id=1), max_ram_mib INTEGER NOT NULL,
            reserve_ram_mib INTEGER NOT NULL, max_pending INTEGER NOT NULL);
        INSERT OR IGNORE INTO resource_policy VALUES (1,512,256,256);
        CREATE TABLE IF NOT EXISTS job_resources (
            job_id TEXT PRIMARY KEY REFERENCES jobs(id), ram_mib INTEGER,
            gpu_mib INTEGER NOT NULL CHECK(gpu_mib=0));
        ''')
        store.db.commit()

    def policy(self):
        row = dict(self.store.db.execute('SELECT * FROM resource_policy WHERE id=1').fetchone())
        row.pop('id')
        return row

    def configure(self, max_ram_mib=512, reserve_ram_mib=256, max_pending=256):
        integer(max_ram_mib, 1, 4096, 'Per-job estimated RAM ceiling (MiB)')
        integer(reserve_ram_mib, 0, 8192, 'Available RAM reserve (MiB)')
        integer(max_pending, 1, 1000, 'Pending queue limit')
        with self.store.db:
            self.store.db.execute('UPDATE resource_policy SET max_ram_mib=?,reserve_ram_mib=?,max_pending=? WHERE id=1',
                                  (max_ram_mib, reserve_ram_mib, max_pending))
            self.store.event('resources.configured', {'max_ram_mib': max_ram_mib,
                'reserve_ram_mib': reserve_ram_mib, 'max_pending': max_pending})
        return self.status()

    def validate_request(self, ram_mib=None, gpu_mib=0):
        if gpu_mib != 0 or type(gpu_mib) is not int:
            raise ValueError('GPU execution is unavailable; GPU requests must be integer zero')
        policy = self.policy()
        if ram_mib is not None:
            integer(ram_mib, 1, policy['max_ram_mib'], 'Estimated RAM (MiB)')
        pending = self.store.db.execute("SELECT count(*) FROM jobs WHERE status IN ('queued','paused','running')").fetchone()[0]
        if pending >= policy['max_pending']:
            raise ValueError('Aster pending queue limit reached; finish or cancel a job first')

    def record_request(self, job_id, ram_mib, gpu_mib):
        # Called within Jobs.submit's transaction, never separately commits it.
        self.store.db.execute('INSERT INTO job_resources VALUES (?,?,?)', (job_id, ram_mib, gpu_mib))

    def admission(self, job_id, memory):
        row = self.store.db.execute('SELECT * FROM job_resources WHERE job_id=?', (job_id,)).fetchone()
        if row is None or row['ram_mib'] is None:
            return {'allowed': True, 'state': 'legacy_bounded_action_no_ram_estimate',
                    'ram_enforced_by_os': False, 'gpu_enabled': False}
        ram = row['ram_mib']
        policy = self.policy()
        observation = memory.get('observation') or {}
        available = observation.get('available_bytes')
        reason = 'estimated_ram_within_budget'
        allowed = True
        if type(ram) is not int or not 1 <= ram <= policy['max_ram_mib'] or row['gpu_mib'] != 0:
            allowed, reason = False, 'request_exceeds_current_policy'
        elif type(available) is not int or available < 0:
            allowed, reason = False, 'available_ram_unknown'
        elif available < (ram + policy['reserve_ram_mib']) * MIB:
            allowed, reason = False, 'insufficient_available_ram_after_reserve'
        return {'allowed': allowed, 'state': reason, 'ram_mib': ram,
                'available_bytes': available, 'reserve_ram_mib': policy['reserve_ram_mib'],
                'ram_enforced_by_os': False, 'gpu_enabled': False}

    def status(self):
        counts = {r['status']: r['n'] for r in self.store.db.execute('SELECT status,count(*) AS n FROM jobs GROUP BY status')}
        rows = [dict(r) for r in self.store.db.execute('''SELECT j.id,j.action,j.status,j.budget,
            r.ram_mib,r.gpu_mib FROM jobs j LEFT JOIN job_resources r ON j.id=r.job_id
            ORDER BY j.rowid DESC LIMIT 100''')]
        return {'state': 'local_admission_budgets', 'policy': self.policy(), 'jobs': rows,
                'job_counts': counts, 'concurrent_jobs': 1, 'on_demand_only': True,
                'ram_budget_kind': 'owner_estimate_admission_only', 'hard_ram_limit': False,
                'wall_budget_kind': 'measured_after_bounded_action', 'hard_timeout': False,
                'cancel_scope': 'queued_or_paused_before_execution',
                'gpu': {'state': 'unavailable', 'execution_enabled': False, 'measured_bytes': None},
                'process_launch_enabled': False, 'external_app_control_enabled': False}
