# Installer acceptance contract

## Scope

A standalone Python 3.11+ standard-library touchscreen installer for MPI3508 on Raspberry Pi 5 / Kali arm64 / Xorg-libinput. It configures ADS7846 boot parameters and a libinput InputClass. It never configures the display, autologin, terminals, keyboards, networking or SSH, and never reboots or restarts the desktop.

The explicit `pi5-kali-reference` profile describes one measured panel. Installing it does not establish physical accuracy on another panel.

## Public interface

`python3 -I mpi3508.py {preview,install,verify,restore}`. Profile selection is explicit for preview/install. Install/restore require root and confirmation; an explicit `--yes` is the noninteractive acknowledgement. Restore selects a transaction identifier reported by install, not an arbitrary path. No root/path/environment override is exposed through the CLI.

Preview performs no writes, emits the planned path-specific diff and profile caveat, and fails closed when prerequisites or configuration scope cannot be established. Install only writes after all preconditions, backups and journal preparation succeed. Report saved configuration separately from effective runtime state; installation cannot report runtime or physical acceptance.

The CLI gates Xorg persistence on independently observed effective ADS7846 DT and ABS X/Y bounds 200–3900. On a pristine or mismatched host, save only the boot change and report `boot-configured-reboot-required`; a user-controlled reboot and rerun are needed before saving the matrix. Do not equate saved boot text with loaded bounds. Preserve restore lineage across stages, or expose separate stage transactions with explicit reverse restore order. Internal fixture transactions may use an `include_xorg` selector; no bypass of the effective-bounds gate is exposed to CLI users.

The published command downloads a commit-pinned artifact without root privileges. Its elevated isolated Python verifier uses the module’s `VERIFICATION_BOOTSTRAP` source verbatim: arguments are artifact path, expected SHA256 and installer arguments. It reads a safe regular artifact once, validates that buffer’s digest and executes the same buffer with the artifact’s `__file__`, `__main__` and argument context. Missing, linked, truncated or mismatched artifacts fail before payload execution. The verifier has no network access or post-check pathname reopen. Its behavior is tested before implementation, and documentation is compiled from this source rather than maintaining a second verifier.

## Fixed paths

- `/boot/firmware/config.txt`
- `/etc/X11/xorg.conf.d/99-mpi3508-touch.conf`
- Root-owned journal/lock/backups under `/var/lib/mpi3508`

Only these target files may be modified. Unrelated content is preserved byte-for-byte. A separately mounted firmware filesystem is an explicit expected boundary. Links, unsafe parents, unexpected ownership, hardlinks, malformed manifests and concurrent drift must refuse rather than redirect privileged writes.

## Configuration planning

Support a simple, unambiguous top-level boot layout with no active includes or complex conditional touchscreen settings. Recognize overlay scope; preserve unrelated settings and line endings. Refuse duplicate ADS7846 overlays, unsupported touchscreen parameters, malformed sections and ambiguous transformations. Keep generated lines conservatively below the documented firmware limit. Do not use unsupported `keep_vref_on`. Profile coordinate bounds are X/Y 200–3900 and x-plate resistance 150 ohms; wiring is an explicit profile assumption, not autodetection.

The Xorg rule matches product `ADS7846 Touchscreen`, touchscreen status and driver `libinput`. Use a full nine-value CalibrationMatrix. Reject applicable competing evdev/calibration/nonidentity-CTM rules without deleting or replacing them. Generated code/configuration must not retain private hostnames, home paths, boot IDs, logs or raw contacts.

## Transaction

Validate every target and state path. Lock concurrent invocations. Create exclusive verified backups and a durable prepared journal before target mutation. Stage in the target directory; replace atomically only after rechecking preimages and identity, preserve metadata and verify readback. Roll back completed writes on subsequent failures without overwriting concurrent changes. Detect interrupted transactions on the next invocation. Preserve evidence and name manual recovery when rollback cannot safely complete. Restore prevalidates all current postimages and all backup identities/hashes before its first mutation. Restore an originally absent rule by removing only the owned verified regular file. No recursive deletion.

## Verification

Saved-file verification is independent of the planning function. Runtime checks identify devices by properties, not event numbers or PIDs, and distinguish unavailable/not-examined data from mismatch. Check available device-tree and ABS bounds, Xorg InputClass application, live libinput matrix and identity CTM. Do not print session secrets, full environments or terminal content. Physical accuracy always remains outside automatic verification.

## Test ownership and gates

An independent test-author writes tests and records meaningful RED before implementation, then freezes test-side hashes and makes a separate RED commit. Missing behavior is the intended failure; import, syntax and infrastructure errors do not count. A distinct doer implements production only and makes GREEN separately; they cannot edit tests, fixtures, helpers or test configuration. A distinct checker owns final acceptance and verifies frozen hashes at the delivery revision.

Cover clean/existing configuration, scope and line endings, profile integrity, conflicts, idempotence, unsupported environments, linked/unsafe paths, malformed state, concurrent drift, each transactional failure point, rollback, interrupted work and drift-safe restore. Exercise the real CLI and real filesystem transaction in disposable Linux in addition to pure tests. Synthetic fixtures test installer mechanics, not physical calibration. Document real-reference and authoritative-contract checks separately.

Before publication run compilation/build, full tests, lint, formatter check and secret/private-identifier checks including commit messages. CI Actions use full SHAs. Local hooks and CI run matching checks. Publish only a checked clean source tree. Public documentation provides a commit-pinned SHA256-verified installation command, validation limits, preview/restore and working Privacy/Terms links.
