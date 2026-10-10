"""Approved, bounded local UTF-8 source snapshots and exact passage retrieval.

No crawling, downloads, PDF/OCR, embeddings, model calls or Zotero access.
Filesystem reads always use Aster's existing secure platform Files adapter.
"""
import hashlib
import os
from pathlib import PurePosixPath
import re
import time

from .files import Files, MAX_BYTES, parts
from .storage import text, token

EXTENSIONS = ('.txt', '.md', '.json')
MAX_BATCH_FILES = 32
MAX_SOURCES = 128
MAX_FOLDERS = 32
MAX_CACHE_BYTES = 8 * 1024 * 1024
MAX_PASSAGE_CHARS = 4096


def _path(path, *, folder=False):
    if folder and path == '.':
        return '.'
    if os.name == 'nt':
        from .windows_files import windows_parts
        return '/'.join(windows_parts(path))
    return '/'.join(parts(path))


def _within(path, folder):
    return folder == '.' or path.startswith(folder + '/')


def _limit(value):
    if type(value) is not int or not 1 <= value <= 100:
        raise ValueError('Limit must be an integer from 1 to 100')
    return value


def _decode(data):
    try:
        body = data.decode('utf-8')
    except UnicodeDecodeError as error:
        raise ValueError('Reference files must be UTF-8 text') from error
    if any((ord(char) < 32 and char not in '\t\n\r') or 127 <= ord(char) <= 159 for char in body):
        raise ValueError('Binary/control-byte content is not a supported reference')
    return body


def _original_offset(body, folded_offset):
    """Map casefold expansion offsets back to source-character offsets."""
    total = 0
    for index, char in enumerate(body):
        total += len(char.casefold())
        if total > folded_offset:
            return index
    return len(body)


def _passages(body, query):
    # split only universal text newlines; U+2028 is a source character, not a
    # synthetic line boundary. Retain exact CR/LF source bytes after decoding.
    lines = re.findall(r'[^\r\n]*(?:\r\n|\r|\n)|[^\r\n]+$', body)
    folded = query.casefold()
    emitted = set()
    for index, line in enumerate(lines):
        position = line.casefold().find(folded)
        if position < 0:
            continue
        match_start = _original_offset(line, position)
        match_end = _original_offset(line, position + len(folded) - 1) + 1
        if len(line) > MAX_PASSAGE_CHARS:
            start = max(0, match_start - 240)
            end = min(len(line), match_end + 240)
            yield {'passage': line[start:end], 'start_line': index + 1, 'end_line': index + 1,
                   'start_column': start + 1, 'end_column': end, 'clipped': True}
            continue
        first = last = index
        length = len(line)
        for neighbor in range(index - 1, max(-1, index - 3), -1):
            if length + len(lines[neighbor]) > MAX_PASSAGE_CHARS:
                break
            first, length = neighbor, length + len(lines[neighbor])
        for neighbor in range(index + 1, min(len(lines), index + 3)):
            if length + len(lines[neighbor]) > MAX_PASSAGE_CHARS:
                break
            last, length = neighbor, length + len(lines[neighbor])
        if (first, last) not in emitted:
            emitted.add((first, last))
            yield {'passage': ''.join(lines[first:last + 1]), 'start_line': first + 1, 'end_line': last + 1,
                   'start_column': 1, 'end_column': len(lines[last]), 'clipped': False}


class ReferenceLibrary:
    """A cache scoped by explicit folder approvals and explicit file lists.

    paths are workspace-relative, not relative to the approved folder. Revoked
    scopes are excluded before cached text is searched or live files are read.
    Cache bytes are retained after revocation; reapproval does not erase them.
    """
    def __init__(self, store, files=None):
        self.store = store
        if files is not None and files.store is not store:
            raise ValueError('Reference reader must belong to this Store')
        self.files = Files(store) if files is None else files
        self._owns_files = files is None
        self.store.db.create_function('aster_casefold', 1, str.casefold, deterministic=True)
        with self.store.db:
            self.store.db.execute('''CREATE TABLE IF NOT EXISTS reference_folders (
                id TEXT PRIMARY KEY, path TEXT NOT NULL UNIQUE, approved_at REAL NOT NULL,
                revoked_at REAL, state TEXT NOT NULL CHECK(state IN ('active','revoked'))
            )''')
            self.store.db.execute('''CREATE TABLE IF NOT EXISTS reference_sources (
                id TEXT PRIMARY KEY, folder_id TEXT NOT NULL REFERENCES reference_folders(id),
                path TEXT NOT NULL, sha256 TEXT NOT NULL, indexed_at REAL NOT NULL,
                body TEXT NOT NULL, byte_size INTEGER NOT NULL,
                UNIQUE(folder_id,path)
            )''')

    def close(self):
        if self._owns_files:
            self.files.close()
            self._owns_files = False

    def status(self):
        return {
            'status': 'available', 'search': 'literal_case_insensitive_substring',
            'scope': 'explicitly_approved_workspace_folders', 'recursive_scan': False,
            'formats': list(EXTENSIONS), 'max_file_bytes': MAX_BYTES,
            'max_batch_files': MAX_BATCH_FILES, 'max_sources': MAX_SOURCES,
            'max_cache_bytes': MAX_CACHE_BYTES, 'max_passage_characters': MAX_PASSAGE_CHARS,
            'pdf': 'unconfigured', 'ocr': 'unconfigured', 'zotero': 'unconfigured',
            'semantic_search': False, 'model_learning': False, 'encrypted': False,
            'revocation': 'disables_reads_and_results_cached_bytes_retained',
        }

    def _check_folder(self, path):
        # The fabricated final component is never opened. Secure parent() walks
        # and validates every actual directory under the anchored workspace.
        probe = '__aster_scope_probe__' if path == '.' else path + '/__aster_scope_probe__'
        if os.name == 'nt':
            with self.files.parent(probe):
                pass
        else:
            fd, _ = self.files.parent(probe)
            os.close(fd)

    def approve_folder(self, relative_folder):
        folder = _path(relative_folder, folder=True)
        self._check_folder(folder)
        with self.store.db:
            row = self.store.db.execute('SELECT * FROM reference_folders WHERE path=?', (folder,)).fetchone()
            if row is not None and row['state'] == 'active':
                return dict(row)
            if row is None and self.store.db.execute('SELECT COUNT(*) FROM reference_folders').fetchone()[0] >= MAX_FOLDERS:
                raise ValueError('Reference library is limited to 32 retained folder approvals')
            folder_id, at = row['id'] if row else token(), time.time()
            self.store.db.execute('''INSERT INTO reference_folders VALUES (?,?,?,NULL,'active')
                ON CONFLICT(path) DO UPDATE SET approved_at=excluded.approved_at,revoked_at=NULL,state='active' ''',
                (folder_id, folder, at))
            self.store.event('library.approve', {'id': folder_id, 'path': folder})
        return self._folder(folder_id)

    def _folder(self, folder_id, *, active=False):
        text(folder_id, 128)
        row = self.store.db.execute('SELECT * FROM reference_folders WHERE id=?', (folder_id,)).fetchone()
        if row is None:
            raise ValueError('Unknown approved folder ID')
        if active and row['state'] != 'active':
            raise ValueError('Folder approval is revoked; no reads or results are allowed')
        return dict(row)

    def folders(self):
        return [dict(row) for row in self.store.db.execute('SELECT * FROM reference_folders ORDER BY path')]

    def revoke_folder(self, folder_id):
        with self.store.db:
            folder = self._folder(folder_id)
            if folder['state'] != 'revoked':
                self.store.db.execute("UPDATE reference_folders SET state='revoked',revoked_at=? WHERE id=?",
                                      (time.time(), folder_id))
                self.store.event('library.revoke', {'id': folder_id, 'cached_bytes_retained': True})
        return {**self._folder(folder_id), 'cached_bytes_retained': True}

    def index_files(self, folder_id, paths):
        folder = self._folder(folder_id, active=True)
        if type(paths) not in (list, tuple) or not 1 <= len(paths) <= MAX_BATCH_FILES:
            raise ValueError('Provide an explicit list of 1 to 32 workspace-relative files')
        canonical = [_path(path) for path in paths]
        if len(set(canonical)) != len(canonical):
            raise ValueError('File list contains duplicate paths')
        for path in canonical:
            if not _within(path, folder['path']):
                raise ValueError('File is outside the approved folder')
            if PurePosixPath(path).suffix.lower() not in EXTENSIONS:
                raise ValueError('Only UTF-8 .txt, .md and .json references are configured')
        # Validate the complete batch before committing any changed snapshot.
        prepared = []
        for path in canonical:
            data = self.files.read(path)
            prepared.append((path, hashlib.sha256(data).hexdigest(), _decode(data), len(data)))
        result = []
        with self.store.db:
            self._folder(folder_id, active=True)
            count, size = self.store.db.execute('SELECT COUNT(*),COALESCE(SUM(byte_size),0) FROM reference_sources').fetchone()
            for path, sha, body, byte_size in prepared:
                existing = self.store.db.execute('SELECT * FROM reference_sources WHERE folder_id=? AND path=?',
                                                  (folder_id, path)).fetchone()
                count += 0 if existing else 1
                size += byte_size - (existing['byte_size'] if existing else 0)
                if count > MAX_SOURCES or size > MAX_CACHE_BYTES:
                    raise ValueError('Reference cache would exceed its 128-file or 8 MiB limit')
                source_id, at = existing['id'] if existing else token(), time.time()
                self.store.db.execute('''INSERT INTO reference_sources VALUES (?,?,?,?,?,?,?)
                    ON CONFLICT(folder_id,path) DO UPDATE SET sha256=excluded.sha256,
                    indexed_at=excluded.indexed_at,body=excluded.body,byte_size=excluded.byte_size''',
                    (source_id, folder_id, path, sha, at, body, byte_size))
                result.append({'id': source_id, 'folder_id': folder_id, 'path': path, 'sha256': sha,
                               'indexed_at': at, 'byte_size': byte_size})
            self.store.event('library.index', {'folder_id': folder_id, 'sources': [row['id'] for row in result]})
        return result

    def _freshness(self, row):
        path = _path(row['path'])
        if not _within(path, row['folder_path']):
            raise ValueError('Stored reference path is outside its approval')
        try:
            current = hashlib.sha256(self.files.read(path)).hexdigest()
        except FileNotFoundError:
            return {'source_state': 'missing', 'stale': True, 'current_sha256': None}
        except (OSError, ValueError):
            return {'source_state': 'unavailable', 'stale': True, 'current_sha256': None}
        return {'source_state': 'fresh' if current == row['sha256'] else 'changed',
                'stale': current != row['sha256'], 'current_sha256': current}

    def _source_rows(self, folder_id=None, query=None):
        if folder_id is not None:
            self._folder(folder_id, active=True)
        sql = '''SELECT s.*,f.path AS folder_path FROM reference_sources s
                 JOIN reference_folders f ON f.id=s.folder_id WHERE f.state='active' '''
        values = []
        if folder_id is not None:
            sql += ' AND s.folder_id=?'
            values.append(folder_id)
        if query is not None:
            sql += ' AND instr(aster_casefold(s.body), ?) > 0'
            values.append(query.casefold())
        return self.store.db.execute(sql + ' ORDER BY s.path,s.id LIMIT ?', (*values, MAX_SOURCES))

    def sources(self, folder_id=None):
        return [{**{key: row[key] for key in ('id', 'folder_id', 'path', 'sha256', 'indexed_at', 'byte_size')},
                 **self._freshness(row)} for row in self._source_rows(folder_id)]

    def search(self, query, *, folder_id=None, limit=20):
        text(query, 512); _limit(limit)
        if any(char in query for char in '\n\r'):
            raise ValueError('Reference query must be a single line')
        result = []
        for row in self._source_rows(folder_id, query):
            freshness = self._freshness(row)
            for passage in _passages(row['body'], query):
                citation = {key: passage[key] for key in ('start_line', 'end_line', 'start_column', 'end_column')}
                citation.update(path=row['path'], sha256=row['sha256'])
                result.append({'source_id': row['id'], 'folder_id': row['folder_id'],
                               'path': row['path'], 'sha256': row['sha256'], 'indexed_at': row['indexed_at'],
                               **passage, **freshness, 'citation': citation, 'snapshot': True})
                if len(result) == limit:
                    return result
        return result
