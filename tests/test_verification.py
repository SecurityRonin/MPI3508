"""Saved-file verification must not borrow the planner's answer or imply physical accuracy."""

import re
import unittest
from decimal import Decimal
from unittest.mock import patch

from tests.helpers import BOOT_REL, PROFILE, RULE_REL, fixture, installer


class VerificationTests(unittest.TestCase):
    def setUp(self):
        self.m = installer(self)
        self.layout, self.root = fixture(self, self.m)

    def test_saved_match_is_independently_checked_without_planner(self):
        self.m.install(self.layout, PROFILE)
        with (
            patch.object(
                self.m, "plan_boot", side_effect=AssertionError("Planner is not an oracle")
            ),
            patch.object(
                self.m, "render_xorg", side_effect=AssertionError("Renderer is not an oracle")
            ),
        ):
            report = self.m.verify_saved(self.layout, PROFILE)
        self.assertEqual(report["saved"], "match")
        self.assertEqual(report["runtime"], "not-examined")
        self.assertEqual(report["physical"], "not-examined")

    def test_saved_matrix_mismatch_not_reported_as_match(self):
        self.m.install(self.layout, PROFILE)
        rule = self.root / RULE_REL
        original = rule.read_bytes()
        match = re.search(rb'Option\s+"CalibrationMatrix"\s+"([^"]+)"', original)
        self.assertIsNotNone(match)
        values = match.group(1).split()
        self.assertEqual(len(values), 9)
        self.assertNotEqual(Decimal(values[1].decode()), Decimal(0))
        values[1] = str(-Decimal(values[1].decode())).encode()
        altered = original[: match.start(1)] + b" ".join(values) + original[match.end(1) :]
        self.assertNotEqual(altered, original, "Matrix mutation must actually apply")
        rule.write_bytes(altered)
        report = self.m.verify_saved(self.layout, PROFILE)
        self.assertEqual(report["saved"], "mismatch")
        self.assertEqual(report["physical"], "not-examined")

    def test_saved_boot_bounds_mismatch_is_detected(self):
        self.m.install(self.layout, PROFILE)
        boot = self.root / BOOT_REL
        altered = boot.read_bytes().replace(b"xmin=200", b"xmin=201")
        self.assertNotEqual(altered, boot.read_bytes(), "Boot mutation must actually apply")
        boot.write_bytes(altered)
        self.assertEqual(self.m.verify_saved(self.layout, PROFILE)["saved"], "mismatch")

    def test_unavailable_rule_is_distinct_from_matrix_mismatch(self):
        self.m.install(self.layout, PROFILE, include_xorg=False)
        self.assertFalse((self.root / RULE_REL).exists())
        report = self.m.verify_saved(self.layout, PROFILE)
        self.assertEqual(report["saved"], "unavailable")
        self.assertEqual(report["physical"], "not-examined")

    def test_unknown_profile_refused(self):
        with self.assertRaisesRegex(self.m.InstallerError, "unknown-panel"):
            self.m.verify_saved(self.layout, "unknown-panel")


if __name__ == "__main__":
    unittest.main()
