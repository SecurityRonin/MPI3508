"""T3 mock-boundary regressions; actual Linux mount validation is a separate oracle."""

import contextlib
import hashlib
import os
import stat
import unittest
from unittest.mock import patch

from tests.helpers import BOOT_REL, PROFILE, RULE_REL, STATE_REL, fixture, installer


class MountBoundariesRegressionTests(unittest.TestCase):
    def setUp(self):
        self.m = installer(self)
        self.layout, self.root = fixture(self, self.m)
        (self.root / STATE_REL).mkdir(mode=0o700)

    def snapshot(self):
        result = {}
        for path in (self.root, *sorted(self.root.rglob("*"))):
            info = path.lstat()
            result[str(path.relative_to(self.root))] = (
                info.st_dev,
                info.st_ino,
                info.st_uid,
                info.st_gid,
                stat.S_IMODE(info.st_mode),
                hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None,
            )
        return result

    @contextlib.contextmanager
    def observations(self, boundary=None, *, separate_device=False, unavailable=None):
        real_stat, real_fstat = os.stat, os.fstat
        directories = {self.root.stat().st_ino: ""}
        directories.update(
            (path.stat().st_ino, str(path.relative_to(self.root)))
            for path in self.root.rglob("*")
            if path.is_dir()
        )
        seen = {"stat": set(), "fstat": set(), "mount": set()}
        if boundary is not None:
            child = real_stat(self.root / boundary)
            parent = real_stat((self.root / boundary).parent)
            self.assertEqual(child.st_dev, parent.st_dev, "Synthetic input starts on one device")
            self.assertIn(child.st_ino, directories)

        def crossed(relative):
            return boundary is not None and (
                relative == boundary or relative.startswith(boundary + "/")
            )

        def device_observation(info, method):
            if stat.S_ISDIR(info.st_mode) and info.st_ino in directories:
                relative = directories[info.st_ino]
                seen[method].add(relative)
                if separate_device and crossed(relative):
                    values = list(info)
                    values[2] = info.st_dev + 1
                    changed = os.stat_result(values)
                    self.assertNotEqual(changed.st_dev, info.st_dev)
                    self.assertEqual(changed.st_ino, info.st_ino)
                    return changed
            return info

        def observed_stat(*args, **kwargs):
            return device_observation(real_stat(*args, **kwargs), "stat")

        def observed_fstat(fd):
            return device_observation(real_fstat(fd), "fstat")

        def observed_mount(fd):
            info = real_fstat(fd)
            self.assertTrue(stat.S_ISDIR(info.st_mode), "Observe only directory descriptors")
            relative = directories.get(info.st_ino)
            self.assertIsNotNone(relative, "Descriptor must name a selected fixture directory")
            seen["mount"].add(relative)
            if unavailable == "error":
                raise OSError("Synthetic mount observation unavailable")
            if unavailable == "missing":
                return None
            if unavailable == "malformed":
                return "not-a-mount-id"
            return 202 if crossed(relative) else 101

        with (
            patch.object(self.m.os, "stat", side_effect=observed_stat),
            patch.object(self.m.os, "fstat", side_effect=observed_fstat),
            patch.object(self.m, "mount_id", side_effect=observed_mount, create=True),
            patch.object(self.m.sys, "platform", "linux"),
            patch.object(self.m.platform, "system", return_value="Linux"),
        ):
            yield seen

    def assert_refusal(self, boundary, *, separate_device=False, unavailable=None):
        before = self.snapshot()
        with self.observations(
            boundary, separate_device=separate_device, unavailable=unavailable
        ) as seen:
            with self.assertRaisesRegex(self.m.InstallerError, "(?i)mount|boundary|observation"):
                self.m.install(self.layout, PROFILE)
            self.assertTrue(seen["mount"], "GREEN requires mount observations on the real path")
            if boundary is not None:
                self.assertIn(boundary, seen["stat"])
                self.assertIn(boundary, seen["fstat"])
                if not separate_device:
                    self.assertIn(boundary, seen["mount"])
        self.assertEqual(self.snapshot(), before, "Refusal must precede every fixture mutation")
        self.assertFalse((self.root / RULE_REL).exists())

    def test_unmounted_fixture_installs_and_restores(self):
        original = (self.root / BOOT_REL).read_bytes()
        transaction = self.m.install(self.layout, PROFILE)
        self.assertTrue((self.root / RULE_REL).is_file())
        self.m.restore(self.layout, transaction)
        self.assertEqual((self.root / BOOT_REL).read_bytes(), original)
        self.assertFalse((self.root / RULE_REL).exists())

    def test_unexpected_different_device_mount_refused_before_writes(self):
        self.assert_refusal("etc/X11/xorg.conf.d", separate_device=True)

    def test_unexpected_same_device_mount_refused_before_writes(self):
        self.assert_refusal("etc/X11/xorg.conf.d")

    def test_unexpected_ancestor_and_state_mounts_refused(self):
        for boundary in ("boot", "etc", "etc/X11", "var", "var/lib", str(STATE_REL)):
            with self.subTest(boundary=boundary):
                self.setUp()
                self.assert_refusal(boundary)

    def test_expected_firmware_mount_allows_both_device_classes(self):
        for separate_device in (False, True):
            with self.subTest(separate_device=separate_device):
                self.setUp()
                with self.observations("boot/firmware", separate_device=separate_device) as seen:
                    transaction = self.m.install(self.layout, PROFILE)
                    self.assertTrue((self.root / RULE_REL).is_file())
                    self.assertIn("boot/firmware", seen["mount"])
                    self.assertIn("", seen["mount"])
                    self.m.restore(self.layout, transaction)
                self.assertFalse((self.root / RULE_REL).exists())

    def test_supported_linux_missing_mount_observation_refused(self):
        self.assert_refusal(None, unavailable="missing")

    def test_supported_linux_malformed_mount_observation_refused(self):
        self.assert_refusal(None, unavailable="malformed")

    def test_supported_linux_observation_error_refused(self):
        self.assert_refusal(None, unavailable="error")


if __name__ == "__main__":
    unittest.main()
