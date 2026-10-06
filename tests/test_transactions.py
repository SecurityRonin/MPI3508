"""Real filesystem transaction tests using synthetic layouts, never host system paths."""

import json
import os
import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

from tests.helpers import (
    BOOT,
    BOOT_REL,
    PROFILE,
    ROOT,
    RULE_REL,
    STATE_REL,
    fixture,
    input_class,
    installer,
)


class TransactionTests(unittest.TestCase):
    def setUp(self):
        self.m = installer(self)
        self.layout, self.root = fixture(self, self.m)
        self.boot = self.root / BOOT_REL
        self.rule = self.root / RULE_REL
        self.state = self.root / STATE_REL

    def assert_original(self):
        self.assertEqual(self.boot.read_bytes(), BOOT)
        self.assertFalse(self.rule.exists())

    def journals(self):
        return sorted(self.state.rglob("*.json"))

    def installed(self):
        transaction = self.m.install(self.layout, PROFILE)
        self.assertIsInstance(transaction, str)
        self.assertRegex(transaction, r"\A[A-Za-z0-9][A-Za-z0-9_-]{0,127}\Z")
        self.assertEqual(self.boot.read_bytes(), self.m.plan_boot(BOOT, PROFILE))
        self.assertEqual(self.rule.read_bytes(), self.m.render_xorg(PROFILE))
        return transaction

    def test_boot_only_stage_never_creates_xorg_rule_and_restores(self):
        transaction = self.m.install(self.layout, PROFILE, include_xorg=False)
        self.assertIsInstance(transaction, str)
        self.assertEqual(self.boot.read_bytes(), self.m.plan_boot(BOOT, PROFILE))
        self.assertFalse(self.rule.exists())
        self.m.restore(self.layout, transaction)
        self.assert_original()

    def test_boot_only_stage_is_idempotent(self):
        self.m.install(self.layout, PROFILE, include_xorg=False)
        before = (self.boot.stat().st_ino, self.boot.read_bytes())
        self.m.install(self.layout, PROFILE, include_xorg=False)
        self.assertEqual((self.boot.stat().st_ino, self.boot.read_bytes()), before)
        self.assertFalse(self.rule.exists())

    def test_staged_restore_retains_original_boot_lineage(self):
        boot_transaction = self.m.install(self.layout, PROFILE, include_xorg=False)
        configured_boot = self.boot.read_bytes()
        touch_transaction = self.m.install(self.layout, PROFILE, include_xorg=True)
        self.assertEqual(self.rule.read_bytes(), self.m.render_xorg(PROFILE))
        self.assertEqual(self.boot.read_bytes(), configured_boot)
        self.m.restore(self.layout, touch_transaction)
        if touch_transaction != boot_transaction:
            self.assertEqual(self.boot.read_bytes(), configured_boot)
            self.assertFalse(self.rule.exists())
            self.m.restore(self.layout, boot_transaction)
        self.assert_original()

    def test_install_changes_only_targets_and_keeps_metadata(self):
        unrelated = self.root / "etc/untouched.conf"
        unrelated.write_bytes(b"unique unrelated content\n")
        original_stat = self.boot.stat()
        self.installed()
        after = self.boot.stat()
        self.assertEqual(after.st_mode & 0o777, original_stat.st_mode & 0o777)
        self.assertEqual((after.st_uid, after.st_gid), (original_stat.st_uid, original_stat.st_gid))
        self.assertEqual(unrelated.read_bytes(), b"unique unrelated content\n")
        self.assertEqual(self.rule.stat().st_uid, os.getuid())
        self.assertFalse(self.rule.stat().st_mode & 0o022)

    def test_prepared_checkpoint_has_journal_and_preimage_backups_before_mutation(self):
        observed = []

        def checkpoint(stage, path):
            if stage != "prepared":
                return
            observed.append(stage)
            self.assert_original()
            journals = self.journals()
            self.assertTrue(journals, "Prepared journal missing before target write")
            for journal in journals:
                json.loads(journal.read_text())
            copies = [
                p
                for p in self.state.rglob("*")
                if p.is_file() and p.suffix != ".json" and p.read_bytes() == BOOT
            ]
            self.assertTrue(copies, "Exclusive preimage backup missing at prepared point")
            for backup in copies:
                self.assertEqual(backup.stat().st_nlink, 1)
                self.assertFalse(backup.stat().st_mode & 0o022)

        self.m.install(self.layout, PROFILE, checkpoint=checkpoint)
        self.assertEqual(observed, ["prepared"])

    def test_second_install_is_idempotent_without_replacing_targets(self):
        self.installed()
        before = [(p.stat().st_ino, p.read_bytes()) for p in (self.boot, self.rule)]
        self.m.install(self.layout, PROFILE)
        after = [(p.stat().st_ino, p.read_bytes()) for p in (self.boot, self.rule)]
        self.assertEqual(after, before)

    def test_restore_originally_absent_rule(self):
        transaction = self.installed()
        self.m.restore(self.layout, transaction)
        self.assert_original()
        self.assertEqual(self.boot.stat().st_mode & 0o777, 0o640)

    def test_restore_originally_existing_owned_rule(self):
        existing = self.m.render_xorg(PROFILE)
        self.rule.write_bytes(existing)
        self.rule.chmod(0o640)
        transaction = self.installed()
        self.m.restore(self.layout, transaction)
        self.assertEqual(self.boot.read_bytes(), BOOT)
        self.assertEqual(self.rule.read_bytes(), existing)
        self.assertEqual(self.rule.stat().st_mode & 0o777, 0o640)

    def test_each_checkpoint_failure_rolls_back_completed_writes(self):
        for failure_stage, target in (
            ("prepared", None),
            ("before_replace", BOOT_REL),
            ("after_replace", BOOT_REL),
            ("before_replace", RULE_REL),
            ("after_replace", RULE_REL),
            ("before_commit", None),
        ):
            with self.subTest(stage=failure_stage, target=target):
                layout, root = fixture(self, self.m)
                fired = []

                def checkpoint(
                    stage, path, failure_stage=failure_stage, target=target, root=root, fired=fired
                ):
                    if stage == failure_stage and (target is None or path == root / target):
                        fired.append(stage)
                        raise OSError("synthetic injected transaction failure")

                with self.assertRaises((self.m.InstallerError, OSError)):
                    self.m.install(layout, PROFILE, checkpoint=checkpoint)
                self.assertEqual(
                    fired, [failure_stage], "Failure injection did not reach real path"
                )
                self.assertEqual((root / BOOT_REL).read_bytes(), BOOT)
                self.assertFalse((root / RULE_REL).exists())

    def test_backup_or_journal_write_failure_prevents_target_mutation(self):
        real_fsync = os.fsync
        fired = []

        def fail_first_fsync(fd):
            if not fired:
                fired.append(fd)
                raise OSError("synthetic durability failure")
            return real_fsync(fd)

        with patch.object(self.m.os, "fsync", side_effect=fail_first_fsync):
            with self.assertRaises((self.m.InstallerError, OSError)):
                self.m.install(self.layout, PROFILE)
        self.assertTrue(fired, "Durability failure did not exercise fsync")
        self.assert_original()

    def test_readback_corruption_is_detected_and_never_reported_committed(self):
        fired = []

        def checkpoint(stage, path):
            if stage == "after_replace" and path == self.boot:
                fired.append(stage)
                self.boot.write_bytes(b"synthetic corrupt postimage\n")

        with self.assertRaisesRegex(
            self.m.InstallerError, "(?i)readback|drift|recover|changed|hash"
        ):
            self.m.install(self.layout, PROFILE, checkpoint=checkpoint)
        self.assertEqual(fired, ["after_replace"])
        self.assertFalse(self.rule.exists())

    def test_drift_before_first_replacement_not_overwritten(self):
        drift = b"external edit before replacement\n"
        fired = []

        def checkpoint(stage, path):
            if stage == "before_replace" and path == self.boot:
                fired.append(stage)
                self.boot.write_bytes(drift)

        with self.assertRaisesRegex(self.m.InstallerError, "(?i)drift|changed|preimage|identity"):
            self.m.install(self.layout, PROFILE, checkpoint=checkpoint)
        self.assertEqual(fired, ["before_replace"])
        self.assertEqual(self.boot.read_bytes(), drift)
        self.assertFalse(self.rule.exists())

    def test_concurrent_inode_replacement_with_identical_bytes_is_refused(self):
        fired = []

        def checkpoint(stage, path):
            if stage == "before_replace" and path == self.boot:
                replacement = self.boot.with_name("external-replacement")
                replacement.write_bytes(BOOT)
                replacement.chmod(0o640)
                replacement.replace(self.boot)
                fired.append(stage)

        with self.assertRaisesRegex(self.m.InstallerError, "(?i)identity|changed|drift|inode"):
            self.m.install(self.layout, PROFILE, checkpoint=checkpoint)
        self.assertEqual(fired, ["before_replace"])
        self.assert_original()

    def test_rollback_preserves_concurrent_edit_and_names_manual_recovery(self):
        drift = b"external edit after successful first replacement\n"
        fired = []

        def checkpoint(stage, path):
            if stage == "before_replace" and path == self.rule:
                self.boot.write_bytes(drift)
                fired.append(stage)
                raise OSError("synthetic second-target failure")

        with self.assertRaisesRegex(self.m.InstallerError, "(?i)manual.*recover|recover.*manual"):
            self.m.install(self.layout, PROFILE, checkpoint=checkpoint)
        self.assertEqual(fired, ["before_replace"])
        self.assertEqual(self.boot.read_bytes(), drift)
        self.assertTrue(self.journals(), "Unsafe rollback must retain recovery evidence")
        self.assertFalse(self.rule.exists())

    def test_concurrent_install_lock_refuses_without_deadlocking(self):
        failures = []

        def checkpoint(stage, path):
            if stage == "prepared":
                try:
                    self.m.install(self.layout, PROFILE)
                except self.m.InstallerError as exc:
                    failures.append(str(exc))
                else:
                    self.fail("Nested transaction escaped exclusive lock")

        self.m.install(self.layout, PROFILE, checkpoint=checkpoint)
        self.assertEqual(len(failures), 1)
        self.assertRegex(failures[0], "(?i)lock|concurrent|busy")

    def test_interrupted_transaction_is_detected_on_next_install(self):
        result = subprocess.run(
            [sys.executable, str(ROOT / "tests/crash_worker.py"), str(self.root)],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        self.assertEqual(result.returncode, 73, result.stderr)
        self.assertNotEqual(self.boot.read_bytes(), BOOT, "Crash must follow an actual first write")
        self.assertTrue(self.journals())
        with self.assertRaisesRegex(
            self.m.InstallerError, "(?i)interrupt|prepared|recover|incomplete"
        ):
            self.m.install(self.layout, PROFILE)

    def test_restore_prevalidates_all_targets_before_first_write(self):
        transaction = self.installed()
        post_boot = self.boot.read_bytes()
        self.rule.write_bytes(b"external rule change\n")
        with self.assertRaisesRegex(self.m.InstallerError, "(?i)drift|changed|postimage|hash"):
            self.m.restore(self.layout, transaction)
        self.assertEqual(self.boot.read_bytes(), post_boot)
        self.assertEqual(self.rule.read_bytes(), b"external rule change\n")

    def test_restore_refuses_corrupt_backup_before_first_write(self):
        transaction = self.installed()
        post = (self.boot.read_bytes(), self.rule.read_bytes())
        backups = [
            p
            for p in self.state.rglob("*")
            if p.is_file() and p.suffix != ".json" and p.read_bytes() == BOOT
        ]
        self.assertTrue(backups, "No independently recognizable boot preimage backup")
        backups[0].write_bytes(b"corrupt backup\n")
        with self.assertRaisesRegex(self.m.InstallerError, "(?i)backup|hash"):
            self.m.restore(self.layout, transaction)
        self.assertEqual((self.boot.read_bytes(), self.rule.read_bytes()), post)

    def test_restore_refuses_backup_hardlink_before_first_write(self):
        transaction = self.installed()
        post = (self.boot.read_bytes(), self.rule.read_bytes())
        backups = [
            p
            for p in self.state.rglob("*")
            if p.is_file() and p.suffix != ".json" and p.read_bytes() == BOOT
        ]
        self.assertTrue(backups)
        os.link(backups[0], self.root / "backup-alias")
        with self.assertRaisesRegex(self.m.InstallerError, "(?i)link|identity|backup"):
            self.m.restore(self.layout, transaction)
        self.assertEqual((self.boot.read_bytes(), self.rule.read_bytes()), post)

    def test_restore_refuses_malformed_and_wrong_schema_journals(self):
        for malformed in (b"{", b"{}", b"[]", b'{"status":"committed"}'):
            with self.subTest(malformed=malformed):
                layout, root = fixture(self, self.m)
                transaction = self.m.install(layout, PROFILE)
                post = ((root / BOOT_REL).read_bytes(), (root / RULE_REL).read_bytes())
                journals = sorted((root / STATE_REL).rglob("*.json"))
                self.assertEqual(len(journals), 1, "Exactly one transaction journal expected")
                journals[0].write_bytes(malformed)
                with self.assertRaisesRegex(
                    self.m.InstallerError, "(?i)journal|manifest|schema|state"
                ):
                    self.m.restore(layout, transaction)
                self.assertEqual(
                    ((root / BOOT_REL).read_bytes(), (root / RULE_REL).read_bytes()), post
                )

    def test_restore_refuses_missing_originally_absent_postimage(self):
        transaction = self.installed()
        self.rule.unlink()
        post_boot = self.boot.read_bytes()
        with self.assertRaises(self.m.InstallerError):
            self.m.restore(self.layout, transaction)
        self.assertEqual(self.boot.read_bytes(), post_boot)

    def test_restore_transaction_selector_cannot_escape_state(self):
        self.installed()
        for transaction in ("../escape", "/absolute", "", "a/b", ".", "..", "a\x00b"):
            with self.subTest(transaction=transaction):
                with self.assertRaises(self.m.InstallerError):
                    self.m.restore(self.layout, transaction)

    def test_restore_each_failure_rolls_back_to_installed_postimages(self):
        for failure_stage, target in (
            ("before_replace", BOOT_REL),
            ("after_replace", BOOT_REL),
            ("before_replace", RULE_REL),
            ("after_replace", RULE_REL),
            ("before_commit", None),
        ):
            with self.subTest(stage=failure_stage, target=target):
                layout, root = fixture(self, self.m)
                transaction = self.m.install(layout, PROFILE)
                post = ((root / BOOT_REL).read_bytes(), (root / RULE_REL).read_bytes())
                fired = []

                def checkpoint(
                    stage, path, failure_stage=failure_stage, target=target, root=root, fired=fired
                ):
                    if stage == failure_stage and (target is None or path == root / target):
                        fired.append(stage)
                        raise OSError("synthetic restore failure")

                with self.assertRaises((self.m.InstallerError, OSError)):
                    self.m.restore(layout, transaction, checkpoint=checkpoint)
                self.assertEqual(fired, [failure_stage])
                self.assertEqual(
                    ((root / BOOT_REL).read_bytes(), (root / RULE_REL).read_bytes()), post
                )


class UnsafePathTests(unittest.TestCase):
    def setUp(self):
        self.m = installer(self)
        self.layout, self.root = fixture(self, self.m)
        self.boot = self.root / BOOT_REL
        self.rule = self.root / RULE_REL

    def test_missing_boot_file_refused(self):
        self.boot.unlink()
        with self.assertRaisesRegex(self.m.InstallerError, "config.txt|boot"):
            self.m.install(self.layout, PROFILE)
        self.assertFalse(self.rule.exists())

    def test_symlink_target_not_followed(self):
        outside = self.root / "outside"
        outside.write_bytes(b"outside sentinel")
        self.boot.unlink()
        self.boot.symlink_to(outside)
        with self.assertRaisesRegex(self.m.InstallerError, "(?i)link|unsafe"):
            self.m.install(self.layout, PROFILE)
        self.assertEqual(outside.read_bytes(), b"outside sentinel")
        self.assertFalse(self.rule.exists())

    def test_absent_rule_symlink_refused(self):
        outside = self.root / "outside"
        outside.write_bytes(b"outside sentinel")
        self.rule.symlink_to(outside)
        with self.assertRaisesRegex(self.m.InstallerError, "(?i)link|unsafe"):
            self.m.install(self.layout, PROFILE)
        self.assertEqual(outside.read_bytes(), b"outside sentinel")
        self.assertEqual(self.boot.read_bytes(), BOOT)

    def test_symlink_parent_not_followed(self):
        outside = self.root / "outside-dir"
        outside.mkdir()
        (outside / "sentinel").write_bytes(b"outside sentinel")
        self.rule.parent.rmdir()
        self.rule.parent.symlink_to(outside, target_is_directory=True)
        with self.assertRaisesRegex(self.m.InstallerError, "(?i)link|unsafe"):
            self.m.install(self.layout, PROFILE)
        self.assertEqual((outside / "sentinel").read_bytes(), b"outside sentinel")
        self.assertFalse((outside / self.rule.name).exists())
        self.assertEqual(self.boot.read_bytes(), BOOT)

    def test_hardlinked_target_refused(self):
        alias = self.root / "alias"
        os.link(self.boot, alias)
        with self.assertRaisesRegex(self.m.InstallerError, "(?i)link"):
            self.m.install(self.layout, PROFILE)
        self.assertEqual(alias.read_bytes(), BOOT)
        self.assertFalse(self.rule.exists())

    def test_unsafe_target_or_parent_mode_refused(self):
        for relative in (BOOT_REL, BOOT_REL.parent, RULE_REL.parent, Path("var/lib")):
            with self.subTest(relative=relative):
                layout, root = fixture(self, self.m)
                (root / relative).chmod(0o777)
                with self.assertRaisesRegex(
                    self.m.InstallerError, "(?i)writ|mode|permission|unsafe"
                ):
                    self.m.install(layout, PROFILE)
                self.assertEqual((root / BOOT_REL).read_bytes(), BOOT)
                self.assertFalse((root / RULE_REL).exists())

    def test_unexpected_owner_refused(self):
        layout = self.m.Layout(root=self.root, owner_uid=os.getuid() + 1)
        with self.assertRaisesRegex(self.m.InstallerError, "(?i)owner|uid"):
            self.m.install(layout, PROFILE)
        self.assertEqual(self.boot.read_bytes(), BOOT)
        self.assertFalse(self.rule.exists())

    def test_symlink_state_directory_refused(self):
        outside = self.root / "outside-state"
        outside.mkdir()
        (self.root / STATE_REL).symlink_to(outside, target_is_directory=True)
        with self.assertRaisesRegex(self.m.InstallerError, "(?i)link|unsafe"):
            self.m.install(self.layout, PROFILE)
        self.assertEqual(list(outside.iterdir()), [])
        self.assertEqual(self.boot.read_bytes(), BOOT)

    def test_competing_rule_preflight_leaves_targets_unchanged(self):
        competitor = self.rule.parent / "20-legacy.conf"
        competitor.write_bytes(input_class(driver="evdev"))
        before = competitor.read_bytes()
        with self.assertRaisesRegex(self.m.InstallerError, "20-legacy.conf"):
            self.m.install(self.layout, PROFILE)
        self.assertEqual(competitor.read_bytes(), before)
        self.assertEqual(self.boot.read_bytes(), BOOT)
        self.assertFalse(self.rule.exists())


if __name__ == "__main__":
    unittest.main()
