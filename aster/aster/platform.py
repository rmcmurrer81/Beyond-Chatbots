"""Owner-local state guards and advisory process locking.

File-workspace operations use their own stronger platform-specific handles.
SQLite state remains trusted-owner storage, not a hostile same-user sandbox.
"""
import os
import stat


def linklike(path):
    try:
        info = path.lstat()
    except FileNotFoundError:
        return False
    return stat.S_ISLNK(info.st_mode) or bool(getattr(info, 'st_file_attributes', 0) & 0x400)


def lock_state(fd):
    if os.name == 'nt':
        import msvcrt
        os.lseek(fd, 0, os.SEEK_SET)
        # Python documents that the locked byte range may extend beyond EOF.
        # Do not write a sentinel byte before acquiring the lock.
        msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
    elif os.name == 'posix':
        import fcntl
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    else:
        raise RuntimeError('Unsupported platform: no safe state lock available')
