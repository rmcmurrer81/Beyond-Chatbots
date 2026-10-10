"""Fixed isolated startup entry point for this checkout; no arbitrary commands."""
import sys

# Reject a non-isolated real invocation before importing from any path that could
# come from a caller's working directory, PYTHONPATH, or user site packages.
if __name__ == '__main__' and (not sys.flags.isolated or not sys.flags.no_site):
    raise SystemExit('Use the reviewed startup command with Python -I -S -B')

import os
from pathlib import Path
import stat


def _real_path(path, *, directory):
    if not path.is_absolute() or '..' in path.parts:
        raise ValueError('Startup paths must be absolute and contain no traversal')
    if os.name == 'nt' and (len(path.drive) != 2 or path.drive[1] != ':'):
        raise ValueError('Startup requires local Windows paths')
    for candidate in [path, *path.parents]:
        info = candidate.lstat()
        if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 0x400:
            raise ValueError('Startup paths cannot contain symlinks or reparse points')
    info = path.stat()
    if not (stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode)):
        raise ValueError('Startup path has the wrong file type')
    return path


def main(argv=None):
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) != 2 or args[0] != '--state' or not isinstance(args[1], str):
        raise ValueError('Expected only --state followed by an absolute existing state directory')
    if len(args[1]) > 4096 or any(ord(c) < 32 for c in args[1]):
        raise ValueError('Invalid bounded startup state path')
    root = _real_path(Path(__file__).absolute().parent, directory=True)
    _real_path(root / 'launch_aster.py', directory=False)
    _real_path(root / 'aster', directory=True)
    _real_path(root / 'aster' / '__init__.py', directory=False)
    _real_path(root / 'aster' / 'lifecycle.py', directory=False)
    state = _real_path(Path(args[1]), directory=True)
    # -I -S leaves only Python's standard-library paths. Insert the verified
    # checkout explicitly; the Windows logon working directory is irrelevant.
    sys.path.insert(0, str(root))
    from aster.lifecycle import startup_launch
    return startup_launch(state)


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (ValueError, OSError, RuntimeError) as exc:
        print('Aster startup could not open: ' + str(exc), file=sys.stderr)
        raise SystemExit(2)
