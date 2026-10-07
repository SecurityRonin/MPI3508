---
title: Validation and limits
layout: default
permalink: /validation/
---

# Validation and limits

## Current evidence boundary

The production candidate is signed commit `a51deb06ef4f27f47d0b768241d8578dd818cc8d`, installer SHA256 `d9e4c11dc6d0ecaa00a13ff15f9e5578b87c911d9b93d16c6a3f358d5a6d2401`. Independent source-stage checks recorded on 7 October 2026 passed compilation, lint, formatting and bounded public-tree/commit-message scans. The full suite discovered 106 methods: 105 executed with one platform skip on Darwin, and 105 executed with the complementary platform skip in disposable Linux arm64. Both platforms also passed the optimized unsafe-path and bootstrap subsets, each containing nine methods. The 19 saved-parameter and mount regressions passed separately.

These checks concern the exact source candidate, not final delivery acceptance. Final independent delivery review, an actual Jekyll build and rendered HTML readback, public-download availability, remote CI execution and deployed Pages links remain pending.

The new public installer has not been run on the reference Pi. The inherited reference record concerns a manually configured panel, not an installation by this program.

| Evidence | What it supports | Limit |
|---|---|---|
| `[QUOTED]` Scrubbed reference record, supplied 6 October 2026 | A panel-specific profile and recorded startup/property readback on one panel | Raw hardware observations were not independently repeated for this document. No fresh physical edge test. |
| `[OBSERVED]` Debian-published upstream libinput manual and pinned vendor source, read 6 October 2026 | The documented option format and the contents of those source revisions | A documented option or vendor preset does not establish a particular panel’s accuracy. |
| Synthetic installer tests (T3) | Configuration, refusal and transaction behavior in constructed fixtures | Revision-bound independent execution is recorded above; author-created fixtures are not an independent oracle for panel accuracy. |
| Native Linux path controls (T2) | Selected install/restore, unexpected-mount refusals and descriptor-alias/cache checks on real Linux filesystems | Chosen container scenarios, not a Pi installation or an arbitrary privileged dynamic-overmount test. |
| Source-contract C oracle (T2) | C structure layout, ioctl request values and decoding of chosen ABI bytes agree with the Python implementation | Compiled on Darwin against pinned Linux header fragments with synthetic values, not against a running Pi kernel. |

## Reference profile

The supplied profile is `pi5-kali-reference`: Raspberry Pi 5 / Kali arm64 / Xorg-libinput, ADS7846 X/Y bounds 200–3900, x-plate resistance 150 ohms and reference wiring assumptions. Its full nine-value matrix is:

```text
-0.002296031116191308 -0.9921051268461499 1.0030508935417717 -1.025727266567984 -0.012705460331736715 1.0049107831524058 0 0 1
```

These values are copied from the supplied scrubbed profile, not a new fit or an independent measurement. The profile uses libinput’s inclusive ABS endpoint normalization. Recorded property persistence is different from physical accuracy. No pixel-error bound, edge-coverage result, accuracy percentage or cross-unit compatibility result is available in this publication record.

## What verification must distinguish

The acceptance contract separates:

1. **Saved-file verification:** an independent read of installed configuration, including equality of the complete parsed ADS7846 parameter set, not merely reuse of the planner’s output.
2. **Runtime observation:** available device-tree parameters, ABS bounds, Xorg rule application, live libinput matrix and identity Coordinate Transformation Matrix. Device selection uses identifying properties, not changing event numbers or process IDs.
3. **Physical acceptance:** stylus tests across the actual display, including edges. Automatic verification does not perform this.

Missing runtime access is “unavailable” or “not examined”, not a successful check and not proof of mismatch. Install success is a saved-state result only. Other hardware, wiring, Wayland and display geometries remain outside this reference profile.

## Installer test scope

The required independent suite covers configuration scope and line endings; explicit profiles; conflict and unsupported-environment refusals; linked/unsafe paths; malformed state; idempotence; concurrent drift; transactional failure points; rollback; interrupted work; and drift-safe restore. Real CLI/filesystem transactions must also be exercised in disposable Linux. Tests of synthetic files cannot establish behavior on a physical Pi.

The independent checker, not the implementation author, owns acceptance. Publication requires compilation, full tests, lint, formatting and secret/private-identifier checks at the delivery revision, including commit messages. A clean source tree and deployed documentation links are separate publication checks.

### Native Linux mount scope

The source observes opened descriptors and rechecks held handles against their current paths. Only the exact `/boot/firmware` directory may introduce a separately mounted filesystem; that exception does not extend to its target file. An unavailable mount observation remains distinct from an observed unexpected boundary.

Selected native Linux controls (T2) completed install/restore on an ordinary tree and with `/boot/firmware` backed by a bind mount or tmpfs. Unexpected directory, target-file and lock-file mounts refused before transactional checkpoints, with the examined fixture and host manifests unchanged. Separate cache controls used actual alias descriptors. Successful restoration recovered recorded target bytes and metadata, while atomic replacement changed inode identity and durable transaction state remained.

The native descriptor reader agreed with independently read Linux fdinfo/mountinfo. Constructed grammar and read-error controls are T3. Container processes had no effective or bounding capabilities and `NoNewPrivs` was set. These are bounded observations: arbitrary concurrent mount manipulation by a process with `CAP_SYS_ADMIN` was not examined. Descriptor-alias/cache controls are not a dynamic-overmount test, and neither establishes runtime touch accuracy on a Pi.

## Sources read

The Xorg libinput manual’s `CalibrationMatrix` entry specifies nine space-separated floating-point values forming a 3×3 matrix. The Debian-published packaged upstream manual and the libinput project’s configuration documentation were read on 6 October 2026:

- Debian’s `libinput(4)` manual, Configuration Details, `CalibrationMatrix`: <https://manpages.debian.org/testing/xserver-xorg-input-libinput/libinput.4.en.html>
- libinput configuration documentation, Calibration section: <https://wayland.freedesktop.org/libinput/doc/latest/configuration.html#calibration>

The upstream GitLab raw-manual endpoint returned a bot challenge during this documentation check; the option claim above is supported by the packaged manual actually read, not by that response.

The following pinned vendor scripts copy the MPI3508 calibration preset and include evdev installation logic. Their referenced presets contain `Calibration` set to `3945 233 3939 183` and `SwapAxes` set to `1`:

- goodtft MPI3508-show at `a36c00a55e11f0de3b4be0e66f0a2cec47076e23`: <https://raw.githubusercontent.com/goodtft/LCD-show/a36c00a55e11f0de3b4be0e66f0a2cec47076e23/MPI3508-show>
- goodtft MPI3508 preset at `a36c00a55e11f0de3b4be0e66f0a2cec47076e23`: <https://raw.githubusercontent.com/goodtft/LCD-show/a36c00a55e11f0de3b4be0e66f0a2cec47076e23/usr/99-calibration.conf-3508-0>
- lcdwiki MPI3508-show at `002cd5d0927c66c421e770245baf4777c207f3ae`: <https://raw.githubusercontent.com/lcdwiki/LCD-show-kali/002cd5d0927c66c421e770245baf4777c207f3ae/MPI3508-show>
- lcdwiki MPI3508 preset at `002cd5d0927c66c421e770245baf4777c207f3ae`: <https://raw.githubusercontent.com/lcdwiki/LCD-show-kali/002cd5d0927c66c421e770245baf4777c207f3ae/usr/99-calibration.conf-3508-0>

Those presets exist and may work with an appropriate evdev setup. Their source does not establish that they are universally wrong, that this libinput profile fits every MPI3508, or that either vendor tested this project’s target environment.

[Guide](https://securityronin.github.io/MPI3508/) · [Privacy](https://securityronin.github.io/MPI3508/privacy) · [Terms](https://securityronin.github.io/MPI3508/terms)  
© Security Ronin Ltd
