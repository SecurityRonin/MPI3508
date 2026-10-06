# MPI3508 project instructions

Implement only the acceptance contract in ACCEPTANCE.md. Runtime is standalone Python 3.11+ standard library; no package installation, desktop/display/network changes or automatic restart/reboot.

Keep calibration panel-specific and separate saved-file, runtime and physical validation claims. Refuse unknown prerequisites, ambiguous boot scope, conflicting input rules and unsafe paths; do not guess.

Installer changes are Category 1 in Certified mode. Test-author, doer, checker and any fixer are distinct contexts. Acceptance tests must fail for the missing behavior before production implementation. RED then GREEN are separate commits. Freeze test-side hashes; doer/fixer may modify only production-side files. Independent checker owns PASS.

Use a feature branch, signed commits and file-based commit messages. End commit messages with:
Co-Authored-By: Claude Code <noreply@anthropic.com>

No private records or machine/session identifiers belong in this public tree. Evidence and critic files stay outside the repository. Never use a worktree unless explicitly requested. No recursive cleanup. Match local checks and CI; pin Actions to full SHAs. Do not push without compilation/build, full tests, lint, formatter and secret checks (including commit messages).
