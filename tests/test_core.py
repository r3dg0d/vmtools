import hashlib
import tempfile
import unittest
from pathlib import Path

from vmtools.checksum import sha256_file, verification_label, verify_sha256
from vmtools.config import validate_name, write_json, read_json, NAME_RE
from vmtools.ui import Fail
from androidvm.ports import allocate
from androidvm.access import access_configured


class TestNames(unittest.TestCase):
    def test_ok(self):
        self.assertEqual(validate_name("win11-main"), "win11-main")

    def test_bad(self):
        with self.assertRaises(Fail):
            validate_name("../etc")


class TestChecksum(unittest.TestCase):
    def test_roundtrip(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "f.bin"
            data = b"vmtools-test-bytes"
            p.write_bytes(data)
            expect = hashlib.sha256(data).hexdigest()
            self.assertEqual(sha256_file(p, progress=False), expect)
            self.assertTrue(verify_sha256(p, expect))
            self.assertFalse(verify_sha256(p, "0" * 64))
            self.assertEqual(verification_label(publisher=True), "VERIFIED AGAINST PUBLISHER")
            self.assertEqual(verification_label(local_only=True), "LOCAL HASH ONLY")


class TestJson(unittest.TestCase):
    def test_atomic(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "c.json"
            write_json(p, {"a": 1})
            self.assertEqual(read_json(p)["a"], 1)


class TestAndroid(unittest.TestCase):
    def test_ports(self):
        ports = allocate(18000, 2)
        self.assertEqual(len(ports), 2)

    def test_access_default(self):
        # without env, typically false
        self.assertIsInstance(access_configured(), bool)


if __name__ == "__main__":
    unittest.main()
