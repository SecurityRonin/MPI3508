"""Fail-closed public-tree checks for credential signatures and private path identifiers.

This bounded scanner is not an exhaustive secret-detection claim. It covers its named
signatures and public-path policy; independent publication review remains required.
"""

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SIGNATURES = {
    "private-key": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----"),
    "github-token": re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}\b|\bgithub_pat_[A-Za-z0-9_]{30,}\b"),
    "aws-access-key": re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b"),
    "private-home-path": re.compile(r"/(?:Users|home)/[A-Za-z0-9_.-]+/"),
    "credential-assignment": re.compile(
        r"""(?i)(?:api[_-]?key|access[_-]?token|password|secret)\s*[:=]\s*["']"""
        r"""[A-Za-z0-9+/=_-]{24,}["']"""
    ),
}


def violations(content):
    findings = []
    for category, pattern in SIGNATURES.items():
        for match in pattern.finditer(content):
            findings.append((content.count("\n", 0, match.start()) + 1, category))
    return findings


def git_output(*args):
    result = subprocess.run(["git", *args], cwd=ROOT, capture_output=True, check=False)
    if result.returncode:
        raise RuntimeError("Git inventory failed; public-tree scan cannot certify its scope")
    return result.stdout


def main():
    paths = git_output("ls-files", "--cached", "--others", "--exclude-standard", "-z").split(b"\0")
    findings = []
    examined = 0
    for value in sorted(set(paths)):
        if not value:
            continue
        relative = value.decode("utf-8", errors="strict")
        path = ROOT / relative
        if not path.is_file() or path.is_symlink():
            continue
        raw = path.read_bytes()
        if b"\0" in raw:
            continue
        try:
            content = raw.decode("utf-8")
        except UnicodeDecodeError:
            continue
        examined += 1
        findings.extend((relative, line, category) for line, category in violations(content))
    if examined == 0:
        raise RuntimeError("Empty public-tree scan is not a successful secret check")
    revisions = git_output("rev-list", "--all").splitlines()
    for revision in revisions:
        message = git_output("show", "-s", "--format=%B", revision.decode()).decode("utf-8")
        findings.extend(
            ("commit:" + revision.decode(), line, category)
            for line, category in violations(message)
        )
    for path, line, category in findings:
        print(f"REFUSED {path}:{line} category={category}", file=sys.stderr)
    print(
        f"Scanned {examined} UTF-8 files and {len(revisions)} commit messages; "
        "bounded signatures only"
    )
    return 1 if findings else 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, RuntimeError, UnicodeError) as error:
        print(f"Public-tree scan unavailable: {type(error).__name__}", file=sys.stderr)
        raise SystemExit(2) from None
