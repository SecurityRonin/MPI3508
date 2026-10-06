"""Local and CI checks use the same commands; zero discovered tests cannot pass."""

import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    sys.path.insert(0, str(ROOT))
    suite = unittest.defaultTestLoader.discover(str(ROOT / "tests"), top_level_dir=str(ROOT))
    count = suite.countTestCases()
    if count < 1:
        print("REFUSED: no acceptance tests discovered", file=sys.stderr)
        return 1
    print(f"Acceptance discovery: {count} tests", flush=True)
    version = subprocess.run(["ruff", "--version"], capture_output=True, text=True, check=False)
    if version.returncode or version.stdout.strip() != "ruff 0.15.1":
        print("REFUSED: checks require ruff 0.15.1", file=sys.stderr)
        return 1
    commands = [
        [sys.executable, "-m", "py_compile", "mpi3508.py"],
        [sys.executable, "-m", "compileall", "-q", "tests"],
        ["ruff", "check", "."],
        ["ruff", "format", "--check", "."],
        [sys.executable, "tests/check_public_tree.py"],
        [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-v"],
        [sys.executable, "-O", "-m", "unittest", "tests.test_transactions.UnsafePathTests", "-v"],
        [sys.executable, "-O", "-m", "unittest", "tests.test_bootstrap.BootstrapTests", "-v"],
    ]
    for command in commands:
        print("CHECK:", " ".join(command), flush=True)
        result = subprocess.run(command, cwd=ROOT, timeout=120, check=False)
        if result.returncode:
            return result.returncode
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, subprocess.TimeoutExpired) as error:
        print(f"Check unavailable: {type(error).__name__}", file=sys.stderr)
        raise SystemExit(2) from None
