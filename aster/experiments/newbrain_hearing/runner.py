"""Isolated component runner, deliberately not a blind production consumer."""
import importlib.util
import json
from pathlib import Path
import sys
import unittest


def main():
    role, cases, result_path = (Path(p).resolve() for p in sys.argv[1:])
    sys.path.insert(0, str(role))
    spec = importlib.util.spec_from_file_location('aster_hearing_component_cases', cases)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    result = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromModule(module))
    result_path.write_text(json.dumps({'tests_run':result.testsRun,'failures':len(result.failures),
        'errors':len(result.errors),'skipped':len(result.skipped),'success':result.wasSuccessful(),
        'scope':'Non-blind component compatibility with fresh synthetic data, not runtime qualification.'},indent=2)+'\n')
    return 0 if result.wasSuccessful() else 1


if __name__ == '__main__':
    raise SystemExit(main())
