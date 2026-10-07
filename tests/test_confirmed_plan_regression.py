"""Install may write only changes it disclosed before acknowledgement, using fixture layouts.

Preview as an unprivileged user can see less runtime evidence than the privileged install
(for example an unreadable /dev/input/eventN), so the two can plan different targets. The
invariant is observable at the CLI: every target the install changes must have its planned
change shown before confirmation (or before the first target write under --yes), otherwise
the install refuses without changing any target.
"""

import contextlib
import io
import unittest
from unittest.mock import patch

from tests.helpers import BOOT, BOOT_REL, PROFILE, RULE_REL, fixture, installer

MATCH = {"bounds": "match", "dt_bounds": "match", "abs_bounds": "match"}
UNAVAILABLE = {"bounds": "unavailable", "dt_bounds": "unavailable", "abs_bounds": "unavailable"}


class ConfirmedPlanTests(unittest.TestCase):
    def setUp(self):
        self.m = installer(self)
        self.layout, self.root = fixture(self, self.m)

    def run_cli(self, argv, report, *, euid):
        output = io.StringIO()
        disclosed = {}

        def confirm(prompt=""):
            disclosed.setdefault("confirmation", output.getvalue())
            return "yes"

        real_replace = self.m.Files.replace
        real_remove = self.m.Files.remove

        def first_write(real):
            def observed(files, *args, **kwargs):
                disclosed.setdefault("write", output.getvalue())
                return real(files, *args, **kwargs)

            return observed

        with (
            patch.object(self.m, "check_environment", return_value=None),
            patch.object(self.m.os, "geteuid", return_value=euid),
            patch.object(self.m, "runtime_report", return_value=report),
            patch.object(self.m, "Layout", return_value=self.layout),
            patch.object(self.m.Files, "replace", first_write(real_replace)),
            patch.object(self.m.Files, "remove", first_write(real_remove)),
            patch("builtins.input", side_effect=confirm),
            contextlib.redirect_stdout(output),
            contextlib.redirect_stderr(output),
        ):
            code = self.m.main(argv)
        return code, output.getvalue(), disclosed

    def planned_changes(self, include_xorg):
        changes = {}
        if include_xorg:
            rule = self.m.render_xorg(PROFILE)
            changes["/" + str(RULE_REL)] = [line for line in rule.splitlines() if line.strip()]
        boot = self.m.plan_boot(BOOT, PROFILE)
        changes["/" + str(BOOT_REL)] = [line for line in boot.splitlines() if line not in BOOT]
        return changes

    def assert_disclosed(self, shown, include_xorg):
        for path, lines in self.planned_changes(include_xorg).items():
            self.assertIn(path, shown, f"Install changed {path} without showing it first")
            for line in lines:
                self.assertIn(
                    line.decode(), shown, f"Install did not show planned {path} line {line!r}"
                )

    def assert_unchanged(self):
        self.assertEqual((self.root / BOOT_REL).read_bytes(), BOOT)
        self.assertFalse((self.root / RULE_REL).exists())

    def test_install_never_writes_xorg_rule_hidden_by_boot_only_preview(self):
        code, preview, _ = self.run_cli(["preview", "--profile", PROFILE], UNAVAILABLE, euid=1000)
        self.assertEqual(code, 0, preview)
        self.assertNotIn("/" + str(RULE_REL), preview)
        self.assert_disclosed(preview, include_xorg=False)  # Control: the matcher can pass.
        _, full_preview, _ = self.run_cli(["preview", "--profile", PROFILE], MATCH, euid=1000)
        self.assert_disclosed(full_preview, include_xorg=True)
        self.assert_unchanged()

        code, output, disclosed = self.run_cli(["install", "--profile", PROFILE], MATCH, euid=0)
        if code != 0:
            self.assert_unchanged()
            return
        self.assertIn("confirmation", disclosed, output)
        self.assertEqual(
            (self.root / RULE_REL).read_bytes(),
            self.m.render_xorg(PROFILE),
            output,
        )
        self.assert_disclosed(disclosed["confirmation"], include_xorg=True)

    def test_noninteractive_install_shows_every_target_change_before_writing(self):
        for report, include_xorg in ((MATCH, True), (UNAVAILABLE, False)):
            with self.subTest(include_xorg=include_xorg):
                self.layout, self.root = fixture(self, self.m)
                argv = ["install", "--profile", PROFILE, "--yes"]
                code, output, disclosed = self.run_cli(argv, report, euid=0)
                if code != 0:
                    self.assert_unchanged()
                    continue
                self.assertIn("write", disclosed, output)
                self.assertEqual((self.root / RULE_REL).exists(), include_xorg, output)
                self.assert_disclosed(disclosed["write"], include_xorg)

    def test_interactive_install_with_consistent_evidence_shows_plan_and_proceeds(self):
        code, output, disclosed = self.run_cli(
            ["install", "--profile", PROFILE], UNAVAILABLE, euid=0
        )
        self.assertEqual(code, 0, output)
        self.assertEqual(
            (self.root / BOOT_REL).read_bytes(), self.m.plan_boot(BOOT, PROFILE), output
        )
        self.assertFalse((self.root / RULE_REL).exists())
        self.assertIn("confirmation", disclosed, output)
        self.assert_disclosed(disclosed["confirmation"], include_xorg=False)


if __name__ == "__main__":
    unittest.main()
