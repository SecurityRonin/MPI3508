"""Synthetic filesystem mechanics fixtures, never a physical calibration oracle."""

import importlib.util
import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "mpi3508.py"
PROFILE = "pi5-kali-reference"
BOOT_REL = Path("boot/firmware/config.txt")
RULE_REL = Path("etc/X11/xorg.conf.d/99-mpi3508-touch.conf")
STATE_REL = Path("var/lib/mpi3508")
BOOT = b"# Synthetic fixture: preserve this comment\ndtparam=audio=on\n"


def installer(case):
    case.assertTrue(
        SCRIPT.is_file(),
        "Required standalone mpi3508.py installer behavior has not been delivered",
    )
    if "mpi3508_under_test" not in sys.modules:
        spec = importlib.util.spec_from_file_location("mpi3508_under_test", SCRIPT)
        case.assertIsNotNone(spec)
        case.assertIsNotNone(spec.loader)
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
    return sys.modules["mpi3508_under_test"]


def reference():
    return json.loads((ROOT / "tests/data/reference-profile.json").read_text(encoding="utf-8"))


def fixture(case, module, *, existing_rule=None):
    # Retained deliberately: the governed author run permits no recursive cleanup.
    root = Path(tempfile.mkdtemp(prefix="mpi3508-test-"))
    (root / BOOT_REL).parent.mkdir(parents=True)
    (root / RULE_REL).parent.mkdir(parents=True)
    (root / "var/lib").mkdir(parents=True)
    (root / BOOT_REL).write_bytes(BOOT)
    (root / BOOT_REL).chmod(0o640)
    if existing_rule is not None:
        (root / RULE_REL).write_bytes(existing_rule)
        (root / RULE_REL).chmod(0o640)
    return module.Layout(root=root, owner_uid=os.getuid()), root


def input_class(*, product="ADS7846 Touchscreen", driver="libinput", options=(), extra=()):
    lines = [
        'Section "InputClass"',
        '  Identifier "synthetic competing rule"',
        f'  MatchProduct "{product}"',
        '  MatchIsTouchscreen "on"',
        f'  Driver "{driver}"',
    ]
    lines.extend(extra)
    lines.extend(f'  Option "{key}" "{value}"' for key, value in options)
    lines.append("EndSection")
    return ("\n".join(lines) + "\n").encode()
