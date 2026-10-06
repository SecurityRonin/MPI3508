"""Acceptance entrypoint tests; absence is a feature assertion, not an import error."""

import os
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "mpi3508.py"


class DistributionTests(unittest.TestCase):
    def test_distribution_entrypoint(self):
        self.assertTrue(
            SCRIPT.is_file(),
            "Required standalone mpi3508.py installer behavior has not been delivered",
        )

    def run_cli(self, *args):
        self.test_distribution_entrypoint()
        return subprocess.run(
            [sys.executable, "-I", str(SCRIPT), *args],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=10,
            env={"PATH": os.defpath, "LC_ALL": "C", "HOME": str(ROOT)},
            cwd=ROOT,
            check=False,
        )

    def test_help_declares_four_commands_without_exposing_test_bypasses(self):
        result = self.run_cli("--help")
        self.assertEqual(result.returncode, 0, result.stderr)
        for command in ("preview", "install", "verify", "restore"):
            self.assertIn(command, result.stdout)
        for bypass in ("--root", "--owner-uid", "--force", "--platform", "--skip-checks"):
            self.assertNotIn(bypass, result.stdout)

    def test_preview_requires_explicit_profile(self):
        result = self.run_cli("preview")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("profile", result.stdout.lower() + result.stderr.lower())

    def test_unknown_profile_is_named(self):
        result = self.run_cli("preview", "--profile", "nonexistent-panel")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("nonexistent-panel", result.stdout + result.stderr)

    def test_cli_refuses_fixture_and_platform_overrides(self):
        for option in ("--root", "--owner-uid", "--platform", "--force"):
            with self.subTest(option=option):
                result = self.run_cli(
                    "preview", "--profile", "pi5-kali-reference", option, "/not-a-real-root"
                )
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(option, result.stdout + result.stderr)

    def test_restore_refuses_arbitrary_path(self):
        result = self.run_cli("restore", "--transaction", "../../outside", "--yes")
        self.assertNotEqual(result.returncode, 0)

    @unittest.skipIf(sys.platform == "linux", "non-Linux refusal applies only off Linux")
    def test_supported_profile_does_not_allow_install_on_non_linux(self):
        result = self.run_cli("install", "--profile", "pi5-kali-reference", "--yes")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("linux", result.stdout.lower() + result.stderr.lower())
        self.assertNotIn("Traceback", result.stderr)


if __name__ == "__main__":
    unittest.main()
