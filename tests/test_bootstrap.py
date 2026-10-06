"""Bootstrap trust-boundary tests. Payload fixtures do not implement the bootstrap."""

import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from tests.helpers import installer

PAYLOAD = b"""import json, pathlib, sys
p = pathlib.Path(sys.argv[1])
if p.exists():
    raise RuntimeError("Payload executed more than once")
p.write_text(json.dumps({"argv":sys.argv,"name":__name__,"file":__file__,
                        "isolated":sys.flags.isolated}), encoding="utf-8")
"""

SWAP_SUPERVISOR = """import hashlib, pathlib, sys
source, artifact, digest, marker, swap_marker = sys.argv[1:]
original_sha256 = hashlib.sha256
def swap_on_hash(*args, **kwargs):
    result = original_sha256(*args, **kwargs)
    pathlib.Path(artifact).write_text("raise RuntimeError('unchecked replacement executed')\\n")
    pathlib.Path(swap_marker).write_text("swapped")
    return result
hashlib.sha256 = swap_on_hash
sys.argv = ["-c", artifact, digest, marker, "probe-argument"]
exec(compile(source, "<bootstrap-under-test>", "exec"), {"__name__":"__main__"})
"""


class BootstrapTests(unittest.TestCase):
    def setUp(self):
        self.m = installer(self)
        self.assertTrue(
            hasattr(self.m, "VERIFICATION_BOOTSTRAP"), "Required checked-buffer bootstrap is absent"
        )
        self.source = self.m.VERIFICATION_BOOTSTRAP
        self.assertIsInstance(self.source, str)
        self.root = Path(tempfile.mkdtemp(prefix="mpi3508-bootstrap-test-"))
        self.artifact = self.root / "payload.py"
        self.artifact.write_bytes(PAYLOAD)
        self.artifact.chmod(0o600)
        self.marker = self.root / "execution.json"
        self.digest = hashlib.sha256(PAYLOAD).hexdigest()

    def run_bootstrap(self, artifact=None, digest=None, *, optimized=False, env=None):
        command = [sys.executable, "-I"]
        if optimized:
            command.append("-O")
        command.extend(
            [
                "-c",
                self.source,
                str(artifact or self.artifact),
                digest or self.digest,
                str(self.marker),
                "probe-argument",
            ]
        )
        return subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=10,
            cwd=self.root,
            env=env,
            check=False,
        )

    def test_matching_digest_executes_once_with_preserved_script_context(self):
        result = self.run_bootstrap()
        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads(self.marker.read_text())
        self.assertEqual(report["argv"], [str(self.artifact), str(self.marker), "probe-argument"])
        self.assertEqual(report["name"], "__main__")
        self.assertEqual(report["file"], str(self.artifact))
        self.assertEqual(report["isolated"], 1)

    def test_wrong_digest_never_executes_under_normal_or_optimized_python(self):
        for optimized in (False, True):
            with self.subTest(optimized=optimized):
                result = self.run_bootstrap(digest="0" * 64, optimized=optimized)
                self.assertNotEqual(result.returncode, 0)
                self.assertFalse(self.marker.exists())

    def test_malformed_digest_never_executes(self):
        for digest in ("z" * 64, "f" * 63, "f" * 65, "sha256:garbage"):
            with self.subTest(digest=digest):
                result = self.run_bootstrap(digest=digest)
                self.assertNotEqual(result.returncode, 0)
                self.assertFalse(self.marker.exists())

    def test_truncated_payload_never_executes(self):
        self.artifact.write_bytes(PAYLOAD[:-1])
        result = self.run_bootstrap()
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(self.marker.exists())

    def test_missing_payload_never_executes(self):
        self.artifact.unlink()
        result = self.run_bootstrap()
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(self.marker.exists())

    def test_symlink_or_hardlink_artifact_never_executes(self):
        alias = self.root / "linked-payload.py"
        alias.symlink_to(self.artifact)
        result = self.run_bootstrap(artifact=alias)
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(self.marker.exists())
        alias.unlink()
        os.link(self.artifact, alias)
        result = self.run_bootstrap()
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(self.marker.exists())

    def test_group_or_world_writable_artifact_never_executes(self):
        self.artifact.chmod(0o666)
        result = self.run_bootstrap()
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(self.marker.exists())

    def test_checked_buffer_executes_after_on_disk_replacement(self):
        swap_marker = self.root / "swap-observed"
        result = subprocess.run(
            [
                sys.executable,
                "-I",
                "-c",
                SWAP_SUPERVISOR,
                self.source,
                str(self.artifact),
                self.digest,
                str(self.marker),
                str(swap_marker),
            ],
            capture_output=True,
            text=True,
            timeout=10,
            cwd=self.root,
            check=False,
        )
        self.assertTrue(swap_marker.exists(), "Digest-boundary mutation did not run")
        self.assertNotEqual(
            self.artifact.read_bytes(), PAYLOAD, "Mutation must change on-disk bytes"
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(self.marker.exists(), "Original checked buffer was not executed")

    def test_isolated_python_ignores_cwd_and_pythonpath_modules(self):
        evil_marker = self.root / "untrusted-import"
        malicious = f"from pathlib import Path\nPath({str(evil_marker)!r}).write_text('bad')\n"
        for name in ("json.py", "hashlib.py"):
            (self.root / name).write_text(malicious)
        env = dict(os.environ, PYTHONPATH=str(self.root))
        result = self.run_bootstrap(env=env)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(self.marker.exists())
        self.assertFalse(evil_marker.exists())


if __name__ == "__main__":
    unittest.main()
