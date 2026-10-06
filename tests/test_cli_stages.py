"""Exercise the shipping CLI decision with mocked hardware boundaries and real fixture writes."""

import contextlib
import io
import unittest
from unittest.mock import patch

from tests.helpers import BOOT, BOOT_REL, PROFILE, RULE_REL, fixture, installer


class CliStageSelectionTests(unittest.TestCase):
    def setUp(self):
        self.m = installer(self)

    def invoke(self, report):
        layout, root = fixture(self, self.m)
        output = io.StringIO()
        real_install = self.m.install
        with (
            patch.object(self.m, "check_environment", return_value=None),
            patch.object(self.m.os, "geteuid", return_value=0),
            patch.object(self.m, "runtime_report", return_value=report),
            patch.object(self.m, "Layout", return_value=layout),
            patch.object(self.m, "install", wraps=real_install) as observed_install,
            contextlib.redirect_stdout(output),
            contextlib.redirect_stderr(output),
        ):
            code = self.m.main(["install", "--profile", PROFILE, "--yes"])
        self.assertEqual(code, 0, output.getvalue())
        self.assertEqual(observed_install.call_count, 1, "CLI must reach guarded transaction API")
        return root, output.getvalue(), observed_install.call_args

    def test_cli_install_requires_root_even_with_yes(self):
        layout, root = fixture(self, self.m)
        output = io.StringIO()
        with (
            patch.object(self.m, "check_environment", return_value=None),
            patch.object(self.m.os, "geteuid", return_value=12345),
            patch.object(self.m, "Layout", return_value=layout),
            patch.object(self.m, "install", wraps=self.m.install) as observed_install,
            contextlib.redirect_stdout(output),
            contextlib.redirect_stderr(output),
        ):
            code = self.m.main(["install", "--profile", PROFILE, "--yes"])
        self.assertNotEqual(code, 0)
        self.assertEqual(observed_install.call_count, 0)
        self.assertEqual((root / BOOT_REL).read_bytes(), BOOT)
        self.assertFalse((root / RULE_REL).exists())
        self.assertRegex(output.getvalue().lower(), "root|privilege")

    def test_cli_confirmation_eof_never_mutates_targets(self):
        layout, root = fixture(self, self.m)
        output = io.StringIO()
        with (
            patch.object(self.m, "check_environment", return_value=None),
            patch.object(self.m.os, "geteuid", return_value=0),
            patch.object(self.m, "runtime_report", return_value={"bounds": "unavailable"}),
            patch.object(self.m, "Layout", return_value=layout),
            patch.object(self.m, "install", wraps=self.m.install) as observed_install,
            patch("builtins.input", side_effect=EOFError),
            contextlib.redirect_stdout(output),
            contextlib.redirect_stderr(output),
        ):
            code = self.m.main(["install", "--profile", PROFILE])
        self.assertNotEqual(code, 0)
        self.assertEqual(observed_install.call_count, 0)
        self.assertEqual((root / BOOT_REL).read_bytes(), BOOT)
        self.assertFalse((root / RULE_REL).exists())

    def test_matching_effective_bounds_allow_xorg_persistence(self):
        root, output, call = self.invoke(
            {"bounds": "match", "dt_bounds": "match", "abs_bounds": "match"}
        )
        self.assertTrue(call.kwargs.get("include_xorg", True))
        self.assertEqual((root / RULE_REL).read_bytes(), self.m.render_xorg(PROFILE))
        self.assertNotIn("physical-accepted", output.lower())

    def test_mismatch_unavailable_or_missing_bounds_cannot_persist_matrix(self):
        reports = (
            {"bounds": "mismatch", "dt_bounds": "match", "abs_bounds": "mismatch"},
            {"bounds": "unavailable", "dt_bounds": "unavailable", "abs_bounds": "unavailable"},
            {"bounds": "not-examined"},
            {},
        )
        for report in reports:
            with self.subTest(report=report):
                root, output, call = self.invoke(report)
                self.assertFalse(call.kwargs.get("include_xorg", True))
                self.assertFalse((root / RULE_REL).exists())
                self.assertEqual((root / BOOT_REL).read_bytes(), self.m.plan_boot(BOOT, PROFILE))
                self.assertIn("boot-configured-reboot-required", output)

    def test_aggregate_match_cannot_hide_missing_component_observation(self):
        for report in (
            {"bounds": "match", "dt_bounds": "unavailable", "abs_bounds": "match"},
            {"bounds": "match", "dt_bounds": "match", "abs_bounds": "mismatch"},
            {"bounds": "match"},
        ):
            with self.subTest(report=report):
                root, output, call = self.invoke(report)
                self.assertFalse(call.kwargs.get("include_xorg", True))
                self.assertFalse((root / RULE_REL).exists())
                self.assertIn("boot-configured-reboot-required", output)


if __name__ == "__main__":
    unittest.main()
