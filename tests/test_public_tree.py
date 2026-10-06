"""Positive and negative controls for the bounded public-source scanner."""

import unittest

from tests.check_public_tree import violations


class PublicTreeGateTests(unittest.TestCase):
    def test_scanner_flags_named_sensitive_classes_without_printing_values(self):
        controls = (
            ("private-key", "-----BEGIN " + "OPENSSH PRIVATE KEY-----"),
            ("github-token", "ghp_" + "A" * 36),
            ("aws-access-key", "AKIA" + "A" * 16),
            ("private-home-path", "/" + "Users/fictional-user/repo"),
            ("credential-assignment", 'api_key="' + "A" * 30 + '"'),
        )
        for category, value in controls:
            with self.subTest(category=category):
                self.assertIn((1, category), violations(value))

    def test_public_examples_and_fixed_system_paths_not_misclassified(self):
        content = (
            "/boot/firmware/config.txt\n"
            "/etc/X11/xorg.conf.d/99-mpi3508-touch.conf\n"
            "/var/lib/mpi3508\n"
            'api_key="example"\n'
            "https://github.com/SecurityRonin/MPI3508\n"
        )
        self.assertEqual(violations(content), [])


if __name__ == "__main__":
    unittest.main()
