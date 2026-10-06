"""Isolated crash injection after an actual target write, in a supplied test fixture."""

import importlib.util
import os
import sys
from pathlib import Path


def main():
    root = Path(sys.argv[1])
    script = Path(__file__).resolve().parents[1] / "mpi3508.py"
    spec = importlib.util.spec_from_file_location("mpi3508_crash_test", script)
    if spec is None or spec.loader is None:
        raise RuntimeError("Cannot load existing installer for crash test")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)

    def checkpoint(stage, path):
        if stage == "after_replace" and path == root / "boot/firmware/config.txt":
            os._exit(73)

    module.install(
        module.Layout(root=root, owner_uid=os.getuid()),
        "pi5-kali-reference",
        checkpoint=checkpoint,
    )
    raise RuntimeError("Crash checkpoint did not fire")


if __name__ == "__main__":
    main()
