"""Later-session lineage checks across a firmware remount, using synthetic layouts only.

A vfat firmware filesystem assigns inode numbers when it is mounted, and device numbers
are not guaranteed across reboot. Stage 2 and restore run in a later session, so they
must accept unchanged bytes, owner and mode at a new inode or device, while still
refusing genuine content, mode or owner drift.
"""

import os
import stat
import unittest
from contextlib import contextmanager
from unittest.mock import patch

from tests.helpers import BOOT, BOOT_REL, PROFILE, RULE_REL, fixture, installer

STAT_SEQUENCE = ("st_mode", "st_ino", "st_dev", "st_nlink", "st_uid", "st_gid", "st_size")


def remount(path, *, raw=None, mode=None, gid=None):
    """Re-create a file at a new inode, as a remount does, optionally with drift."""
    before = path.stat()
    replacement = path.with_name(".synthetic-remount-" + path.name)
    replacement.write_bytes(path.read_bytes() if raw is None else raw)
    os.chown(replacement, -1, before.st_gid if gid is None else gid)
    os.chmod(replacement, stat.S_IMODE(before.st_mode) if mode is None else mode)
    os.replace(replacement, path)
    after = path.stat()
    if after.st_ino == before.st_ino:
        raise AssertionError("Synthetic remount did not produce a new inode")
    return after


@contextmanager
def renumbered_device(probe, offset=0x1000):
    """Report every fixture file on a different device number, as after a reboot."""
    device = os.stat(probe).st_dev
    real = {name: getattr(os, name) for name in ("stat", "fstat", "lstat")}

    def shifted(result):
        if result.st_dev != device:
            return result
        extra = {
            name: getattr(result, name)
            for name in dir(result)
            if name.startswith("st_") and name not in STAT_SEQUENCE
        }
        sequence = (*result[:2], result.st_dev + offset, *result[3:10])
        return os.stat_result(sequence, extra)

    def wrap(name):
        return lambda *args, **kwargs: shifted(real[name](*args, **kwargs))

    with (
        patch.object(os, "stat", wrap("stat")),
        patch.object(os, "fstat", wrap("fstat")),
        patch.object(os, "lstat", wrap("lstat")),
    ):
        if os.stat(probe).st_dev == device:
            raise AssertionError("Synthetic device renumbering was not applied")
        yield


class RemountIdentityTests(unittest.TestCase):
    def setUp(self):
        self.m = installer(self)
        self.layout, self.root = fixture(self, self.m)
        self.boot = self.root / BOOT_REL
        self.rule = self.root / RULE_REL

    def accepted(self, operation, *args, **kwargs):
        try:
            return operation(self.layout, *args, **kwargs)
        except self.m.InstallerError as error:
            self.fail(f"Later session refused an unchanged file contract: {error}")

    def stage_one(self):
        transaction = self.m.install(self.layout, PROFILE, include_xorg=False)
        self.assertEqual(self.boot.read_bytes(), self.m.plan_boot(BOOT, PROFILE))
        self.assertFalse(self.rule.exists())
        return transaction

    def test_stage_two_and_restore_accept_new_firmware_inode_with_same_contract(self):
        boot_transaction = self.stage_one()
        configured = self.boot.read_bytes()
        remount(self.boot)
        touch_transaction = self.accepted(self.m.install, PROFILE, include_xorg=True)
        self.assertEqual(self.boot.read_bytes(), configured)
        self.assertEqual(self.rule.read_bytes(), self.m.render_xorg(PROFILE))
        remount(self.boot)
        self.accepted(self.m.restore, touch_transaction)
        self.assertFalse(self.rule.exists())
        self.assertEqual(self.boot.read_bytes(), configured)
        if touch_transaction != boot_transaction:
            remount(self.boot)
            self.accepted(self.m.restore, boot_transaction)
        self.assertEqual(self.boot.read_bytes(), BOOT)

    def test_restore_accepts_new_firmware_inode_with_same_contract(self):
        transaction = self.stage_one()
        remount(self.boot)
        self.accepted(self.m.restore, transaction)
        self.assertEqual(self.boot.read_bytes(), BOOT)
        self.assertFalse(self.rule.exists())

    def test_stage_two_and_restore_accept_renumbered_device_with_same_contract(self):
        boot_transaction = self.stage_one()
        configured = self.boot.read_bytes()
        with renumbered_device(self.boot):
            touch_transaction = self.accepted(self.m.install, PROFILE, include_xorg=True)
            self.assertEqual(self.boot.read_bytes(), configured)
            self.assertEqual(self.rule.read_bytes(), self.m.render_xorg(PROFILE))
            self.accepted(self.m.restore, touch_transaction)
            if touch_transaction != boot_transaction:
                self.accepted(self.m.restore, boot_transaction)
        self.assertEqual(self.boot.read_bytes(), BOOT)
        self.assertFalse(self.rule.exists())

    def test_restore_accepts_renumbered_device_with_same_contract(self):
        transaction = self.stage_one()
        with renumbered_device(self.boot):
            self.accepted(self.m.restore, transaction)
        self.assertEqual(self.boot.read_bytes(), BOOT)
        self.assertFalse(self.rule.exists())

    def test_genuine_drift_at_new_inode_still_refuses_stage_two_and_restore(self):
        drifts = {
            "content": {"raw": self.m.plan_boot(BOOT, PROFILE) + b"# drift\n"},
            "mode": {"mode": 0o600},
        }
        alternative = [gid for gid in os.getgroups() if gid != os.getgid()]
        if alternative:
            drifts["group"] = {"gid": alternative[0]}
        for name, change in drifts.items():
            for operation in ("install", "restore"):
                with self.subTest(drift=name, operation=operation):
                    layout, root = fixture(self, self.m)
                    boot = root / BOOT_REL
                    transaction = self.m.install(layout, PROFILE, include_xorg=False)
                    remount(boot, **change)
                    tampered = (boot.read_bytes(), boot.stat())
                    with self.assertRaises(self.m.InstallerError):
                        if operation == "install":
                            self.m.install(layout, PROFILE, include_xorg=True)
                        else:
                            self.m.restore(layout, transaction)
                    after = boot.stat()
                    self.assertEqual(boot.read_bytes(), tampered[0])
                    self.assertEqual(
                        (after.st_ino, after.st_mode, after.st_gid),
                        (tampered[1].st_ino, tampered[1].st_mode, tampered[1].st_gid),
                    )
                    self.assertFalse((root / RULE_REL).exists())


if __name__ == "__main__":
    unittest.main()
