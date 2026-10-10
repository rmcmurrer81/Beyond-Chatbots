"""Fail-closed Windows adapter for Files' reversible journal.

Supported storage is an owner-controlled directory on a local fixed NTFS volume.
UNC/device paths, reparse points (including cloud placeholders and junctions),
case-sensitive directories and DOS short-name workspace aliases are rejected.
Workspace paths use ASCII names and are journaled in lowercase. Contents remain
arbitrary bounded bytes. State-directory names may be Unicode.

Every operation opens each ancestor with OPEN_REPARSE_POINT/BACKUP_SEMANTICS and
retains GENERIC_READ handles without FILE_SHARE_DELETE. Empty directories also
exclude FILE_SHARE_WRITE: a metadata-only handle would not enforce sharing.
Before a native atomic rename, only the immediate parent gains write sharing,
while its CREATE_NEW temporary file is still held without delete sharing. That
file pins the directory nonempty; NTFS refuses setting a reparse point on a
nonempty directory. Deletion and temporary-file cleanup use verified handles.
There is no path-only or in-place-write fallback. This is not a sandbox against
hostile same-user processes, administrators, kernel drivers or drive remapping.

FlushFileBuffers flushes file bytes before rename. As with the journal's recovery
protocol, process-crash recovery is supported; power-loss atomic durability of
Windows directory metadata is not promised. Failed operations remain prepared.

Native contracts:
https://learn.microsoft.com/windows/win32/api/fileapi/nf-fileapi-createfilew
https://learn.microsoft.com/windows/win32/api/fileapi/nf-fileapi-setfileinformationbyhandle
https://learn.microsoft.com/windows-hardware/drivers/ddi/ntifs/nf-ntifs-ntsetinformationfile
https://learn.microsoft.com/windows-hardware/drivers/ddi/ntifs/ns-ntifs-_file_rename_information
https://learn.microsoft.com/windows/win32/fileio/reparse-points
"""
from contextlib import contextmanager
import ctypes
import ntpath
import os

from .files import Files, MAX_BYTES, parts
from .storage import token


_GENERIC_READ = 0x80000000
_GENERIC_WRITE = 0x40000000
_DELETE = 0x00010000
_SHARE_READ = 1
_SHARE_WRITE = 2
_OPEN_EXISTING = 3
_CREATE_NEW = 1
_DIRECTORY = 0x10
_DEVICE = 0x40
_REPARSE = 0x400
_OPEN_REPARSE_POINT = 0x00200000
_BACKUP_SEMANTICS = 0x02000000
_WRITE_THROUGH = 0x80000000
_FILE_TYPE_DISK = 1
_FILE_RENAME_INFORMATION = 10  # Native FILE_INFORMATION_CLASS, not Win32 class 3.
_STATUS_PENDING = 0x103
_FILE_DISPOSITION_INFO = 4
_FILE_CASE_SENSITIVE_INFO = 23
_INVALID_HANDLE = ctypes.c_void_p(-1).value
_DWORD = ctypes.c_uint32
_HANDLE = ctypes.c_void_p
_BOOL = ctypes.c_int32
_NTSTATUS = ctypes.c_int32


class _FileTime(ctypes.Structure):
    _fields_ = [('low', _DWORD), ('high', _DWORD)]


class _FileInformation(ctypes.Structure):
    _fields_ = [
        ('attributes', _DWORD), ('creation', _FileTime),
        ('access', _FileTime), ('write', _FileTime), ('volume', _DWORD),
        ('size_high', _DWORD), ('size_low', _DWORD), ('links', _DWORD),
        ('index_high', _DWORD), ('index_low', _DWORD),
    ]

    @property
    def size(self):
        return (self.size_high << 32) | self.size_low

    @property
    def identity(self):
        return self.volume, self.index_high, self.index_low


class _IoStatusUnion(ctypes.Union):
    _fields_ = [('status', _NTSTATUS), ('pointer', ctypes.c_void_p)]


class _IoStatusBlock(ctypes.Structure):
    _anonymous_ = ('result',)
    _fields_ = [('result', _IoStatusUnion), ('information', ctypes.c_size_t)]


class _RenameInformation(ctypes.Structure):
    # The first union is DWORD-sized in current Windows headers. The native
    # FileRenameInformation reads its BOOLEAN member; remaining bytes are zero.
    _fields_ = [('replace', _DWORD), ('root', _HANDLE),
                ('length', _DWORD), ('name', ctypes.c_wchar * 1)]


def _component(name, *, ascii_only=False):
    if (not name or name in {'.', '..'} or name[-1] in ' .'
            or any(ord(c) < 32 or ord(c) == 127 or c in '<>:"/\\|?*' for c in name)):
        raise ValueError('Invalid Windows filename component')
    try:
        size = len(name.encode('utf-16-le')) // 2
    except UnicodeEncodeError as error:
        raise ValueError('Invalid Unicode filename') from error
    if size > 255:
        raise ValueError('Windows filename component exceeds 255 UTF-16 units')
    if ascii_only and not name.isascii():
        raise ValueError('Windows workspace paths currently require ASCII filenames')
    stem = name.split('.', 1)[0].rstrip(' ').upper()
    devices = {'CON', 'PRN', 'AUX', 'NUL', 'CONIN$', 'CONOUT$', 'CLOCK$'}
    devices.update(prefix + n for prefix in ('COM', 'LPT') for n in '0123456789\u00b9\u00b2\u00b3')
    if stem in devices:
        raise ValueError('Reserved Windows device name')


def windows_parts(path):
    """Validate a portable workspace path and return its canonical journal key."""
    names = parts(path)
    for name in names:
        _component(name, ascii_only=True)
        # A native normalized-path check also rejects aliases without a tilde.
        if '~' in name:
            raise ValueError('DOS short-name aliases are not supported')
    return tuple(name.lower() for name in names)


class _Win32:
    """Small explicitly typed binding; never instantiated outside Windows."""
    def __init__(self):
        if os.name != 'nt':
            raise RuntimeError('Windows file adapter requires native Windows')
        self.dll = ctypes.WinDLL('kernel32', use_last_error=True)
        signatures = {
            'CreateFileW': (_HANDLE, [ctypes.c_wchar_p, _DWORD, _DWORD, ctypes.c_void_p,
                                     _DWORD, _DWORD, _HANDLE]),
            'CloseHandle': (_BOOL, [_HANDLE]),
            'WaitForSingleObject': (_DWORD, [_HANDLE, _DWORD]),
            'GetFileType': (_DWORD, [_HANDLE]),
            'GetFileInformationByHandle': (_BOOL, [_HANDLE, ctypes.POINTER(_FileInformation)]),
            'GetFileInformationByHandleEx': (_BOOL, [_HANDLE, ctypes.c_int, ctypes.c_void_p, _DWORD]),
            'GetFinalPathNameByHandleW': (_DWORD, [_HANDLE, ctypes.c_wchar_p, _DWORD, _DWORD]),
            'GetVolumeInformationByHandleW': (_BOOL, [_HANDLE, ctypes.c_wchar_p, _DWORD,
                ctypes.POINTER(_DWORD), ctypes.POINTER(_DWORD), ctypes.POINTER(_DWORD),
                ctypes.c_wchar_p, _DWORD]),
            'GetDriveTypeW': (_DWORD, [ctypes.c_wchar_p]),
            'CreateDirectoryW': (_BOOL, [ctypes.c_wchar_p, ctypes.c_void_p]),
            'ReadFile': (_BOOL, [_HANDLE, ctypes.c_void_p, _DWORD, ctypes.POINTER(_DWORD), ctypes.c_void_p]),
            'WriteFile': (_BOOL, [_HANDLE, ctypes.c_void_p, _DWORD, ctypes.POINTER(_DWORD), ctypes.c_void_p]),
            'FlushFileBuffers': (_BOOL, [_HANDLE]),
            'SetFileInformationByHandle': (_BOOL, [_HANDLE, ctypes.c_int, ctypes.c_void_p, _DWORD]),
        }
        for name, (result, arguments) in signatures.items():
            function = getattr(self.dll, name)
            function.restype = result
            function.argtypes = arguments
        # Win32's SetFileInformationByHandle wrapper mishandles a non-NULL
        # RootDirectory on supported Windows builds. Use the documented native
        # rename contract directly, preserving the held-directory anchor.
        # Missing native exports fail closed; there is no path-based retry.
        self.ntdll = ctypes.WinDLL('ntdll', use_last_error=True)
        self.ntdll.NtSetInformationFile.restype = _NTSTATUS
        self.ntdll.NtSetInformationFile.argtypes = [
            _HANDLE, ctypes.POINTER(_IoStatusBlock), ctypes.c_void_p, _DWORD, ctypes.c_int,
        ]
        self.ntdll.RtlNtStatusToDosError.restype = _DWORD
        self.ntdll.RtlNtStatusToDosError.argtypes = [_NTSTATUS]

    @staticmethod
    def check(result):
        if not result:
            raise ctypes.WinError(ctypes.get_last_error())
        return result

    def open(self, path, access=_GENERIC_READ, *, share=_SHARE_READ,
             disposition=_OPEN_EXISTING, write_through=False):
        flags = _OPEN_REPARSE_POINT | _BACKUP_SEMANTICS
        if write_through:
            flags |= _WRITE_THROUGH
        handle = self.dll.CreateFileW(path, access, share, None, disposition, flags, None)
        if handle == _INVALID_HANDLE:
            raise ctypes.WinError(ctypes.get_last_error())
        return handle

    def close(self, handle):
        self.check(self.dll.CloseHandle(handle))

    def info(self, handle, *, directory=False):
        info = _FileInformation()
        self.check(self.dll.GetFileInformationByHandle(handle, ctypes.byref(info)))
        if self.dll.GetFileType(handle) != _FILE_TYPE_DISK or info.attributes & (_REPARSE | _DEVICE):
            raise ValueError('Reparse points and special files are forbidden')
        if bool(info.attributes & _DIRECTORY) != directory:
            raise ValueError('Expected a real directory' if directory else 'Expected a regular file')
        if directory:
            flags = _DWORD()
            # Do not silently accept an OS/filesystem unable to check this.
            self.check(self.dll.GetFileInformationByHandleEx(handle, _FILE_CASE_SENSITIVE_INFO,
                                                             ctypes.byref(flags), ctypes.sizeof(flags)))
            if flags.value & 1:
                raise ValueError('Case-sensitive Windows directories are not supported')
        elif info.links != 1 or info.size > MAX_BYTES:
            raise ValueError('Only bounded regular single-link files are allowed')
        return info

    def normalized_path(self, handle):
        buffer = ctypes.create_unicode_buffer(32768)
        size = self.check(self.dll.GetFinalPathNameByHandleW(handle, buffer, len(buffer), 0))
        if size >= len(buffer):
            raise ValueError('Native path is too long')
        result = buffer.value
        if not result.startswith('\\\\?\\') or result.startswith('\\\\?\\UNC\\'):
            raise ValueError('Only local drive paths are supported')
        return result

    def directory(self, path, *, share=_SHARE_READ):
        handle = self.open(path, share=share)
        try:
            self.info(handle, directory=True)
            return handle, self.normalized_path(handle)
        except BaseException:
            self.close(handle)
            raise

    def ntfs(self, handle):
        filesystem = ctypes.create_unicode_buffer(32)
        self.check(self.dll.GetVolumeInformationByHandleW(handle, None, 0, None, None,
                                                         None, filesystem, len(filesystem)))
        if filesystem.value != 'NTFS':
            raise ValueError('Windows file tools require a local fixed NTFS volume')

    def mkdir(self, path):
        if not self.dll.CreateDirectoryW(path, None):
            error = ctypes.get_last_error()
            if error != 183:  # ERROR_ALREADY_EXISTS; caller still opens and validates.
                raise ctypes.WinError(error)

    def read(self, handle):
        result = bytearray()
        while len(result) <= MAX_BYTES:
            size = min(65536, MAX_BYTES + 1 - len(result))
            buffer = ctypes.create_string_buffer(size)
            count = _DWORD()
            self.check(self.dll.ReadFile(handle, buffer, size, ctypes.byref(count), None))
            if not count.value:
                break
            result.extend(buffer.raw[:count.value])
        if len(result) > MAX_BYTES:
            raise ValueError('File too large')
        self.info(handle)
        return bytes(result)

    def write(self, handle, data):
        position = 0
        while position < len(data):
            chunk = data[position:position + 65536]
            buffer = ctypes.create_string_buffer(chunk)
            count = _DWORD()
            self.check(self.dll.WriteFile(handle, buffer, len(chunk), ctypes.byref(count), None))
            if not count.value:
                raise OSError('Native write made no progress')
            position += count.value
        self.check(self.dll.FlushFileBuffers(handle))
        self.info(handle)

    def delete(self, handle):
        delete = ctypes.c_ubyte(1)  # FILE_DISPOSITION_INFO contains BOOLEAN, not BOOL.
        self.check(self.dll.SetFileInformationByHandle(handle, _FILE_DISPOSITION_INFO,
                                                      ctypes.byref(delete), ctypes.sizeof(delete)))

    def rename(self, handle, parent_handle, name):
        encoded = name.encode('utf-16-le')
        offset = _RenameInformation.name.offset
        # The native contract asks for sizeof(FILE_RENAME_INFORMATION) plus
        # the filename byte count. Include a zero terminator as well; length
        # below still excludes it. This works for both 32- and 64-bit padding.
        buffer = ctypes.create_string_buffer(ctypes.sizeof(_RenameInformation) + len(encoded) + 2)
        info = _RenameInformation.from_buffer(buffer)
        info.replace = 1
        info.root = parent_handle
        info.length = len(encoded)
        ctypes.memmove(ctypes.addressof(buffer) + offset, encoded, len(encoded))
        status_block = _IoStatusBlock()
        status = self.ntdll.NtSetInformationFile(
            handle, ctypes.byref(status_block), buffer, len(buffer), _FILE_RENAME_INFORMATION)
        if status == _STATUS_PENDING:
            # CreateFile handles here are synchronous, but retain the native
            # buffers and all confinement handles if a driver returns pending.
            waited = self.dll.WaitForSingleObject(handle, 0xFFFFFFFF)
            if waited != 0:  # WAIT_OBJECT_0
                if waited == 0xFFFFFFFF:  # WAIT_FAILED
                    raise ctypes.WinError(ctypes.get_last_error())
                raise OSError('Unexpected wait result for native file rename')
            status = status_block.status
        if status < 0:
            # NT functions return NTSTATUS directly; GetLastError is unrelated.
            raise ctypes.WinError(self.ntdll.RtlNtStatusToDosError(status))


class _Parent:
    """Own all ancestor handles until an operation, including cleanup, ends."""
    def __init__(self, api):
        self.api = api
        self.handles = []
        self.path = None
        self.name = None

    @property
    def handle(self):
        return self.handles[-1]

    @property
    def target(self):
        return ntpath.join(self.path, self.name)

    def descend(self, name, *, create=False, workspace_name=False):
        candidate = ntpath.join(self.path, name)
        if create:
            self.api.mkdir(candidate)
        handle, normalized = self.api.directory(candidate)
        self.handles.append(handle)
        if workspace_name and (not ntpath.basename(normalized).isascii()
                               or ntpath.basename(normalized).lower() != name):
            raise ValueError('DOS short-name workspace aliases are not supported')
        self.path = normalized

    def allow_rename(self, pinned_file):
        # The pinned CREATE_NEW file has DELETE access but no FILE_SHARE_DELETE,
        # so no other handle can remove/rename it. It keeps this directory
        # nonempty while native rename temporarily requires parent write sharing.
        self.api.info(pinned_file)
        before = self.api.info(self.handle, directory=True).identity
        handle, normalized = self.api.directory(self.path, share=_SHARE_READ | _SHARE_WRITE)
        try:
            if self.api.info(handle, directory=True).identity != before:
                raise ValueError('Parent directory identity changed')
        except BaseException:
            self.api.close(handle)
            raise
        previous = self.handles[-1]
        self.handles[-1] = handle
        self.path = normalized
        self.api.close(previous)

    def close(self):
        while self.handles:
            self.api.close(self.handles.pop())


class WindowsFiles(Files):
    def __init__(self, store):
        self.store = store
        self.root = store.root / 'workspace'
        self._api = _Win32()
        self._closed = False
        self._workspace_id = None
        with self._workspace(create=True) as parent:
            self._workspace_id = self._api.info(parent.handle, directory=True).identity

    def close(self):
        # Handles are operation-scoped, including root ancestors. No native
        # handles remain idle and repeated close is harmless.
        self._closed = True

    @contextmanager
    def _workspace(self, *, create=False):
        if self._closed:
            raise ValueError('File tools are closed')
        state = str(self.store.root)
        drive, tail = ntpath.splitdrive(state)
        if (len(drive) != 2 or not drive[0].isascii() or not drive[0].isalpha()
                or drive[1] != ':' or not tail.startswith('\\') or state.startswith('\\\\')):
            raise ValueError('Windows state must be an absolute local drive path')
        names = tail[1:].split('\\') if tail[1:] else []
        for name in names:
            _component(name)
        if len(state.encode('utf-16-le')) // 2 > 30000:
            raise ValueError('Windows state path is too long')
        if self._api.dll.GetDriveTypeW(drive + '\\') != 3:  # DRIVE_FIXED
            raise ValueError('Windows file tools require a local fixed NTFS volume')
        parent = _Parent(self._api)
        try:
            handle, parent.path = self._api.directory('\\\\?\\' + drive + '\\')
            parent.handles.append(handle)
            self._api.ntfs(handle)
            for name in names:
                parent.descend(name)
            parent.descend('workspace', create=create, workspace_name=True)
            actual = self._api.info(parent.handle, directory=True).identity
            if self._workspace_id is not None and actual != self._workspace_id:
                raise ValueError('Workspace directory was replaced; reopen state explicitly')
            yield parent
        finally:
            parent.close()

    @contextmanager
    def parent(self, path, create=False):
        names = windows_parts(path)
        with self._workspace() as parent:
            for name in names[:-1]:
                parent.descend(name, create=create, workspace_name=True)
            parent.name = names[-1]
            yield parent

    def _file(self, parent, *, delete=False):
        access = _GENERIC_READ | (_DELETE if delete else 0)
        handle = self._api.open(parent.target, access)
        try:
            self._api.info(handle)
            actual_name = ntpath.basename(self._api.normalized_path(handle))
            if not actual_name.isascii() or actual_name.lower() != parent.name:
                raise ValueError('DOS short-name workspace aliases are not supported')
            return handle
        except BaseException:
            self._api.close(handle)
            raise

    def read(self, path):
        with self.parent(path) as parent:
            handle = self._file(parent)
            try:
                return self._api.read(handle)
            finally:
                self._api.close(handle)

    def change(self, path, data, kind='write', *, job_id=None):
        # Windows resolves ASCII names case-insensitively. Use one journal key
        # so an interrupted edit cannot be bypassed with another spelling.
        canonical = '/'.join(windows_parts(path))
        # COLLATE NOCASE also covers ASCII journal rows imported from a POSIX
        # state, whose historical spelling may not already be lowercase.
        if self.store.db.execute(
                "SELECT 1 FROM changes WHERE path=? COLLATE NOCASE AND status='prepared'",
                (canonical,)).fetchone():
            raise ValueError('Interrupted change requires recover before editing')
        return super().change(canonical, data, kind, job_id=job_id)

    def _replace(self, path, data):
        if data is not None and (type(data) is not bytes or len(data) > MAX_BYTES):
            raise ValueError('Content must be bytes within 256 KiB')
        with self.parent(path, create=data is not None) as parent:
            target = None
            try:
                target = self._file(parent, delete=data is None)
            except FileNotFoundError:
                if data is None:
                    raise
            if data is None:
                try:
                    self._api.delete(target)
                finally:
                    self._api.close(target)
                return
            out = None
            committed = False
            try:
                temporary = ntpath.join(parent.path, '.aster-' + token())
                out = self._api.open(temporary, _GENERIC_WRITE | _DELETE,
                                     disposition=_CREATE_NEW, write_through=True)
                self._api.info(out)
                self._api.write(out, data)
                parent.allow_rename(out)
                # Windows cannot replace a target while our old read handle
                # denies delete-sharing. Native rename replaces the directory
                # entry; it never opens/follows the destination's reparse data.
                if target is not None:
                    self._api.close(target)
                    target = None
                self._api.rename(out, parent.handle, parent.name)
                committed = True
            finally:
                if target is not None:
                    self._api.close(target)
                if out is not None:
                    try:
                        if not committed:
                            self._api.delete(out)
                    finally:
                        self._api.close(out)
