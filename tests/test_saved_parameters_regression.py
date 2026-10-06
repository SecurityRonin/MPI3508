"""T3 synthetic saved-readback regressions, not a physical calibration oracle."""

import re
import unittest
from unittest.mock import patch

from tests.helpers import BOOT_REL, PROFILE, RULE_REL, fixture, installer

EXPECTED_PARAMETERS = {
    "xmin": "200",
    "xmax": "3900",
    "ymin": "200",
    "ymax": "3900",
    "xohms": "150",
    "penirq": "25",
    "speed": "50000",
    "cs": "1",
}


class SavedParametersRegressionTests(unittest.TestCase):
    def setUp(self):
        self.m = installer(self)
        self.layout, self.root = fixture(self, self.m)
        self.m.install(self.layout, PROFILE)
        self.boot = self.root / BOOT_REL
        self.rule = self.root / RULE_REL

    def overlay(self, raw):
        matches = list(re.finditer(rb"(?m)^dtoverlay=ads7846(?:,[^\r\n]*)?$", raw))
        self.assertEqual(len(matches), 1, "Mutation must select exactly one ADS7846 overlay")
        match = matches[0]
        tokens = match.group().split(b",")[1:]
        for line in raw[match.end() :].splitlines():
            if line.startswith(b"dtoverlay="):
                break
            if line.startswith(b"dtparam="):
                tokens.extend(line.removeprefix(b"dtparam=").split(b","))
        pairs = [token.split(b"=", 1) for token in tokens]
        self.assertTrue(all(len(pair) == 2 for pair in pairs))
        parameters = {key.decode(): value.decode() for key, value in pairs}
        self.assertEqual(len(parameters), len(pairs), "Input must have no duplicate parameter keys")
        return match, parameters

    def verify(self):
        before = self.boot.read_bytes(), self.rule.read_bytes()
        with (
            patch.object(
                self.m, "plan_boot", side_effect=AssertionError("Planner is not an oracle")
            ),
            patch.object(
                self.m, "render_xorg", side_effect=AssertionError("Renderer is not an oracle")
            ),
        ):
            report = self.m.verify_saved(self.layout, PROFILE)
        self.assertEqual((self.boot.read_bytes(), self.rule.read_bytes()), before)
        self.assertEqual(report["runtime"], "not-examined")
        self.assertEqual(report["physical"], "not-examined")
        return report["saved"]

    def test_unmodified_complete_parameter_set_matches(self):
        _, parameters = self.overlay(self.boot.read_bytes())
        self.assertEqual(parameters, EXPECTED_PARAMETERS)
        self.assertEqual(self.verify(), "match")

    def test_unrelated_comment_does_not_change_saved_match(self):
        before = self.boot.read_bytes()
        self.boot.write_bytes(before + b"# Synthetic unrelated comment\n")
        _, parameters = self.overlay(self.boot.read_bytes())
        self.assertEqual(parameters, EXPECTED_PARAMETERS)
        self.assertEqual(self.verify(), "match")

    def test_each_additional_supported_parameter_is_mismatch(self):
        original = self.boot.read_bytes()
        match, parameters = self.overlay(original)
        self.assertEqual(parameters, EXPECTED_PARAMETERS)
        for key, value in (("swapxy", "1"), ("penirq_pull", "2"), ("pmin", "1"), ("pmax", "4095")):
            with self.subTest(parameter=key):
                token = f",{key}={value}".encode()
                altered = original[: match.end()] + token + original[match.end() :]
                self.assertNotEqual(altered, original, "Parameter mutation must actually apply")
                _, changed = self.overlay(altered)
                self.assertEqual(changed, {**EXPECTED_PARAMETERS, key: value})
                self.boot.write_bytes(altered)
                self.assertEqual(self.verify(), "mismatch")


if __name__ == "__main__":
    unittest.main()
