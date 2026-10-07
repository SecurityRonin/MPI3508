# MPI3508

[![MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Sponsor](https://img.shields.io/badge/sponsor-h4x0r-pink.svg)](https://github.com/sponsors/h4x0r)

**Configure MPI3508 touch on Pi 5 / Kali / Xorg-libinput, with a preview and a drift-safe way back.**

> **Release candidate.** Independent source-stage checks are green; final delivery acceptance, the public download and GitHub Pages deployment remain pending. The profile comes from one measured panel. This installer has not been run on that Pi.

## Start with a preview

Run this in a normal user terminal on the supported Pi, **after the public-download gate is verified**. It downloads the pinned installer to an exclusive temporary file, verifies the bytes before preview, then verifies them again under isolated elevated Python before execution. Review the printed diff and type `yes` only if you accept it. The command does not redirect confirmation input.

```sh
artifact="$(python3 -I -c 'import os, sys, tempfile, urllib.request
if os.geteuid() == 0:
    sys.exit("Download refused: run without sudo or a root shell")
try:
    directory = tempfile.mkdtemp(prefix="mpi3508-")
    artifact = os.path.join(directory, "mpi3508.py")
    fd = os.open(artifact, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "wb") as output:
        with urllib.request.urlopen("https://raw.githubusercontent.com/SecurityRonin/MPI3508/a51deb06ef4f27f47d0b768241d8578dd818cc8d/mpi3508.py", timeout=30) as response:
            payload = response.read(2097153)
        if not 0 < len(payload) <= 2097152:
            raise ValueError("invalid artifact size")
        output.write(payload)
    print(artifact)
except Exception as error:
    sys.exit("Download refused: " + type(error).__name__)
')" &&
source_sha=d9e4c11dc6d0ecaa00a13ff15f9e5578b87c911d9b93d16c6a3f358d5a6d2401 &&
verifier='
import hashlib, os, re, stat, sys
try:
    if not sys.flags.isolated or len(sys.argv) < 3:
        raise ValueError("isolated Python, artifact and SHA256 required")
    artifact, expected = sys.argv[1:3]
    if re.fullmatch(r"[0-9a-fA-F]{64}", expected) is None:
        raise ValueError("invalid SHA256")
    fd = os.open(artifact, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, "rb") as source:
        before = os.fstat(source.fileno())
        if (not stat.S_ISREG(before.st_mode) or before.st_nlink != 1
                or before.st_mode & 0o022 or not 0 < before.st_size <= 2097152):
            raise ValueError("unsafe artifact")
        payload = source.read(2097153)
        after = os.fstat(source.fileno())
    if (len(payload) != before.st_size or
            (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns,
             before.st_ctime_ns, before.st_mode, before.st_nlink) !=
            (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns,
             after.st_ctime_ns, after.st_mode, after.st_nlink)):
        raise ValueError("artifact changed during read")
    if hashlib.sha256(payload).hexdigest() != expected.lower():
        raise ValueError("SHA256 mismatch")
except (OSError, ValueError) as error:
    message = str(error) if isinstance(error, ValueError) else type(error).__name__
    sys.exit("Artifact verification refused: " + message)
sys.argv = [artifact] + sys.argv[3:]
exec(compile(payload, artifact, "exec"),
     {"__file__": artifact, "__name__": "__main__", "__package__": None})
' &&
python3 -I -c "$verifier" "$artifact" "$source_sha" preview --profile pi5-kali-reference &&
sudo python3 -I -c "$verifier" "$artifact" "$source_sha" install --profile pi5-kali-reference
```

The verifier is the exact `VERIFICATION_BOOTSTRAP` literal from that source commit. It reads once, hashes and executes the same buffer, with no privileged download or post-check reopen. A download, verification or preview failure stops the command before installation. The temporary artifact remains available for the follow-up commands in the [guide](docs/index.md).

Python 3.11+ and the system’s existing Xorg/libinput stack are required. This tool does not install packages or configure the display. A working display and recovery access are prerequisites.

## What it changes

The installer contract limits configuration changes to:

- `/boot/firmware/config.txt`: ADS7846 touchscreen parameters.
- `/etc/X11/xorg.conf.d/99-mpi3508-touch.conf`: a libinput rule for `ADS7846 Touchscreen`.
- `/var/lib/mpi3508`: root-owned transaction records, lock and verified backups.

It does not change display settings, autologin, terminals, keyboards, networking or SSH. It never automatically reboots or restarts the desktop.

## Interface

The CLI options below are checked against this candidate’s `--help`. Direct-file examples assume an already verified local copy; use the verifier-based commands in the [guide](docs/index.md) for the downloaded artifact.

| Command | Purpose |
|---|---|
| `python3 -I mpi3508.py preview --profile pi5-kali-reference` | Inspect the proposed diff and panel caveat without writes. |
| `sudo python3 -I mpi3508.py install --profile pi5-kali-reference` | Require confirmation; back up and journal before changing configuration. |
| `python3 -I mpi3508.py verify` | Report saved-file checks separately from available runtime observations. |
| `sudo python3 -I mpi3508.py restore --transaction ID` | Replace `ID` with an installer-issued transaction identifier; restore only if current files and backups still match. |

Install and restore prompt for confirmation; `--yes` is explicit noninteractive acknowledgement. There is no arbitrary restore-path, filesystem-root or environment override in the public CLI.

Conflicting evdev/calibration rules, ambiguous boot sections or includes, unknown prerequisites, unsafe paths and concurrent edits must fail loudly. The installer does not delete competing rules to make itself work. Keep the transaction identifier reported by install. If files have changed since installation, restore refuses instead of erasing those edits; incomplete recovery preserves records and names the manual recovery needed.

### The boot boundary is deliberate

One install invocation is the entry point, but a pristine or mismatched host needs two stages. The installer saves only the boot change and reports `boot-configured-reboot-required`. Reboot yourself when ready, then rerun the same install command. It may persist the Xorg matrix only when all three reported fields, `bounds`, `dt_bounds` and `abs_bounds`, are `match`: effective ADS7846 device-tree settings and ABS X/Y bounds must be 200–3900. Missing or unavailable observations do not satisfy that gate. Saved boot text is not evidence that those bounds are loaded.

After the Xorg rule is saved, restart the Xorg session yourself when ready. Neither stage automatically reboots or restarts the desktop. Installation reports saved configuration, not runtime or physical acceptance. Keep every reported transaction identifier; where stages have separate transactions, restore the newest stage first, then the boot stage.

## Precision and compatibility

`pi5-kali-reference` is an explicit, panel-specific profile for Raspberry Pi 5 Model B, Kali arm64 and an already running Xorg/libinput session. It assumes SPI0 CE1, PENIRQ GPIO25, 50000 Hz, ADS7846 X/Y bounds of 200–3900 and x-plate resistance of 150 ohms. Wiring is an assumption to confirm, not autodetection. It is not an automatic calibration procedure or a display driver.

The reference record describes startup/property readback on one panel. No new physical edge test accompanies this release, and another panel may need its own fit. Automatic verification cannot measure stylus accuracy, edge reachability or nonlinear resistive-panel error. Wayland, other boards, other wiring and other display layouts are outside this profile’s scope.

[Validation and source limits](docs/validation.md) distinguish the reference record, installer tests and untested hardware behavior. The [usage guide](docs/index.md) explains the recovery workflow.

## Why libinput?

The upstream Xorg libinput driver documents `CalibrationMatrix` as nine space-separated values forming a 3×3 matrix. The pinned vendor MPI3508 presets instead use `Calibration` and `SwapAxes`, and their scripts include evdev installation paths. That vendor setup may work in its intended environment; this project targets the existing libinput stack rather than replacing it. Source links and scope are in [validation](docs/validation.md#sources-read).

---

[Privacy](https://securityronin.github.io/MPI3508/privacy) · [Terms](https://securityronin.github.io/MPI3508/terms)  
© Security Ronin Ltd
