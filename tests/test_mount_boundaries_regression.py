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
    def observations(
        self,
        boundary=None,
        *,
        separate_device=False,
        unavailable=None,
        change_after=None,
        mount_base=101,
        supported_linux=True,
    ):
        real_stat, real_fstat = os.stat, os.fstat
        root_info = real_stat(self.root)
        seen = {"stat": set(), "fstat": set(), "mount": set()}
        mount_calls = {}
        if boundary is not None:
            child = real_stat(self.root / boundary)
            parent = real_stat((self.root / boundary).parent)
            self.assertEqual(child.st_dev, parent.st_dev, "Synthetic input starts on one device")

        def entries(directory, prefix=""):
            with os.scandir(directory) as children:
                for child in children:
                    relative = prefix + child.name
                    info = child.stat(follow_symlinks=False)
                    yield relative, info
                    if stat.S_ISDIR(info.st_mode):
                        yield from entries(child.path, relative + "/")

        def relative_for(info):
            key = info.st_dev, info.st_ino
            if key == (root_info.st_dev, root_info.st_ino):
                return ""
            for relative, candidate in entries(self.root):
                if key == (candidate.st_dev, candidate.st_ino):
                    return relative
            return None

        def crossed(relative):
            return boundary is not None and (
                relative == boundary or relative.startswith(boundary + "/")
            )

        def device_observation(info, method):
            relative = relative_for(info)
            if relative is not None:
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
            self.assertTrue(
                stat.S_ISDIR(info.st_mode) or stat.S_ISREG(info.st_mode),
                "Observe only selected directory or regular-file descriptors",
            )
            relative = relative_for(info)
            self.assertIsNotNone(relative, "Descriptor must name a selected fixture entry")
            seen["mount"].add(relative)
            mount_calls[relative] = mount_calls.get(relative, 0) + 1
            if unavailable == "error":
                raise OSError("Synthetic mount observation unavailable")
            if unavailable == "missing":
                return None
            if unavailable == "malformed":
                return "not-a-mount-id"
            changed = change_after is None or mount_calls[relative] > change_after
            return mount_base + 1 if crossed(relative) and changed else mount_base

        with (
            patch.object(self.m.os, "stat", side_effect=observed_stat),
            patch.object(self.m.os, "fstat", side_effect=observed_fstat),
            patch.object(self.m, "mount_id", side_effect=observed_mount, create=True),
            patch.object(self.m.sys, "platform", "linux" if supported_linux else "darwin"),
            patch.object(
                self.m.platform, "system", return_value="Linux" if supported_linux else "Darwin"
            ),
        ):
            yield seen

    def assert_refusal(
        self, boundary, *, separate_device=False, unavailable=None, change_after=None
    ):
        before = self.snapshot()
        rule_existed = (self.root / RULE_REL).exists()
        with self.observations(
            boundary,
            separate_device=separate_device,
            unavailable=unavailable,
            change_after=change_after,
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
        self.assertEqual((self.root / RULE_REL).exists(), rule_existed)

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
                    self.assertIn(str(BOOT_REL), seen["mount"])
                    self.assertIn("", seen["mount"])
                    self.m.restore(self.layout, transaction)
                self.assertFalse((self.root / RULE_REL).exists())

    def test_supported_linux_missing_mount_observation_refused(self):
        self.assert_refusal(None, unavailable="missing")

    def test_supported_linux_malformed_mount_observation_refused(self):
        self.assert_refusal(None, unavailable="malformed")

    def test_supported_linux_observation_error_refused(self):
        self.assert_refusal(None, unavailable="error")

    def test_saved_observation_unavailable_is_distinct_from_mismatch(self):
        self.m.install(self.layout, PROFILE)
        before = self.snapshot()
        for unavailable in ("missing", "malformed", "error"):
            with self.subTest(unavailable=unavailable):
                with (
                    self.observations(unavailable=unavailable) as seen,
                    patch.object(
                        self.m, "plan_boot", side_effect=AssertionError("Planner is not an oracle")
                    ),
                    patch.object(
                        self.m,
                        "render_xorg",
                        side_effect=AssertionError("Renderer is not an oracle"),
                    ),
                ):
                    report = self.m.verify_saved(self.layout, PROFILE)
                    self.assertEqual(report["saved"], "unavailable")
                    self.assertEqual(report["runtime"], "not-examined")
                    self.assertEqual(report["physical"], "not-examined")
                    self.assertTrue(seen["mount"])
                self.assertEqual(self.snapshot(), before)

    def test_saved_forbidden_mount_is_mismatch(self):
        self.m.install(self.layout, PROFILE)
        before = self.snapshot()
        with self.observations("etc/X11/xorg.conf.d") as seen:
            report = self.m.verify_saved(self.layout, PROFILE)
            self.assertEqual(report["saved"], "mismatch")
            self.assertEqual(report["physical"], "not-examined")
            self.assertIn("etc/X11/xorg.conf.d", seen["mount"])
        self.assertEqual(self.snapshot(), before)

    def test_nonnegative_zero_mount_identity_is_valid(self):
        with self.observations(mount_base=0) as seen:
            transaction = self.m.install(self.layout, PROFILE)
            self.assertTrue((self.root / RULE_REL).is_file())
            self.assertIn("", seen["mount"])
            self.m.restore(self.layout, transaction)
        self.assertFalse((self.root / RULE_REL).exists())

    def test_unsupported_nonlinux_fixture_allows_missing_mount_observation(self):
        with self.observations(unavailable="missing", supported_linux=False):
            transaction = self.m.install(self.layout, PROFILE)
            self.assertTrue((self.root / RULE_REL).is_file())
            self.m.restore(self.layout, transaction)
        self.assertFalse((self.root / RULE_REL).exists())

    def test_regular_target_file_mounts_refused(self):
        for boundary in (str(BOOT_REL), str(RULE_REL)):
            with self.subTest(boundary=boundary):
                self.setUp()
                self.m.install(self.layout, PROFILE)
                self.assert_refusal(boundary)

    def test_regular_lock_file_mount_refused(self):
        lock = self.root / STATE_REL / "lock"
        lock.write_bytes(b"")
        lock.chmod(0o600)
        self.assert_refusal(str(STATE_REL / "lock"))

    def test_cached_same_inode_directory_overmount_refused(self):
        self.assert_refusal("etc/X11/xorg.conf.d", change_after=1)

    def test_cached_same_inode_lock_overmount_refused(self):
        lock = self.root / STATE_REL / "lock"
        lock.write_bytes(b"")
        lock.chmod(0o600)
        self.assert_refusal(str(STATE_REL / "lock"), change_after=1)


if __name__ == "__main__":
    unittest.main()
