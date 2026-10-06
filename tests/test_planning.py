"""Pure acceptance tests: contract expectations, plus a scrubbed recorded matrix."""

import math
import re
import unittest
from decimal import Decimal

from tests.helpers import BOOT, PROFILE, input_class, installer, reference


class PlanningTests(unittest.TestCase):
    def setUp(self):
        self.m = installer(self)

    def assert_refuses_boot(self, content, reason):
        with self.assertRaisesRegex(self.m.InstallerError, reason):
            self.m.plan_boot(content, PROFILE)

    def test_profile_requires_nine_finite_values_and_explicit_scope(self):
        profile = self.m.PROFILES[PROFILE]
        matrix = profile["matrix"]
        self.assertEqual(len(matrix), 9)
        self.assertTrue(all(math.isfinite(float(value)) for value in matrix))
        self.assertEqual(tuple(float(value) for value in matrix[6:]), (0.0, 0.0, 1.0))
        for field, expected in (
            ("x_min", 200),
            ("x_max", 3900),
            ("y_min", 200),
            ("y_max", 3900),
            ("x_plate_ohms", 150),
        ):
            self.assertEqual(profile[field], expected)
        self.assertTrue(profile["caveat"])
        self.assertTrue(profile["wiring"])

    def test_unknown_profile_fails_loudly(self):
        for fn, args in (
            (self.m.plan_boot, (BOOT, "unmeasured-panel")),
            (self.m.render_xorg, ("unmeasured-panel",)),
        ):
            with self.subTest(function=fn.__name__):
                with self.assertRaisesRegex(self.m.InstallerError, "unmeasured-panel"):
                    fn(*args)

    def test_clean_boot_preserves_all_original_bytes_and_adds_one_overlay(self):
        planned = self.m.plan_boot(BOOT, PROFILE)
        self.assertTrue(planned.startswith(BOOT))
        overlays = [line for line in planned.splitlines() if line.startswith(b"dtoverlay=ads7846")]
        self.assertEqual(len(overlays), 1)
        for setting in (b"xmin=200", b"xmax=3900", b"ymin=200", b"ymax=3900", b"xohms=150"):
            self.assertIn(setting, overlays[0])
        self.assertNotIn(b"keep_vref_on", planned)
        self.assertLess(len(overlays[0]), 98)

    def test_boot_planning_is_idempotent(self):
        once = self.m.plan_boot(BOOT, PROFILE)
        self.assertEqual(self.m.plan_boot(once, PROFILE), once)

    def test_existing_simple_overlay_updated_without_changing_neighbors(self):
        before = (
            b"# keep exactly\n"
            b"dtoverlay=ads7846,xmin=1,xmax=4095,ymin=2,ymax=4094,xohms=100\n"
            b"dtparam=audio=on # unrelated trailing comment\n"
        )
        planned = self.m.plan_boot(before, PROFILE)
        self.assertTrue(planned.startswith(b"# keep exactly\n"))
        self.assertIn(b"dtparam=audio=on # unrelated trailing comment\n", planned)
        self.assertEqual(planned.count(b"dtoverlay=ads7846"), 1)
        self.assertNotIn(b"xmin=1,", planned)

    def test_crlf_and_non_ascii_unrelated_comment_are_preserved(self):
        before = "# 測試 fixture\r\ndtparam=audio=on\r\n".encode()
        planned = self.m.plan_boot(before, PROFILE)
        self.assertTrue(planned.startswith(before))
        self.assertNotIn(b"\n", planned.replace(b"\r\n", b""))

    def test_unterminated_final_unrelated_line_survives(self):
        before = b"dtparam=audio=on"
        planned = self.m.plan_boot(before, PROFILE)
        self.assertTrue(planned.startswith(before + b"\n"))

    def test_unrelated_model_scope_preserved_and_overlay_is_global(self):
        before = b"[pi4]\ndtparam=audio=on\n"
        planned = self.m.plan_boot(before, PROFILE)
        self.assertTrue(planned.startswith(before))
        overlay_offset = planned.index(b"dtoverlay=ads7846")
        self.assertGreater(planned.rfind(b"[all]", 0, overlay_offset), 0)

    def test_comments_are_not_active_overlays_or_includes(self):
        before = b"# dtoverlay=ads7846\n# include other.txt\n"
        planned = self.m.plan_boot(before, PROFILE)
        self.assertTrue(planned.startswith(before))
        self.assertEqual(
            sum(line.startswith(b"dtoverlay=ads7846") for line in planned.splitlines()), 1
        )

    def test_active_include_refused(self):
        for line in (b"include other.txt\n", b" include other.txt\n"):
            with self.subTest(line=line):
                self.assert_refuses_boot(BOOT + line, "(?i)include")

    def test_duplicate_active_overlays_refused(self):
        self.assert_refuses_boot(
            b"dtoverlay=ads7846\ndtoverlay=ads7846,xmin=200\n", "(?i)duplicate|multiple"
        )

    def test_conditional_touchscreen_overlay_refused(self):
        for section in (b"[pi4]", b"[pi5]", b"[HDMI:0]", b"[gpio4=1]"):
            with self.subTest(section=section):
                self.assert_refuses_boot(section + b"\ndtoverlay=ads7846\n", "(?i)scope|condition")

    def test_malformed_section_refused(self):
        self.assert_refuses_boot(b"[pi5\ndtoverlay=ads7846\n", "(?i)section|malformed")

    def test_unsupported_parameter_refused_and_named(self):
        for parameter in (b"keep_vref_on=1", b"made_up=12"):
            with self.subTest(parameter=parameter):
                self.assert_refuses_boot(
                    b"dtoverlay=ads7846," + parameter + b"\n", parameter.split(b"=")[0].decode()
                )

    def test_duplicate_parameter_refused(self):
        self.assert_refuses_boot(b"dtoverlay=ads7846,xmin=200,xmin=201\n", "(?i)duplicate|xmin")

    def test_nul_input_refused(self):
        self.assert_refuses_boot(BOOT + b"\0", "(?i)nul|invalid|binary")

    def test_generated_xorg_has_exact_match_and_full_recorded_matrix(self):
        rule = self.m.render_xorg(PROFILE).decode("utf-8")
        self.assertRegex(rule, r'MatchProduct\s+"ADS7846 Touchscreen"')
        self.assertRegex(rule, r'MatchIsTouchscreen\s+"on"')
        self.assertRegex(rule, r'Driver\s+"libinput"')
        matrix = re.findall(r'Option\s+"CalibrationMatrix"\s+"([^"]+)"', rule)
        self.assertEqual(len(matrix), 1)
        actual = matrix[0].split()
        expected = reference()["matrix"]
        self.assertEqual(len(actual), 9)
        for observed, recorded in zip(actual, expected, strict=True):
            self.assertLessEqual(abs(Decimal(observed) - Decimal(recorded)), Decimal("1e-15"))
        self.assertNotRegex(rule, r'Option\s+"(?:Calibration|SwapAxes|Invert[XY])"')

    def test_planner_does_not_emit_unrelated_system_changes(self):
        planned = self.m.plan_boot(BOOT, PROFILE) + self.m.render_xorg(PROFILE)
        for forbidden in (
            b"hdmi_",
            b"display_rotate",
            b"vc4-",
            b"autologin",
            b"terminal",
            b"keyboard",
            b"ssh",
            b"network",
            b"/home/",
            b"boot_id",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, planned.lower())


class ConflictTests(unittest.TestCase):
    def setUp(self):
        self.m = installer(self)

    def test_unrelated_mouse_evdev_rule_allowed(self):
        self.m.check_xorg_conflicts(
            {"20-mouse.conf": input_class(product="USB Mouse", driver="evdev")}
        )

    def test_unconfigured_generic_libinput_rule_allowed(self):
        self.m.check_xorg_conflicts({"40-libinput.conf": input_class()})

    def test_applicable_evdev_rule_refused_and_path_named(self):
        with self.assertRaisesRegex(self.m.InstallerError, "99-legacy.conf"):
            self.m.check_xorg_conflicts({"99-legacy.conf": input_class(driver="evdev")})

    def test_substring_and_alternative_matches_are_applicable(self):
        for product in ("ADS7846", "ADS7846|Other Touchscreen"):
            with self.subTest(product=product):
                with self.assertRaises(self.m.InstallerError):
                    self.m.check_xorg_conflicts(
                        {"20-legacy.conf": input_class(product=product, driver="evdev")}
                    )

    def test_broad_touchscreen_evdev_rule_refused(self):
        broad = input_class(driver="evdev").replace(b'  MatchProduct "ADS7846 Touchscreen"\n', b"")
        with self.assertRaises(self.m.InstallerError):
            self.m.check_xorg_conflicts({"20-all-touch.conf": broad})

    def test_all_competing_calibration_spellings_refused(self):
        for option, value in (
            ("CalibrationMatrix", "1 0 0.1 0 1 0 0 0 1"),
            ("Calibration", "200 3900 200 3900"),
            ("TransformationMatrix", "1 0 0.2 0 1 0 0 0 1"),
            ("Coordinate Transformation Matrix", "1 0 0.3 0 1 0 0 0 1"),
            ("SwapAxes", "on"),
            ("InvertX", "on"),
            ("InvertY", "on"),
        ):
            with self.subTest(option=option):
                with self.assertRaisesRegex(self.m.InstallerError, "35-other.conf"):
                    self.m.check_xorg_conflicts(
                        {"35-other.conf": input_class(options=((option, value),))}
                    )

    def test_identity_ctm_allowed(self):
        self.m.check_xorg_conflicts(
            {
                "35-identity.conf": input_class(
                    options=(("TransformationMatrix", "1 0 0 0 1 0 0 0 1"),)
                )
            }
        )

    def test_malformed_applicable_rule_refused(self):
        malformed = input_class().replace(b"EndSection\n", b"")
        with self.assertRaisesRegex(self.m.InstallerError, "broken.conf"):
            self.m.check_xorg_conflicts({"broken.conf": malformed})


if __name__ == "__main__":
    unittest.main()
