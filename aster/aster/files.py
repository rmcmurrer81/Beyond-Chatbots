"""Bounded managed files, no shell execution, reversible journaled edits.

POSIX directory descriptors and O_NOFOLLOW prevent traversal/symlink swaps.
The state directory remains a trusted owner-only boundary, not a hostile-user sandbox.
"""
import hashlib
import os
from pathlib import PurePosixPath
import stat
import time
from .storage import token

MAX_BYTES = 262144


def parts(path):
    if type(path) is not str or not path or len(path) > 512 or '\\' in path or '\x00' in path:
        raise ValueError('Invalid workspace-relative path')
    p = PurePosixPath(path)
    if p.is_absolute() or any(s in {'', '.', '..'} for s in path.split('/')) or p.parts[0].startswith('.'):
        raise ValueError('Use a relative path without dot components')
    return p.parts


class Files:
    def __new__(cls, store):
        if cls is Files and os.name == 'nt':
            from .windows_files import WindowsFiles
            return object.__new__(WindowsFiles)
        return object.__new__(cls)

    def __init__(self, store):
        if not hasattr(os, 'O_NOFOLLOW') or os.name != 'posix':
            raise RuntimeError('Secure file tools currently require POSIX; no unsafe fallback')
        self.store = store
        self.root = store.root / 'workspace'
        self.root.mkdir(exist_ok=True)
        self.fd = os.open(self.root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)

    def close(self):
        os.close(self.fd)

    def parent(self, path, create=False):
        names = parts(path)
        fd = os.dup(self.fd)
        try:
            for name in names[:-1]:
                if create:
                    try: os.mkdir(name, dir_fd=fd)
                    except FileExistsError: pass
                nextfd = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
                os.close(fd); fd = nextfd
            return fd, names[-1]
        except BaseException:
            os.close(fd); raise

    def read(self, path):
        fd, name = self.parent(path)
        try:
            handle = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
            try:
                info = os.fstat(handle)
                if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_BYTES or info.st_nlink != 1:
                    raise ValueError('Only bounded regular single-link files are allowed')
                data = os.read(handle, MAX_BYTES + 1)
                if len(data) > MAX_BYTES: raise ValueError('File too large')
                return data
            finally: os.close(handle)
        finally: os.close(fd)

    def snapshot(self, path):
        try: return self.read(path)
        except FileNotFoundError: return None

    def _replace(self, path, data):
        fd, name = self.parent(path, create=data is not None)
        temp = '.aster-' + token()
        try:
            # Reject unexpected special targets, including dangling symlinks.
            try:
                st = os.stat(name, dir_fd=fd, follow_symlinks=False)
                if not stat.S_ISREG(st.st_mode) or st.st_nlink != 1: raise ValueError('Unsafe target')
            except FileNotFoundError: pass
            if data is None:
                os.unlink(name, dir_fd=fd)
            else:
                out = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=fd)
                try:
                    with os.fdopen(out, 'wb') as stream:
                        stream.write(data); stream.flush(); os.fsync(stream.fileno())
                    os.replace(temp, name, src_dir_fd=fd, dst_dir_fd=fd)
                finally:
                    try: os.unlink(temp, dir_fd=fd)
                    except FileNotFoundError: pass
            os.fsync(fd)
        finally: os.close(fd)

    def change(self, path, data, kind='write', *, job_id=None):
        # Prepared rows must be durable before touching external file bytes.
        if self.store.db.in_transaction:
            raise RuntimeError('Effect operation requires transaction ownership')
        parts(path)
        if data is not None and (type(data) is not bytes or len(data) > MAX_BYTES):
            raise ValueError('Content must be bytes within 256 KiB')
        before = self.snapshot(path)
        if data is None and before is None: raise FileNotFoundError(path)
        # No new edit while an interrupted operation on this path needs reconciliation.
        if self.store.db.execute("SELECT 1 FROM changes WHERE path=? AND status='prepared'", (path,)).fetchone():
            raise ValueError('Interrupted change requires recover before editing')
        id_ = token()
        with self.store.effect_transaction():
            self.store.db.execute('INSERT INTO changes VALUES (?,?,?,?,?,?,?)',
                (id_, time.time(), path, kind, before, data, 'prepared'))
            if job_id is not None:
                self.store.link_job_effect(job_id, change_id=id_)
            self.store.event('file.prepared', {'id': id_, 'path': path, 'kind': kind})
        try:
            self._replace(path, data)
        except BaseException:
            # Preserve prepared state: recovery checks actual bytes, never assumes rollback.
            raise
        with self.store.db:
            self.store.db.execute("UPDATE changes SET status='applied' WHERE id=?", (id_,))
            self.store.event('file.applied', {'id': id_, 'sha256': hashlib.sha256(data).hexdigest() if data is not None else None})
        return id_

    def undo(self, id_):
        row = self.store.db.execute('SELECT * FROM changes WHERE id=?', (id_,)).fetchone()
        if not row or row['status'] != 'applied': raise ValueError('No applied change with that ID')
        if self.snapshot(row['path']) != row['after']:
            raise ValueError('File changed since this operation; refusing to overwrite')
        undo_id = self.change(row['path'], row['before'], 'undo:' + id_)
        with self.store.db:
            self.store.db.execute("UPDATE changes SET status='undone' WHERE id=?", (id_,))
        return undo_id

    def recover(self):
        result = []
        for row in self.store.db.execute("SELECT * FROM changes WHERE status='prepared' ORDER BY rowid").fetchall():
            try:
                actual = self.snapshot(row['path'])
            except (OSError, ValueError) as error:
                # An unavailable or unsafe snapshot cannot establish an outcome.
                # Keep its prepared row and bytes intact for an explicit retry.
                # Catch only the read: database/audit failures must still escape.
                result.append({'id': row['id'], 'status': 'unresolved',
                               'reason': 'snapshot_unavailable',
                               'error_type': type(error).__name__})
                continue
            # Equal before/after bytes cannot establish whether replacement happened.
            state = ('indeterminate' if row['before'] == row['after'] and actual == row['after'] else
                     'applied' if actual == row['after'] else 'not_applied' if actual == row['before'] else 'conflict')
            with self.store.db:
                self.store.db.execute('UPDATE changes SET status=? WHERE id=?', (state, row['id']))
                self.store.event('file.recovered', {'id': row['id'], 'status': state})
            result.append({'id': row['id'], 'status': state})
        return result
