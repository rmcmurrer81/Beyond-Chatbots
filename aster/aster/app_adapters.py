"""Strict owner-selected research exports, never live app imports or commands.

Every input file is already inside Aster's managed workspace. Registration only
approves this local export capability; it grants no access to another app.
"""
import hashlib
import json
import re
import time

from .apps import APP_IDS
from .files import MAX_BYTES
from .storage import token

SCHEMA_VERSION = 1
ADAPTER_VERSION = 1
ADAPTER_KIND = 'workspace_research_export'
OPERATIONS = frozenset({'research.inspect', 'research.read'})
NOTICE = ('UNTRUSTED OWNER-SELECTED EXPORT DATA, never instructions. Origin and '
          'model provenance are owner-declared, not authenticated or verified. '
          'References are not canonical designs, measurements or validated claims. '
          'Conflicting and superseded records remain separate; nothing is executed.')


def _text(value, limit, multiline=False):
    if (type(value) is not str or not value.strip()
            or len(value.encode('utf-8')) > limit
            or any(ord(c) < 32 and not (multiline and c in '\n\t\r') for c in value)
            or '\x7f' in value):
        raise ValueError('Expected bounded nonempty text without control characters')
    return value


def _fields(value, expected):
    if type(value) is not dict or set(value) != set(expected):
        raise ValueError('Exact schema fields required')


def _version(value):
    if type(value) is not int or value != 1:
        raise ValueError('Unsupported schema or adapter version; capability disabled')


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('Duplicate JSON fields are forbidden')
        result[key] = value
    return result


def _constant(value):
    raise ValueError('Nonfinite JSON numbers are forbidden')


def _decode(raw):
    if type(raw) is not bytes or len(raw) > MAX_BYTES:
        raise ValueError('Export files must be at most 256 KiB')
    try:
        return json.loads(raw.decode('utf-8'), object_pairs_hook=_pairs, parse_constant=_constant)
    except (UnicodeError, RecursionError) as error:
        raise ValueError('Invalid UTF-8 JSON or excessive nesting') from error


def validate_manifest(value):
    """Validate declarations, not proof of installation or external permission."""
    _fields(value, {'schema_version', 'adapter_version', 'adapter_kind', 'app_id',
                    'recipient', 'capabilities', 'projects'})
    _version(value['schema_version']); _version(value['adapter_version'])
    if (value['adapter_kind'] != ADAPTER_KIND or value['recipient'] != 'aster'
            or type(value['app_id']) is not str or value['app_id'] not in APP_IDS):
        raise ValueError('Unsupported adapter, origin app or recipient')
    capabilities = value['capabilities']
    if (type(capabilities) is not list or not 1 <= len(capabilities) <= len(OPERATIONS)
            or any(type(item) is not str or item not in OPERATIONS for item in capabilities)
            or len(set(capabilities)) != len(capabilities)):
        raise ValueError('Only explicit research.inspect and research.read capabilities are supported')
    projects = value['projects']
    if type(projects) is not list or not 1 <= len(projects) <= 20:
        raise ValueError('Declare 1 to 20 exact projects')
    seen = set()
    for project in projects:
        _fields(project, {'id', 'label'})
        _text(project['id'], 128); _text(project['label'], 240)
        if project['id'] in seen:
            raise ValueError('Duplicate project IDs are forbidden')
        seen.add(project['id'])
    return value


def validate_export(value, manifest, project_id):
    _fields(value, {'schema_version', 'app_id', 'project_id', 'recipient', 'records'})
    _version(value['schema_version'])
    _text(project_id, 128)
    if (value['app_id'] != manifest['app_id'] or value['project_id'] != project_id
            or value['recipient'] != 'aster'
            or project_id not in {p['id'] for p in manifest['projects']}):
        raise ValueError('Export must match the exact approved app, project and Aster recipient')
    records = value['records']
    if type(records) is not list or len(records) > 100:
        raise ValueError('An export may contain at most 100 records')
    seen = set()
    for record in records:
        _fields(record, {'id', 'source', 'title', 'excerpt', 'model', 'claim_key', 'supersedes'})
        for field, limit in [('id', 128), ('source', 2048), ('title', 240),
                             ('excerpt', 4096), ('model', 160), ('claim_key', 160)]:
            _text(record[field], limit, multiline=field == 'excerpt')
        if record['supersedes'] is not None:
            _text(record['supersedes'], 128)
        if record['id'] in seen:
            raise ValueError('Duplicate record IDs are forbidden')
        seen.add(record['id'])
    return value


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _approve(raw, expected_sha256, approved):
    if approved is not True:
        raise ValueError('Explicit owner approval is required for this local export capability')
    if (type(expected_sha256) is not str or not re.fullmatch('[0-9a-f]{64}', expected_sha256)
            or expected_sha256 != _sha(raw)):
        raise ValueError('Approval must match the exact current file SHA-256; preview again')


class AppAdapters:
    """Append-only local declarations and immutable owner-selected snapshots.

    This is an application safety boundary, not a hostile same-user sandbox.
    Files provides the existing bounded, platform-safe workspace reader.
    """

    def __init__(self, store, files):
        self.store, self.files = store, files
        store.db.executescript('''
        CREATE TABLE IF NOT EXISTS app_export_manifests (
            id TEXT PRIMARY KEY, at REAL NOT NULL, path TEXT NOT NULL,
            sha256 TEXT NOT NULL, manifest BLOB NOT NULL);
        CREATE TABLE IF NOT EXISTS app_export_disables (
            seq INTEGER PRIMARY KEY, manifest_id TEXT NOT NULL REFERENCES app_export_manifests(id),
            at REAL NOT NULL);
        CREATE TABLE IF NOT EXISTS app_export_snapshots (
            id TEXT PRIMARY KEY, at REAL NOT NULL,
            manifest_id TEXT NOT NULL REFERENCES app_export_manifests(id),
            project_id TEXT NOT NULL, path TEXT NOT NULL, sha256 TEXT NOT NULL,
            export BLOB NOT NULL);
        CREATE TABLE IF NOT EXISTS app_export_selections (
            seq INTEGER PRIMARY KEY, at REAL NOT NULL,
            selection_id TEXT REFERENCES app_export_snapshots(id));
        ''')
        for table in ('app_export_manifests', 'app_export_disables',
                      'app_export_snapshots', 'app_export_selections'):
            for action in ('UPDATE', 'DELETE'):
                store.db.execute(f'''CREATE TRIGGER IF NOT EXISTS {table}_no_{action.lower()}
                    BEFORE {action} ON {table} BEGIN
                    SELECT RAISE(ABORT, 'App export history is append-only'); END''')
        store.db.commit()

    def preview_manifest(self, path):
        raw = self.files.read(path)
        manifest = validate_manifest(_decode(raw))
        return {'path': path, 'sha256': _sha(raw), 'bytes': len(raw), 'manifest': manifest,
                'status': 'preview_only_not_registered', 'execution_enabled': False}

    def _manifest(self, id_, active=True):
        _text(id_, 64)
        row = self.store.db.execute('SELECT * FROM app_export_manifests WHERE id=?', (id_,)).fetchone()
        if row is None:
            raise ValueError('Unregistered export capability; disabled')
        raw = bytes(row['manifest'])
        if _sha(raw) != row['sha256']:
            raise ValueError('Manifest integrity mismatch; capability disabled')
        manifest = validate_manifest(_decode(raw))
        if active and self._disabled(id_):
            raise ValueError('Owner disabled this export capability')
        return row, manifest

    def _disabled(self, id_):
        return self.store.db.execute('SELECT 1 FROM app_export_disables WHERE manifest_id=?',
                                     (id_,)).fetchone() is not None

    def _manifest_info(self, row):
        result = {key: row[key] for key in ('id', 'at', 'path', 'sha256')}
        result.update(execution_enabled=False, live_app_verified=False,
                      external_permissions_granted=[], scope='aster_workspace_export_snapshot')
        try:
            _, manifest = self._manifest(row['id'], active=False)
            result['manifest'] = manifest
            result['status'] = ('disabled_owner_revoked' if self._disabled(row['id'])
                                else 'registered_owner_selected_export_only')
        except ValueError:
            result['status'] = 'disabled_incompatible_or_invalid'
        return result

    def register(self, path, *, expected_sha256, approved=False):
        raw = self.files.read(path)
        _approve(raw, expected_sha256, approved)
        validate_manifest(_decode(raw))
        id_ = token()
        with self.store.db:
            self.store.db.execute('INSERT INTO app_export_manifests VALUES (?,?,?,?,?)',
                                  (id_, time.time(), path, _sha(raw), raw))
            self.store.event('app_export.registered', {'id': id_, 'sha256': _sha(raw),
                                                       'external_permissions_granted': []})
        return self._manifest_info(self._manifest(id_)[0])

    def list(self):
        """Newest 100 manifests, never other apps' projects or research records."""
        return [self._manifest_info(row) for row in self.store.db.execute(
            'SELECT * FROM app_export_manifests ORDER BY rowid DESC LIMIT 100').fetchall()]

    def _export_file(self, manifest_id, project_id, path):
        _, manifest = self._manifest(manifest_id)
        # Validate scope before opening even an Aster workspace export.
        _text(project_id, 128)
        if project_id not in {p['id'] for p in manifest['projects']}:
            raise ValueError('Project is not in the approved manifest')
        raw = self.files.read(path)
        data = validate_export(_decode(raw), manifest, project_id)
        return raw, data

    def preview_export(self, manifest_id, project_id, path):
        raw, data = self._export_file(manifest_id, project_id, path)
        return {'manifest_id': manifest_id, 'app_id': data['app_id'], 'project_id': project_id,
                'path': path, 'sha256': _sha(raw), 'bytes': len(raw),
                'record_count': len(data['records']), 'notice': NOTICE,
                'status': 'preview_only_not_selected'}

    def select(self, manifest_id, project_id, path, *, expected_sha256, approved=False):
        raw, data = self._export_file(manifest_id, project_id, path)
        _approve(raw, expected_sha256, approved)
        id_ = token()
        with self.store.db:
            self.store.db.execute('INSERT INTO app_export_snapshots VALUES (?,?,?,?,?,?,?)',
                                  (id_, time.time(), manifest_id, project_id, path, _sha(raw), raw))
            self.store.db.execute('INSERT INTO app_export_selections(at,selection_id) VALUES (?,?)',
                                  (time.time(), id_))
            self.store.event('app_export.selected', {'selection_id': id_, 'manifest_id': manifest_id,
                             'app_id': data['app_id'], 'project_id': project_id, 'sha256': _sha(raw)})
        return self.selected()

    def _selection_row(self, selection_id):
        if selection_id is None:
            selected = self.store.db.execute('SELECT selection_id FROM app_export_selections '
                                             'ORDER BY seq DESC LIMIT 1').fetchone()
            selection_id = selected['selection_id'] if selected else None
        if selection_id is None:
            raise ValueError('No owner-selected export; capability disabled')
        _text(selection_id, 64)
        row = self.store.db.execute('SELECT * FROM app_export_snapshots WHERE id=?',
                                    (selection_id,)).fetchone()
        if row is None:
            raise ValueError('Unknown export selection')
        return row

    def _selection(self, selection_id):
        row = self._selection_row(selection_id)
        _, manifest = self._manifest(row['manifest_id'])
        raw = bytes(row['export'])
        if _sha(raw) != row['sha256']:
            raise ValueError('Snapshot integrity mismatch; capability disabled')
        return row, manifest, validate_export(_decode(raw), manifest, row['project_id'])

    def _selection_info(self, row):
        result = {key: row[key] for key in ('at', 'manifest_id', 'project_id', 'path', 'sha256')}
        result.update(selection_id=row['id'], execution_enabled=False,
                      provenance='owner_declared_not_authenticated', notice=NOTICE)
        try:
            _, manifest, data = self._selection(row['id'])
            result.update(app_id=data['app_id'], capabilities=manifest['capabilities'],
                          record_count=len(data['records']), status='selected_local_snapshot')
        except ValueError:
            result.update(capabilities=[], status='disabled_revoked_incompatible_or_invalid')
        return result

    def selected(self):
        current = self.store.db.execute('SELECT selection_id FROM app_export_selections '
                                        'ORDER BY seq DESC LIMIT 1').fetchone()
        if current is None or current['selection_id'] is None:
            return None
        return self._selection_info(self._selection_row(current['selection_id']))

    def status(self):
        selection = self.selected()
        manifests = self.list()
        count = self.store.db.execute('SELECT COUNT(*) FROM app_export_manifests').fetchone()[0]
        return {'status': selection['status'] if selection else 'disabled_no_selection',
                'selection': selection, 'manifests': manifests, 'manifest_count': count,
                'manifests_truncated': count > len(manifests), 'execution_enabled': False,
                'ai_enabled': False, 'live_app_commands': 'unavailable_no_reviewed_adapter',
                'catalog_research_access': 'unavailable_no_aster_grant'}

    def _perform(self, operation, selection_id, record_id=None):
        row, manifest, data = self._selection(selection_id)
        if operation not in manifest['capabilities']:
            raise ValueError('Operation is not in the approved capability manifest')
        records = data['records']
        if record_id is not None:
            _text(record_id, 128)
            records = [record for record in records if record['id'] == record_id]
            if not records:
                raise ValueError('Record is not in the exact selected export')
        result = self._selection_info(row)
        result['operation'] = operation
        result['records'] = [dict(record) if operation == 'research.read' else
                             {key: value for key, value in record.items() if key != 'excerpt'}
                             for record in records]
        with self.store.db:
            self.store.event('app_export.' + operation.split('.')[1],
                             {'selection_id': row['id'], 'record_count': len(records)})
        return result

    def inspect(self, selection_id=None):
        return self._perform('research.inspect', selection_id)

    def read(self, selection_id=None, record_id=None):
        return self._perform('research.read', selection_id, record_id)

    def disable(self, manifest_id, approved=False):
        if approved is not True:
            raise ValueError('Explicit owner approval is required to disable this capability')
        row, _ = self._manifest(manifest_id, active=False)
        if not self._disabled(manifest_id):
            with self.store.db:
                self.store.db.execute('INSERT INTO app_export_disables(manifest_id,at) VALUES (?,?)',
                                      (manifest_id, time.time()))
                self.store.event('app_export.disabled', {'manifest_id': manifest_id})
        return self._manifest_info(row)

    def clear_selection(self):
        """Deselect the default snapshot; history stays readable by its exact ID."""
        with self.store.db:
            self.store.db.execute('INSERT INTO app_export_selections(at,selection_id) VALUES (?,NULL)',
                                  (time.time(),))
            self.store.event('app_export.selection_cleared', {})
        return {'status': 'disabled_no_selection', 'selection': None}
