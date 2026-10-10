"""Source admission and unchanged runtime guards for opt-in hearing checks."""
import contextlib
import io
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from types import SimpleNamespace

from experiments.newbrain_hearing.source import VENDOR, verify, stage
from experiments.newbrain_hearing.pipeline import exact_runtime, invoke


class HearingSourceTests(unittest.TestCase):
    def test_twenty_exact_modules_and_six_role_maps(self):
        value=verify()
        self.assertEqual(len(value['roles']),6)
        self.assertEqual(sum(f['path'].endswith('.py') for f in value['files']),20)

    def test_all_six_role_assemblies_preserve_bytes_and_separation(self):
        with tempfile.TemporaryDirectory() as directory:
            for role in verify()['roles']:
                target=stage(Path(directory)/(role['experiment']+role['role']),role['experiment'],role['role'])
                self.assertEqual({p.name for p in target.iterdir()},{f['filename'] for f in role['files']})
                for f in role['files']:
                    self.assertEqual((target/f['filename']).read_bytes(),(VENDOR/f['repository_path']).read_bytes())

    def test_altered_module_is_refused_before_import(self):
        with tempfile.TemporaryDirectory() as directory:
            target=Path(directory)/'source';shutil.copytree(VENDOR,target)
            p=target/'research/hearing-dependencies220/source/cue_readout.py'
            p.write_bytes(p.read_bytes()+b'\n# tamper\n')
            with self.assertRaisesRegex(ValueError,'bytes changed'):verify(target)

    def test_extra_file_is_refused(self):
        with tempfile.TemporaryDirectory() as directory:
            target=Path(directory)/'source';shutil.copytree(VENDOR,target)
            (target/'extra.py').write_text('')
            with self.assertRaisesRegex(ValueError,'additional'):verify(target)

    def test_tampered_manifest_is_refused(self):
        with tempfile.TemporaryDirectory() as directory:
            target=Path(directory)/'source';shutil.copytree(VENDOR,target)
            (target/'manifest.json').write_text('{}')
            with self.assertRaisesRegex(ValueError,'manifest changed'):verify(target)

    def test_unknown_role_is_refused(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(ValueError,'Unknown'):stage(Path(directory)/'bad','210','unknown')

    def runtime_probe(self, flags):
        with tempfile.TemporaryDirectory() as directory:
            source=stage(Path(directory)/'source','210','staged_producer')
            output=Path(directory)/'output';output.mkdir()
            command='import sys;sys.path.insert(0,sys.argv[1]);from run_io import RunIO;RunIO(sys.argv[2],sys.argv[3])'
            result=subprocess.run([sys.executable,*flags,'-c',command,str(source),str(output),str(Path(directory)/'STOP')],capture_output=True,timeout=10)
            self.assertEqual(list(output.iterdir()),[])
            return result

    def test_failed_entry_retains_raw_diagnostics_only_in_temporary_work(self):
        with tempfile.TemporaryDirectory() as directory:
            work=Path(directory);records=[]
            failed=SimpleNamespace(returncode=1,stdout=b'fixture output',stderr=b'PRIVATE-ENTRY-DIAGNOSTIC')
            with patch('experiments.newbrain_hearing.pipeline.subprocess.run',return_value=failed):
                with self.assertRaises(RuntimeError) as caught:
                    invoke(work,'arm.py',{'arm':'LEARNED','output-dir':work/'out'},work,records)
            self.assertNotIn('PRIVATE-ENTRY-DIAGNOSTIC',str(caught.exception))
            self.assertNotIn('PRIVATE-ENTRY-DIAGNOSTIC',json.dumps(records))
            self.assertEqual((work/'stage-1.stderr').read_bytes(),b'PRIVATE-ENTRY-DIAGNOSTIC')
            self.assertEqual(records[0]['exit_code'],1)

    def test_failed_pipeline_report_is_terminal_and_unsuccessful(self):
        from experiments.newbrain_hearing import checks
        def failed_pipeline(work, report):
            report.update(executed=True,status='RUNNING')
            raise RuntimeError('Original fixture entry failed')
        with tempfile.TemporaryDirectory() as directory:
            output=Path(directory)/'result'
            with patch.object(sys,'argv',['checks','--output',str(output)]), \
                 patch.object(checks,'pipeline',side_effect=failed_pipeline), \
                 contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(checks.main(),1)
            report=json.loads((output/'result.json').read_text())
            self.assertFalse(report['success'])
            self.assertEqual(report['qualified_runtime']['status'],'FAILED')

    def test_missing_isolation_flags_are_refused(self):
        result=self.runtime_probe(['-B'])
        self.assertNotEqual(result.returncode,0)
        self.assertIn(b'Verified -I -S -B runtime',result.stderr)

    def test_exact_version_and_isolation_gate(self):
        result=self.runtime_probe(['-I','-S','-B'])
        if exact_runtime():
            self.assertEqual(result.returncode,0,result.stderr.decode())
        else:
            self.assertNotEqual(result.returncode,0)
            self.assertIn(b'Verified -I -S -B runtime',result.stderr)


if __name__=='__main__':unittest.main()
