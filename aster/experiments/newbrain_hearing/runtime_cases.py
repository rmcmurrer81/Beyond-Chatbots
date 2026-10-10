"""Exercise unchanged RunIO only in its exact accepted isolated interpreter."""
from pathlib import Path
import tempfile
import unittest

from run_io import RunIO, ProductPreflightError, APPLICATION_CAP, EMERGENCY_CAP


class RuntimeGuardTests(unittest.TestCase):
    def setUp(self):
        self.temporary=tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root=Path(self.temporary.name)
        self.io=RunIO(self.root,self.root/'STOP')

    def test_full_write_readback_and_once_only_destination(self):
        saved=self.io.write('payload.bin',b'abc',3)
        self.assertEqual((self.root/'payload.bin').read_bytes(),b'abc')
        self.assertEqual(saved['bytes'],3)
        self.assertEqual(self.io.application,7)
        with self.assertRaises(FileExistsError):self.io.write('payload.bin',b'def',3)
        self.assertEqual((self.root/'payload.bin').read_bytes(),b'abc')

    def test_oversized_payload_fails_before_write(self):
        with self.assertRaises(ProductPreflightError):self.io.write('large.bin',b'abcd',3)
        self.assertFalse((self.root/'large.bin').exists())
        self.assertEqual(self.io.application,0)
        self.assertEqual(self.io.failed_products[0]['raw'],b'abcd')

    def test_path_escape_refused(self):
        with self.assertRaises(ProductPreflightError):self.io.write('../escape.bin',b'x',1)
        self.assertEqual(self.io.application,0)

    def test_normal_budget_does_not_borrow_emergency_account(self):
        self.io.charge(APPLICATION_CAP)
        with self.assertRaises(ProductPreflightError):self.io.write('normal.bin',b'x',1)
        self.assertEqual(self.io.emergency,0)
        self.io.write('emergency.bin',b'x',1,emergency=True)
        self.assertEqual(self.io.emergency,3)
        self.assertEqual(self.io.application,APPLICATION_CAP)

    def test_emergency_budget_is_finite(self):
        self.io.charge(EMERGENCY_CAP,emergency=True)
        with self.assertRaises(ProductPreflightError):self.io.write('overflow.bin',b'x',1,emergency=True)
        self.assertFalse((self.root/'overflow.bin').exists())

    def test_cooperative_stop_retains_reason_and_stops(self):
        (self.root/'STOP').write_bytes(b'aster fixture stop')
        with self.assertRaisesRegex(RuntimeError,'Root cooperative stop'):self.io.checkpoint('test')
        self.assertEqual(self.io.phase,'test')
        self.assertTrue(self.io.rows[-1]['close_acknowledged'])

    def test_read_cap_cannot_clip_input(self):
        p=self.root/'input.bin';p.write_bytes(b'1234')
        with self.assertRaisesRegex(RuntimeError,'Complete own plain input'):self.io.read(p,3)
        self.assertEqual(p.read_bytes(),b'1234')
        self.assertEqual(self.io.application,4)
