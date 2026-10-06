"""Native Linux CLI preflight controls; only read-only commands touch fixed host paths."""

import hashlib
import os
import subprocess
import sys
import unittest
from pathlib import Path

from tests.helpers import PROFILE, SCRIPT

TARGETS = (
    Path("/boot/firmware/config.txt"),
    Path("/etc/X11/xorg.conf.d/99-mpi3508-touch.conf"),
    Path("/var/lib/mpi3508"),
)


def snapshot():
    result = []
    for path in TARGETS:
        try:
            info = path.lstat()
        except FileNotFoundError:
            result.append(None)
            continue
        digest = None
        if path.is_file() and not path.is_symlink():
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
        result.append((info.st_ino, info.st_mode, info.st_size, info.st_mtime_ns, digest))
    return result


@unittest.skipUnless(sys.platform == "linux", "Native Linux preflight exercised in Linux CI")
class LinuxPreflightTests(unittest.TestCase):
    def setUp(self):
        self.assertTrue(SCRIPT.is_file(), "Required standalone installer behavior is absent")
        model = Path("/proc/device-tree/model")
        if model.exists() and b"Raspberry Pi 5" in model.read_bytes():
            self.skipTest("This refusal control is for a Linux host without Pi 5 identity")

    def test_preview_missing_pi_prerequisite_refuses_without_writes(self):
        for optimized in (False, True):
            with self.subTest(optimized=optimized):
                before = snapshot()
                command = [sys.executable, "-I"]
                if optimized:
                    command.append("-O")
                command.extend([str(SCRIPT), "preview", "--profile", PROFILE])
                result = subprocess.run(
                    command,
                    stdin=subprocess.DEVNULL,
                    capture_output=True,
                    text=True,
                    timeout=10,
                    env={"PATH": os.defpath, "LC_ALL": "C"},
                    check=False,
                )
                self.assertNotEqual(result.returncode, 0)
                diagnostic = result.stdout.lower() + result.stderr.lower()
                self.assertRegex(diagnostic, "raspberry|pi 5|arm64|aarch64|platform")
                self.assertNotIn("traceback", diagnostic)
                self.assertEqual(
                    snapshot(), before, "Preview must not create state or alter targets"
                )


if __name__ == "__main__":
    unittest.main()
