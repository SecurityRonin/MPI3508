---
title: MPI3508 touch configuration
layout: default
permalink: /
---

# MPI3508 touch configuration

Touchscreen-only configuration for the MPI3508 reference panel on Raspberry Pi 5 / Kali arm64 / Xorg-libinput. The display must already work.

> **Release candidate.** Independent source-stage checks are green. Final delivery acceptance, the public download and Pages deployment remain pending. See [validation]({{ '/validation/' | relative_url }}) for the distinction between recorded panel observations, installer-mechanics tests and bounded native Linux checks.

## Before changing anything

- Keep a recovery route that does not depend on this touchscreen.
- Use Python 3.11+ and an existing Xorg/libinput installation. This tool installs no packages.
- Confirm that you intend to use the panel-specific `pi5-kali-reference` profile. Its fit is not a promise of accuracy on another unit.
- Read the preview. Unknown prerequisites, conflicting input rules or ambiguous boot scope are refusal conditions, not reasons to force the operation.

## Pinned download, preview and installation

Run this from a normal user terminal on the supported Pi after public distribution is verified. Review the preview and type `yes` to accept installation. The downloader refuses root; the elevated verifier executes only the exact pinned buffer. Confirmation retains interactive stdin.

```sh
artifact="$(python3 -I -c 'import os, sys, tempfile, urllib.request
if os.geteuid() == 0:
    sys.exit("Download refused: run without sudo or a root shell")
try:
    directory = tempfile.mkdtemp(prefix="mpi3508-")
    artifact = os.path.join(directory, "mpi3508.py")
    fd = os.open(artifact, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "wb") as output:
        with urllib.request.urlopen("https://raw.githubusercontent.com/SecurityRonin/MPI3508/107a14e28a6d5d5242310fba19f3077b4caece5f/mpi3508.py", timeout=30) as response:
            payload = response.read(2097153)
        if not 0 < len(payload) <= 2097152:
            raise ValueError("invalid artifact size")
        output.write(payload)
    print(artifact)
except Exception as error:
    sys.exit("Download refused: " + type(error).__name__)
')" &&
source_sha=3ffe690f5a9e77fab8cf4c1f8cb6d2939ed4890a52a0ae0b2a8d0d6906c51029 &&
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

A failed download, digest check or preview stops before installation. This command’s source SHA256 and verifier are compiled from the signed source commit, not from the current branch name. Public URL availability remains a publication gate.

In the same shell, the retained `artifact`, `source_sha` and `verifier` variables allow follow-up checks and restore without executing unchecked bytes:

```sh
python3 -I -c "$verifier" "$artifact" "$source_sha" preview --profile pi5-kali-reference
sudo python3 -I -c "$verifier" "$artifact" "$source_sha" install --profile pi5-kali-reference
python3 -I -c "$verifier" "$artifact" "$source_sha" verify
sudo python3 -I -c "$verifier" "$artifact" "$source_sha" restore --transaction ID
```

Replace `ID` with the reported transaction identifier. After reboot the shell variables are gone; rerun the pinned command to obtain and verify the same source. A declined installation leaves the variables available for verification or restore. The temporary download remains in its private directory until you remove it or the system clears temporary files.

## Preview, install, verify

Preview makes no writes and reports the proposed changes for each target path. Install requires root and confirmation; `--yes` explicitly acknowledges a noninteractive install. The transaction must have verified backups and a prepared journal before target mutation.

Only `/boot/firmware/config.txt` and `/etc/X11/xorg.conf.d/99-mpi3508-touch.conf` are configuration targets. State is kept under `/var/lib/mpi3508`. Unrelated content must be preserved; competing calibration rules are reported rather than removed.

Installation and verification answer different questions:

| Layer | What it answers |
|---|---|
| Saved files | Does the stored configuration match the selected profile? |
| Runtime | Do the available device-tree, ABS bounds and active Xorg/libinput properties match? Unavailable data must remain distinct from a mismatch. |
| Physical | Does a stylus land accurately across this panel? This requires a physical test and is outside automatic verification. |

### Boot-only stage, then Xorg

On a pristine or mismatched host, the first install saves only the boot change and reports `boot-configured-reboot-required`. The Xorg matrix waits until `bounds`, `dt_bounds` and `abs_bounds` are all `match`: independent observations of effective ADS7846 device-tree settings and ABS X/Y bounds must be 200–3900. A missing, unavailable or mismatched component cannot authorize matrix persistence.

Reboot yourself when convenient, then rerun the same install command. Saved boot text is not loaded state. Once the Xorg rule is persisted, restart the Xorg session yourself when ready. The installer performs neither interruption automatically, and unavailable runtime evidence is not permission to bypass the effective-bounds gate.

## Restore and recovery

Keep every transaction identifier printed by install. Restore stage transactions in reverse installation order: the newest Xorg stage first, then the earlier boot stage. Restore accepts an identifier, not an arbitrary backup path, and requires root and confirmation. Before changing any target, it checks that every current postimage and backup still has its recorded content hash, size, owner and mode. Inode and device numbers are not compared across sessions, because a firmware remount or reboot can change them. A later edit causes refusal, not a forced overwrite. Restore still requires the supported running environment, including exactly one existing Xorg display; independent recovery access is needed when those prerequisites are no longer available.

If the Xorg rule originally did not exist, restoration removes only the verified file owned by that transaction. Interrupted operations must be detected on the next invocation. When rollback cannot safely finish, retain the journal and backups and follow the reported manual recovery diagnosis. No recursive deletion is part of restoration.

[Validation]({{ '/validation/' | relative_url }}) · [Privacy Policy]({{ '/privacy/' | relative_url }}) · [Terms of Service]({{ '/terms/' | relative_url }}) · © 2026 Security Ronin Ltd
