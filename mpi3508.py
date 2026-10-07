#!/usr/bin/env python3
"""Panel-specific ADS7846 configuration; Python 3.11+, standard library only.

Saved files, effective kernel/Xorg state and physical accuracy are separate claims.
Layout is an internal filesystem-test seam, never a command-line option.
"""

import argparse
import contextlib
import difflib
import fcntl
import hashlib
import json
import math
import os
import platform
import re
import shlex
import stat
import struct
import subprocess
import sys
import uuid
from dataclasses import dataclass
from pathlib import Path

PROFILES = {
    "pi5-kali-reference": {
        "matrix": (
            "-0.002296031116191308",
            "-0.9921051268461499",
            "1.0030508935417717",
            "-1.025727266567984",
            "-0.012705460331736715",
            "1.0049107831524058",
            "0",
            "0",
            "1",
        ),
        "x_min": 200,
        "x_max": 3900,
        "y_min": 200,
        "y_max": 3900,
        "x_plate_ohms": 150,
        "caveat": (
            "One measured panel: recorded startup/property readback only. "
            "No fresh physical edge acceptance; another panel may need its own fit."
        ),
        "wiring": (
            "Explicit wiring assumption: SPI0 CE1, PENIRQ GPIO25, 50000 Hz; "
            "this is not wiring autodetection. Confirm before installation."
        ),
    }
}
BOOT = "boot/firmware/config.txt"
RULE = "etc/X11/xorg.conf.d/99-mpi3508-touch.conf"
STATE = "var/lib/mpi3508"
TARGETS = (BOOT, RULE)
IDENTIFIER = "MPI3508 reference touchscreen"
IDENTITY = (1, 0, 0, 0, 1, 0, 0, 0, 1)
LIMIT = 2 * 1024 * 1024
MINIMUM_PYTHON = (3, 11)
ID_PATTERN = r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}"

# This exact source is used by the documentation generator and isolated verifier.
# Artifact ownership may belong to the downloading user. The caller pins its digest.
VERIFICATION_BOOTSTRAP = r"""
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
"""


class InstallerError(Exception):
    """An explicit refusal; no security decisions depend on Python assertions."""


class MountObservationError(OSError):
    """Mount evidence is unavailable, rather than an established forbidden boundary."""


def profile(name):
    if name not in PROFILES:
        raise InstallerError(f"Unknown profile: {name}")
    return PROFILES[name]


def text_content(raw):
    if b"\0" in raw or len(raw) > LIMIT:
        raise InstallerError("Invalid binary/NUL or oversized configuration")
    try:
        return raw.decode("utf-8")
    except UnicodeError:
        raise InstallerError("Invalid UTF-8 configuration") from None


def touch_values(name):
    p = profile(name)
    return {
        "xmin": str(p["x_min"]),
        "xmax": str(p["x_max"]),
        "ymin": str(p["y_min"]),
        "ymax": str(p["y_max"]),
        "xohms": str(p["x_plate_ohms"]),
        "penirq": "25",
        "speed": "50000",
        "cs": "1",
    }


TOUCH_PARAMETERS = {
    "cs",
    "speed",
    "penirq",
    "penirq_pull",
    "swapxy",
    "xmin",
    "xmax",
    "ymin",
    "ymax",
    "pmin",
    "pmax",
    "xohms",
}
BASE_PARAMETERS = {"audio", "spi", "i2c_arm", "i2c_vc", "i2c", "i2s"}


def boot_structure(raw):
    """Conservative overlay-scope reader; never evaluate includes or filters."""
    lines = text_content(raw).splitlines(keepends=True)
    scope, overlay, selected = "all", None, None
    params, owned = {}, []

    def add_params(tokens):
        for token in tokens:
            key, sep, value = token.partition("=")
            if key not in TOUCH_PARAMETERS:
                raise InstallerError(f"Unsupported touchscreen parameter: {key}")
            if key in params:
                raise InstallerError(f"Duplicate touchscreen parameter: {key}")
            if not sep or not re.fullmatch(r"[0-9]+", value):
                raise InstallerError(f"Malformed touchscreen parameter: {key}")
            params[key] = value

    for index, original in enumerate(lines):
        line = original.split("#", 1)[0].strip()
        if not line:
            continue
        if re.match(r"include\b", line):
            raise InstallerError("Active include has ambiguous configuration scope")
        if line.startswith("["):
            if not re.fullmatch(r"\[[^\[\]\r\n]+\]", line):
                raise InstallerError("Malformed boot section")
            scope = line[1:-1] if line == "[all]" else "conditional"
            continue
        key, sep, value = line.partition("=")
        key = key.strip()
        value = value.strip()
        if key == "dtoverlay" and sep:
            pieces = value.split(",")
            overlay = pieces[0]
            if overlay != "ads7846":
                if "ads7846" in overlay.lower() or "xpt2046" in overlay.lower():
                    raise InstallerError("Unknown touchscreen overlay")
                continue
            if selected is not None:
                raise InstallerError("Duplicate ADS7846 overlays")
            if scope != "all":
                raise InstallerError("Conditional touchscreen scope is unsupported")
            if len(line) > 98:
                raise InstallerError("Touchscreen line exceeds firmware limit")
            selected = index
            owned.append(index)
            add_params(pieces[1:])
        elif key == "dtparam" and sep:
            tokens = value.split(",")
            keys = {token.partition("=")[0] for token in tokens}
            if "keep_vref_on" in keys:
                raise InstallerError("Unsupported touchscreen parameter: keep_vref_on")
            if keys & TOUCH_PARAMETERS:
                if overlay != "ads7846" or scope != "all":
                    raise InstallerError("Ambiguous touchscreen parameter scope")
                if keys & BASE_PARAMETERS:
                    raise InstallerError("Mixed base and touchscreen parameter scope")
                add_params(tokens)
                owned.append(index)
            elif overlay == "ads7846" and not keys <= BASE_PARAMETERS:
                raise InstallerError("Unsupported touchscreen parameter: " + ",".join(sorted(keys)))
        elif "ads7846" in line.lower():
            raise InstallerError("Malformed touchscreen directive")
    return lines, selected, owned, params, scope


def plan_boot(raw, profile_name):
    values = touch_values(profile_name)
    lines, selected, owned, _, _ = boot_structure(raw)
    newline = "\r\n" if b"\r\n" in raw else "\n"
    generated = [
        "dtoverlay=ads7846,"
        + ",".join(f"{k}={values[k]}" for k in ("xmin", "xmax", "ymin", "ymax", "xohms")),
        "dtparam=penirq=25,speed=50000,cs=1",
        "dtoverlay=",
    ]
    if any(len(line) > 80 for line in generated):
        raise InstallerError("Generated firmware line too long")
    block = newline.join(generated) + newline
    if selected is None:
        prefix = raw.decode("utf-8")
        if prefix and not prefix.endswith("\n"):
            prefix += newline
        return (prefix + "[all]" + newline + block).encode()
    # A previously generated closing directive is consumed with its owned block.
    last = max(owned)
    if last + 1 < len(lines) and lines[last + 1].strip() == "dtoverlay=":
        owned.append(last + 1)
    output = []
    for index, line in enumerate(lines):
        if index == selected:
            output.append(block)
        if index in owned:
            if "#" in line:
                output.append("#" + line.split("#", 1)[1])
            continue
        output.append(line)
    return "".join(output).encode()


def render_xorg(profile_name):
    matrix = " ".join(profile(profile_name)["matrix"])
    return (
        "# MPI3508 panel-specific configuration\n"
        'Section "InputClass"\n'
        f'    Identifier "{IDENTIFIER}"\n'
        '    MatchProduct "ADS7846 Touchscreen"\n'
        '    MatchIsTouchscreen "on"\n'
        '    Driver "libinput"\n'
        f'    Option "CalibrationMatrix" "{matrix}"\n'
        "EndSection\n"
    ).encode()


def input_sections(raw, source):
    sections, current, kind = [], None, None
    try:
        for line in text_content(raw).splitlines():
            tokens = shlex.split(line, comments=True, posix=True)
            if not tokens:
                continue
            key = tokens[0].lower()
            if key == "section":
                if current is not None or len(tokens) != 2:
                    raise ValueError
                current, kind = [], tokens[1].lower()
            elif key == "endsection":
                if current is None or len(tokens) != 1:
                    raise ValueError
                if kind in ("inputclass", "inputdevice"):
                    sections.append((kind, current))
                current, kind = None, None
            elif current is None:
                raise ValueError
            else:
                current.append((key, tokens[1:]))
        if current is not None:
            raise ValueError
    except (ValueError, InstallerError):
        raise InstallerError(f"Malformed Xorg configuration: {source}") from None
    return sections


def matrix_values(value):
    try:
        values = tuple(float(v) for v in value.replace(",", " ").split())
    except ValueError:
        return None
    return values if len(values) == 9 and all(math.isfinite(v) for v in values) else None


def check_xorg_conflicts(mapping):
    for source, raw in mapping.items():
        for kind, entries in input_sections(raw, source):
            applicable = True
            for key, args in entries:
                if key == "matchproduct" and len(args) == 1:
                    applicable &= any(p in "ADS7846 Touchscreen" for p in args[0].split("|"))
                if key == "matchistouchscreen" and args == ["off"]:
                    applicable = False
            if not applicable:
                continue
            for key, args in entries:
                conflict = kind == "inputdevice"
                if key == "driver":
                    conflict |= args != ["libinput"]
                if key == "option":
                    if len(args) != 2:
                        conflict = True
                    else:
                        option, value = args
                        normalized = option.lower().replace(" ", "").replace("_", "")
                        if normalized in {
                            "calibration",
                            "calibrationmatrix",
                            "swapaxes",
                            "invertx",
                            "inverty",
                        }:
                            conflict = True
                        if normalized in {"transformationmatrix", "coordinatetransformationmatrix"}:
                            conflict |= matrix_values(value) != IDENTITY
                if conflict:
                    raise InstallerError(f"Competing Xorg input rule: {source}")


@dataclass(frozen=True)
class Layout:
    root: Path = Path("/")
    owner_uid: int = 0


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def identity(info):
    return {
        "dev": info.st_dev,
        "ino": info.st_ino,
        "uid": info.st_uid,
        "gid": info.st_gid,
        "mode": stat.S_IMODE(info.st_mode),
    }


# The cross-session file contract. Journals also record dev/ino, but those are only
# within-run identity: Linux FAT assigns inode numbers with iunique() when the
# filesystem is mounted, and device numbers can change across reboot.
CONTRACT = ("sha256", "size", "uid", "gid", "mode")


def contract(snapshot):
    return None if snapshot is None else {key: snapshot[key] for key in CONTRACT}


def mount_id(fd):
    """Observe the opened descriptor's mount, not a pathname or device number."""
    if sys.platform != "linux":
        return None
    # proc_pid_fdinfo(5), mnt_id; Linux fs/proc/fd.c emits a decimal mount ID.
    with Path(f"/proc/self/fdinfo/{fd}").open("rb") as stream:
        raw = stream.read(LIMIT + 1)
    fields = [line for line in raw.splitlines() if line.startswith(b"mnt_id:")]
    if len(raw) > LIMIT or len(fields) != 1:
        raise OSError("Mount observation missing or ambiguous")
    match = re.fullmatch(rb"mnt_id:[ \t]*([0-9]+)", fields[0])
    if match is None:
        raise OSError("Malformed mount observation")
    try:
        return int(match[1])
    except ValueError:
        raise OSError("Invalid mount observation") from None


class Files:
    """Descriptor-relative operations with no symlink or unexpected mount traversal."""

    def __init__(self, layout):
        self.layout = layout
        self.root = Path(layout.root)
        self.dirs = {}
        self.mounts = {}
        self.lock = None

    def __enter__(self):
        self.directory("")
        return self

    def __exit__(self, *unused):
        for fd, _ in self.dirs.values():
            os.close(fd)

    def safe(self, info, path, directory=False):
        correct_type = stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode)
        if not correct_type:
            raise InstallerError(f"Unsafe type or symlink: {path}")
        if info.st_uid != self.layout.owner_uid:
            raise InstallerError(f"Unexpected owner uid: {path}")
        if info.st_mode & 0o022:
            raise InstallerError(f"Unsafe writable mode: {path}")
        if not directory and info.st_mode & 0o7000:
            raise InstallerError(f"Unsafe special file mode: {path}")
        if not directory and info.st_nlink != 1:
            raise InstallerError(f"Unsafe hardlink: {path}")

    def observation(self, fd):
        try:
            value = mount_id(fd)
        except OSError:
            raise MountObservationError("Mount observation unavailable") from None
        if type(value) is int and value >= 0:
            return value
        if value is None and sys.platform != "linux":
            return None
        raise MountObservationError("Mount observation unavailable or invalid")

    def check_mount(self, handle, parent_fd, relative, directory=False):
        observed = self.observation(handle)
        if parent_fd is not None:
            parent_mount = self.observation(parent_fd)
            # Only the firmware directory may introduce a separately mounted filesystem.
            if not (directory and relative == "boot/firmware") and (
                observed != parent_mount or os.fstat(handle).st_dev != os.fstat(parent_fd).st_dev
            ):
                raise InstallerError(f"Unexpected mount boundary: {relative}")
        return observed

    def check_handle(self, relative, handle, directory=False):
        parent, _, name = relative.rpartition("/")
        parent_fd = self.dirs[parent][0] if relative else None
        held = os.fstat(handle)
        self.safe(held, relative, directory)
        observed = self.check_mount(handle, parent_fd, relative, directory)
        before = (
            os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
            if relative
            else self.root.lstat()
        )
        self.safe(before, relative, directory)
        flags = os.O_RDONLY | os.O_NOFOLLOW | (os.O_DIRECTORY if directory else os.O_NONBLOCK)
        fresh = os.open(name, flags, dir_fd=parent_fd) if relative else os.open(self.root, flags)
        try:
            info = os.fstat(fresh)
            self.safe(info, relative, directory)
            named_mount = self.check_mount(fresh, parent_fd, relative, directory)
            after = (
                os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
                if relative
                else self.root.lstat()
            )
            self.safe(after, relative, directory)
            if (
                identity(held) != identity(before)
                or identity(held) != identity(info)
                or identity(held) != identity(after)
            ):
                raise InstallerError(f"Opened/name identity changed: {relative}")
            if observed != named_mount:
                raise InstallerError(f"Opened/name mount identity changed: {relative}")
        finally:
            os.close(fresh)
        return observed

    def directory(self, relative):
        if relative in self.dirs:
            self.check_dirs()
            return self.dirs[relative][0]
        if relative:
            parent, _, name = relative.rpartition("/")
            parent_fd = self.directory(parent)
            before = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
            self.safe(before, relative, directory=True)
            fd = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent_fd)
        else:
            before = self.root.lstat()
            self.safe(before, relative, directory=True)
            fd = os.open(self.root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            info = os.fstat(fd)
            self.safe(info, relative, directory=True)
            if identity(info) != identity(before):
                raise InstallerError(f"Directory identity changed: {relative}")
            observed = self.check_handle(relative, fd, directory=True)
            self.dirs[relative] = (fd, identity(info))
            self.mounts[relative] = observed
        except BaseException:
            os.close(fd)
            raise
        return fd

    def check_dirs(self):
        # Fresh descriptors detect same-inode overmounts that stat comparisons cannot.
        for relative, (fd, expected) in self.dirs.items():
            observed = self.check_handle(relative, fd, directory=True)
            if identity(os.fstat(fd)) != expected:
                raise InstallerError(f"Parent identity changed: {relative}")
            if observed != self.mounts[relative]:
                raise InstallerError(f"Parent mount identity changed: {relative}")
        if self.lock is not None:
            handle, expected, expected_mount = self.lock
            observed = self.check_handle(STATE + "/lock", handle)
            if identity(os.fstat(handle)) != expected:
                raise InstallerError("Lock identity changed")
            if observed != expected_mount:
                raise InstallerError("Lock mount identity changed")

    def parent(self, relative):
        parent, _, name = relative.rpartition("/")
        fd = self.directory(parent)
        self.check_dirs()
        return fd, name

    def read(self, relative, *, absent=False):
        fd, name = self.parent(relative)
        try:
            before = os.stat(name, dir_fd=fd, follow_symlinks=False)
        except FileNotFoundError:
            if absent:
                return None, None
            raise InstallerError(f"Required file missing: {relative}") from None
        self.safe(before, relative)
        handle = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
        with os.fdopen(handle, "rb") as stream:
            opened = os.fstat(stream.fileno())
            self.safe(opened, relative)
            if identity(opened) != identity(before):
                raise InstallerError(f"File identity changed: {relative}")
            observed_mount = self.check_handle(relative, stream.fileno())
            raw = stream.read(LIMIT + 1)
            after = os.fstat(stream.fileno())
            if self.check_handle(relative, stream.fileno()) != observed_mount:
                raise InstallerError(f"File mount identity changed during read: {relative}")
        self.check_dirs()
        at_name = os.stat(name, dir_fd=fd, follow_symlinks=False)
        self.safe(after, relative)
        self.safe(at_name, relative)
        if (
            len(raw) > LIMIT
            or len(raw) != before.st_size
            or identity(before) != identity(after)
            or before.st_mtime_ns != after.st_mtime_ns
            or before.st_ctime_ns != after.st_ctime_ns
            or before.st_size != after.st_size
            or identity(at_name) != identity(after)
        ):
            raise InstallerError(f"File changed during read: {relative}")
        return raw, {**identity(after), "sha256": digest(raw), "size": len(raw)}

    def expect(self, relative, expected):
        _, observed = self.read(relative, absent=True)
        if observed != expected:
            raise InstallerError(f"File drift, hash or identity changed: {relative}")

    def expect_contract(self, relative, expected):
        """Check a snapshot saved by an earlier session; refuses content/owner/mode drift."""
        _, observed = self.read(relative, absent=True)
        if contract(observed) != contract(expected):
            raise InstallerError(f"File drift, hash, owner or mode changed: {relative}")

    def exclusive(self, relative, raw, metadata=None):
        fd, name = self.parent(relative)
        handle = os.open(
            name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=fd
        )
        with os.fdopen(handle, "wb") as stream:
            observed_mount = self.check_handle(relative, stream.fileno())
            if metadata is not None:
                info = os.fstat(stream.fileno())
                if (info.st_uid, info.st_gid) != (metadata["uid"], metadata["gid"]):
                    os.fchown(stream.fileno(), metadata["uid"], metadata["gid"])
                os.fchmod(stream.fileno(), metadata["mode"])
            self.check_dirs()
            if self.check_handle(relative, stream.fileno()) != observed_mount:
                raise InstallerError(f"File mount identity changed before write: {relative}")
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
            if self.check_handle(relative, stream.fileno()) != observed_mount:
                raise InstallerError(f"File mount identity changed during write: {relative}")
        os.fsync(fd)
        observed, snapshot = self.read(relative)
        if observed != raw:
            raise InstallerError(f"Exclusive file readback mismatch: {relative}")
        return snapshot

    def replace(self, relative, stage, expected, staged, on_replaced=None):
        self.expect(stage, staged)
        self.expect(relative, expected)
        fd, name = self.parent(relative)
        stage_fd, stage_name = self.parent(stage)
        if fd != stage_fd:
            raise InstallerError("Stage must share target directory")
        os.replace(stage_name, name, src_dir_fd=fd, dst_dir_fd=fd)
        if on_replaced is not None:
            on_replaced()
        os.fsync(fd)

    def remove(self, relative, expected, on_removed=None):
        self.expect(relative, expected)
        fd, name = self.parent(relative)
        os.unlink(name, dir_fd=fd)
        if on_removed is not None:
            on_removed()
        os.fsync(fd)

    def mkdir_state(self):
        fd, name = self.parent(STATE)
        try:
            os.mkdir(name, 0o700, dir_fd=fd)
            os.fsync(fd)
        except FileExistsError:
            pass
        self.directory(STATE)


@contextlib.contextmanager
def locked(files):
    files.mkdir_state()
    path = STATE + "/lock"
    fd, name = files.parent(path)
    try:
        handle = os.open(name, os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=fd)
    except FileExistsError:
        files.read(path)
        handle = os.open(name, os.O_RDWR | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
    try:
        info = os.fstat(handle)
        files.safe(info, path)
        if identity(info) != identity(os.stat(name, dir_fd=fd, follow_symlinks=False)):
            raise InstallerError("Lock identity changed")
        observed_mount = files.check_handle(path, handle)
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise InstallerError("Concurrent installer: lock busy") from None
        os.fsync(handle)
        os.fsync(fd)
        files.lock = (handle, identity(info), observed_mount)
        files.check_dirs()
        yield
    finally:
        files.lock = None
        os.close(handle)


def xorg_files(files):
    result = {}
    for directory in ("etc/X11/xorg.conf.d", "usr/share/X11/xorg.conf.d"):
        try:
            fd = files.directory(directory)
        except FileNotFoundError:
            if directory.startswith("etc"):
                raise InstallerError("Missing Xorg configuration directory") from None
            continue
        for name in sorted(os.listdir(fd)):
            if name.endswith(".conf"):
                relative = directory + "/" + name
                result[relative] = files.read(relative)[0]
    raw, _ = files.read("etc/X11/xorg.conf", absent=True)
    if raw is not None:
        result["etc/X11/xorg.conf"] = raw
    return result


def preflight(files, profile_name):
    boot, boot_snapshot = files.read(BOOT)
    rule, rule_snapshot = files.read(RULE, absent=True)
    rules = xorg_files(files)
    if rule is not None:
        if rule != render_xorg(profile_name):
            raise InstallerError("Existing target rule is not owned MPI3508 configuration")
        rules.pop(RULE, None)
    check_xorg_conflicts(rules)
    # Validate the state parent even before creating state or backups.
    files.directory("var/lib")
    return boot, rule, boot_snapshot, rule_snapshot


def plan_targets(boot, rule, profile_name, include_xorg):
    plans = [(BOOT, boot, plan_boot(boot, profile_name))]
    if include_xorg:
        plans.append((RULE, rule, render_xorg(profile_name)))
    return plans


def plan_changes(plans):
    return {path: (old, new) for path, old, new in plans if old != new}


def show_plan(plans):
    for path, old, new in plans:
        print(
            "".join(
                difflib.unified_diff(
                    (old or b"").decode().splitlines(keepends=True),
                    new.decode().splitlines(keepends=True),
                    fromfile="/" + path,
                    tofile="/" + path + " (planned)",
                )
            ),
            end="",
        )


def checkpoint_call(checkpoint, stage, path=None):
    if checkpoint is not None:
        checkpoint(stage, path)


def transaction_id(value):
    if not isinstance(value, str) or re.fullmatch(ID_PATTERN, value) is None:
        raise InstallerError("Invalid transaction identifier")
    return value


def journal_path(value):
    return STATE + "/" + transaction_id(value) + ".json"


def json_bytes(value):
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()


def no_duplicates(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def valid_snapshot(value, nullable=False):
    if value is None:
        return nullable
    keys = {"dev", "ino", "uid", "gid", "mode", "sha256", "size"}
    return (
        isinstance(value, dict)
        and set(value) == keys
        and all(type(value[k]) is int and value[k] >= 0 for k in keys - {"sha256"})
        and value["mode"] <= 0o777
        and not value["mode"] & 0o022
        and value["size"] <= LIMIT
        and isinstance(value["sha256"], str)
        and re.fullmatch(r"[0-9a-f]{64}", value["sha256"]) is not None
    )


def load_journal(files, tx):
    raw, snapshot = files.read(journal_path(tx))
    try:
        data = json.loads(raw, object_pairs_hook=no_duplicates)
        if (
            not isinstance(data, dict)
            or set(data) != {"version", "id", "profile", "status", "parent", "entries"}
            or data["version"] != 1
            or data["id"] != tx
            or data["profile"] not in PROFILES
            or data["status"]
            not in {
                "prepared",
                "committed",
                "restoring",
                "restored",
                "rolled-back",
                "manual-recovery",
            }
            or not isinstance(data["entries"], list)
            or not 1 <= len(data["entries"]) <= 2
        ):
            raise ValueError
        if data["parent"] is not None:
            transaction_id(data["parent"])
            if data["parent"] == tx:
                raise ValueError
        paths = []
        for entry in data["entries"]:
            if not isinstance(entry, dict) or set(entry) != {
                "path",
                "before",
                "after",
                "backup",
                "backup_snapshot",
                "stage",
            }:
                raise ValueError
            path = entry["path"]
            if path not in TARGETS or path in paths:
                raise ValueError
            paths.append(path)
            if (
                not valid_snapshot(entry["before"], nullable=path == RULE)
                or not valid_snapshot(entry["after"])
                or not valid_snapshot(entry["backup_snapshot"], nullable=True)
            ):
                raise ValueError
            expected_backup = STATE + f"/{tx}-{TARGETS.index(path)}.bak"
            expected_stage = str(Path(path).parent / f".mpi3508-{tx}-{TARGETS.index(path)}")
            if entry["stage"] != expected_stage:
                raise ValueError
            if entry["before"] is None:
                if entry["backup"] is not None or entry["backup_snapshot"] is not None:
                    raise ValueError
            elif (
                entry["backup"] != expected_backup
                or entry["backup_snapshot"] is None
                or entry["before"]["sha256"] != entry["backup_snapshot"]["sha256"]
            ):
                raise ValueError
        if paths != sorted(paths, key=TARGETS.index):
            raise ValueError
    except (ValueError, TypeError, KeyError, InstallerError):
        raise InstallerError(f"Malformed transaction journal schema: {tx}") from None
    return data, snapshot


def save_journal(files, data, previous):
    path = journal_path(data["id"])
    raw = json_bytes(data)
    if previous is None:
        return files.exclusive(path, raw)
    stage = STATE + "/.journal-" + uuid.uuid4().hex
    staged = files.exclusive(stage, raw)
    files.replace(path, stage, previous, staged)
    files.expect(path, staged)
    return staged


def journals(files):
    result = {}
    for name in sorted(os.listdir(files.directory(STATE))):
        if name.endswith(".json"):
            tx = transaction_id(name[:-5])
            data, _ = load_journal(files, tx)
            result[tx] = data
    for data in result.values():
        if data["status"] in {"prepared", "restoring", "manual-recovery"}:
            raise InstallerError(
                f"Incomplete transaction {data['id']}; manual recovery required; preserve evidence"
            )
        if data["parent"] is not None and data["parent"] not in result:
            raise InstallerError("Journal lineage parent missing; manual recovery required")
    return result


def active_tip(records):
    active = {tx: data for tx, data in records.items() if data["status"] == "committed"}
    parents = {data["parent"] for data in active.values()}
    tips = set(active) - parents
    if len(tips) > 1 or active and not tips:
        raise InstallerError("Ambiguous transaction lineage; manual recovery required")
    return next(iter(tips), None)


def validate_lineage(files, records, tip):
    visited, paths = set(), set()
    while tip is not None:
        if tip in visited or tip not in records or records[tip]["status"] != "committed":
            raise InstallerError("Invalid active journal lineage; manual recovery required")
        visited.add(tip)
        for entry in records[tip]["entries"]:
            if entry["path"] not in paths:
                files.expect_contract(entry["path"], entry["after"])
                paths.add(entry["path"])
            backup_bytes(files, entry)
        tip = records[tip]["parent"]


def backup_bytes(files, entry):
    if entry["backup"] is None:
        return None
    files.expect_contract(entry["backup"], entry["backup_snapshot"])
    raw, snapshot = files.read(entry["backup"])
    if snapshot["sha256"] != entry["before"]["sha256"]:
        raise InstallerError("Backup hash mismatch")
    return raw


def reverse_writes(files, completed):
    """Reverse only our verified writes. Any competing edit makes recovery manual."""
    for path, old_raw, old_snapshot, post_snapshot in reversed(completed):
        files.expect(path, post_snapshot)
        if old_raw is None:
            files.remove(path, post_snapshot)
        else:
            stage = str(Path(path).parent / (".mpi3508-rollback-" + uuid.uuid4().hex))
            staged = files.exclusive(stage, old_raw, old_snapshot)
            files.replace(path, stage, post_snapshot, staged)
            files.expect(path, staged)


def install(layout, profile_name, checkpoint=None, include_xorg=True, confirmed=None):
    """confirmed: the plan_changes() shown before acknowledgement; any other plan refuses."""
    profile(profile_name)
    try:
        with Files(layout) as files:
            preflight(files, profile_name)
            with locked(files):
                records = journals(files)
                parent = active_tip(records)
                validate_lineage(files, records, parent)
                boot, rule, boot_snapshot, rule_snapshot = preflight(files, profile_name)
                plans = plan_targets(boot, rule, profile_name, include_xorg)
                if confirmed is not None and plan_changes(plans) != confirmed:
                    raise InstallerError("Planned changes differ from the confirmed plan")
                snapshots = {BOOT: boot_snapshot, RULE: rule_snapshot}
                planned = [(path, raw, snapshots[path], new) for path, raw, new in plans]
                if all(raw == new for _, raw, _, new in planned) and parent is not None:
                    for entry in records[parent]["entries"]:
                        files.expect_contract(entry["path"], entry["after"])
                    return parent
                tx = uuid.uuid4().hex
                data = {
                    "version": 1,
                    "id": tx,
                    "profile": profile_name,
                    "status": "prepared",
                    "parent": parent,
                    "entries": [],
                }
                originals = {}
                for path, raw, before, new in planned:
                    if raw == new:
                        continue
                    number = TARGETS.index(path)
                    backup = STATE + f"/{tx}-{number}.bak" if raw is not None else None
                    backed = files.exclusive(backup, raw) if backup else None
                    stage = str(Path(path).parent / f".mpi3508-{tx}-{number}")
                    metadata = before or {
                        "uid": layout.owner_uid,
                        "gid": os.getgid(),
                        "mode": 0o644,
                    }
                    after = files.exclusive(stage, new, metadata)
                    data["entries"].append(
                        {
                            "path": path,
                            "before": before,
                            "after": after,
                            "backup": backup,
                            "backup_snapshot": backed,
                            "stage": stage,
                        }
                    )
                    originals[path] = raw
                unchanged = {path: before for path, raw, before, new in planned if raw == new}
                if not data["entries"]:
                    raise InstallerError("Configuration already matches but has no restore lineage")
                for entry in data["entries"]:
                    files.expect(entry["path"], entry["before"])
                    backup_bytes(files, entry)
                journal_snapshot = save_journal(files, data, None)
                completed = []
                try:
                    checkpoint_call(checkpoint, "prepared")
                    for entry in data["entries"]:
                        path = entry["path"]
                        checkpoint_call(checkpoint, "before_replace", layout.root / path)
                        for fixed_path, expected in unchanged.items():
                            files.expect(fixed_path, expected)
                        # Validate every preimage/postimage and backup before the next write.
                        done = {item[0] for item in completed}
                        for item in data["entries"]:
                            files.expect(
                                item["path"],
                                item["after"] if item["path"] in done else item["before"],
                            )
                            backup_bytes(files, item)

                        def record_replaced(path=path, entry=entry):
                            completed.append(
                                (path, originals[path], entry["before"], entry["after"])
                            )

                        files.replace(
                            path,
                            entry["stage"],
                            entry["before"],
                            entry["after"],
                            on_replaced=record_replaced,
                        )
                        checkpoint_call(checkpoint, "after_replace", layout.root / path)
                        files.expect(path, entry["after"])
                    checkpoint_call(checkpoint, "before_commit")
                    for fixed_path, expected in unchanged.items():
                        files.expect(fixed_path, expected)
                    for entry in data["entries"]:
                        files.expect(entry["path"], entry["after"])
                    data["status"] = "committed"
                    save_journal(files, data, journal_snapshot)
                except BaseException as error:
                    try:
                        reverse_writes(files, completed)
                        data["status"] = "rolled-back"
                        save_journal(files, data, journal_snapshot)
                    except (OSError, InstallerError):
                        raise InstallerError(
                            f"Manual recovery required for transaction {tx}"
                        ) from error
                    raise
                return tx
    except OSError as error:
        raise InstallerError(f"Filesystem operation refused: {type(error).__name__}") from None


def restore(layout, transaction, checkpoint=None):
    transaction_id(transaction)
    try:
        with Files(layout) as files, locked(files):
            records = journals(files)
            if transaction not in records or active_tip(records) != transaction:
                raise InstallerError("Restore committed transactions in reverse order")
            validate_lineage(files, records, transaction)
            data, journal_snapshot = load_journal(files, transaction)
            # Read all backups, targets and stages before the first target mutation.
            prepared = []
            for entry in data["entries"]:
                path = entry["path"]
                files.expect_contract(path, entry["after"])
                current, current_snapshot = files.read(path)
                original = backup_bytes(files, entry)
                stage, staged = None, None
                if original is not None:
                    stage = str(Path(path).parent / (".mpi3508-restore-" + uuid.uuid4().hex))
                    staged = files.exclusive(stage, original, entry["before"])
                prepared.append((entry, current, current_snapshot, stage, staged))
            data["status"] = "restoring"
            journal_snapshot = save_journal(files, data, journal_snapshot)
            completed = []
            try:
                checkpoint_call(checkpoint, "prepared")
                for entry, current, current_snapshot, stage, staged in prepared:
                    path = entry["path"]
                    checkpoint_call(checkpoint, "before_replace", layout.root / path)
                    for item, _, expected, _, _ in prepared:
                        done = next((v for v in completed if v[0] == item["path"]), None)
                        files.expect(item["path"], done[3] if done else expected)
                        backup_bytes(files, item)

                    def record_replaced(
                        path=path, current=current, current_snapshot=current_snapshot, staged=staged
                    ):
                        completed.append((path, current, current_snapshot, staged))

                    if stage is None:
                        files.remove(path, current_snapshot, on_removed=record_replaced)
                    else:
                        files.replace(
                            path, stage, current_snapshot, staged, on_replaced=record_replaced
                        )
                    checkpoint_call(checkpoint, "after_replace", layout.root / path)
                    files.expect(path, staged)
                checkpoint_call(checkpoint, "before_commit")
                for path, _, _, expected in completed:
                    files.expect(path, expected)
                # Restoring a later stage may recreate an older stage's postimage inode.
                # Rebind only the direct parent after checking its saved byte/metadata contract.
                if data["parent"] is not None:
                    parent_data, parent_snapshot = load_journal(files, data["parent"])
                    for entry in parent_data["entries"]:
                        _, observed = files.read(entry["path"])
                        if contract(observed) != contract(entry["after"]):
                            raise InstallerError("Parent lineage postimage drift")
                        entry["after"] = observed
                    save_journal(files, parent_data, parent_snapshot)
                data["status"] = "restored"
                save_journal(files, data, journal_snapshot)
            except BaseException as error:
                try:
                    reverse_writes(files, completed)
                    for entry in data["entries"]:
                        _, entry["after"] = files.read(entry["path"])
                    data["status"] = "committed"
                    save_journal(files, data, journal_snapshot)
                except (OSError, InstallerError):
                    raise InstallerError(
                        f"Manual recovery required for restore {transaction}"
                    ) from error
                raise
    except OSError as error:
        raise InstallerError(f"Filesystem operation refused: {type(error).__name__}") from None


def verify_saved(layout, profile_name):
    """Semantic readback: no planner or renderer used as an answer key."""
    p = profile(profile_name)
    report = {"saved": "unavailable", "runtime": "not-examined", "physical": "not-examined"}
    try:
        with Files(layout) as files:
            boot, _ = files.read(BOOT, absent=True)
            rule, _ = files.read(RULE, absent=True)
            if boot is None or rule is None:
                return report
            _, selected, _, parameters, _ = boot_structure(boot)
            boot_ok = selected is not None and parameters == touch_values(profile_name)
            sections = input_sections(rule, RULE)
            expected = [
                ("identifier", [IDENTIFIER]),
                ("matchproduct", ["ADS7846 Touchscreen"]),
                ("matchistouchscreen", ["on"]),
                ("driver", ["libinput"]),
            ]
            rule_ok = len(sections) == 1 and sections[0][0] == "inputclass"
            if rule_ok:
                entries = sections[0][1]
                options = [args for key, args in entries if key == "option"]
                rule_ok = (
                    all(entries.count(e) == 1 for e in expected)
                    and len(entries) == 5
                    and len(options) == 1
                    and len(options[0]) == 2
                    and options[0][0] == "CalibrationMatrix"
                    and matrix_values(options[0][1]) == tuple(map(float, p["matrix"]))
                )
            others = xorg_files(files)
            others.pop(RULE, None)
            check_xorg_conflicts(others)
            report["saved"] = "match" if boot_ok and rule_ok else "mismatch"
    except InstallerError:
        report["saved"] = "mismatch"
    except OSError:
        report["saved"] = "unavailable"
    return report


def check_environment():
    if sys.version_info < MINIMUM_PYTHON:
        raise InstallerError("Python 3.11 or newer required")
    if sys.platform != "linux":
        raise InstallerError("Supported platform requires Linux on Raspberry Pi 5")
    if platform.machine() not in {"aarch64", "arm64"}:
        raise InstallerError("Supported platform requires arm64 Raspberry Pi 5")
    try:
        model = Path("/proc/device-tree/model").read_bytes()
        if not model.rstrip(b"\0").startswith(b"Raspberry Pi 5 Model B"):
            raise InstallerError("Raspberry Pi 5 Model B required")
        release = Path("/etc/os-release").read_text()
        if not re.search(r'^ID=(?:kali|"kali")$', release, re.MULTILINE):
            raise InstallerError("Supported platform requires Kali")
        if os.environ.get("XDG_SESSION_TYPE") == "wayland" or os.environ.get("WAYLAND_DISPLAY"):
            raise InstallerError("Xorg required; Wayland is unsupported")
        for required in (
            "/usr/bin/Xorg",
            "/usr/bin/xinput",
            "/usr/lib/xorg/modules/input/libinput_drv.so",
            "/boot/firmware/overlays/ads7846.dtbo",
        ):
            if not Path(required).is_file():
                raise InstallerError("Missing existing Xorg/libinput/ADS7846 prerequisites")
        servers = 0
        for process in Path("/proc").glob("[0-9]*"):
            try:
                if (process / "comm").read_text().strip() != "Xorg":
                    continue
                args = (process / "cmdline").read_bytes().split(b"\0")
                if any(arg in args for arg in (b"-config", b"-configdir")):
                    raise InstallerError("Custom Xorg configuration scope is unsupported")
                servers += 1
            except (FileNotFoundError, PermissionError):
                continue
        if servers != 1:
            raise InstallerError("Exactly one existing Xorg display is required")
    except OSError:
        raise InstallerError(
            "Cannot establish Raspberry Pi 5/Kali platform prerequisites"
        ) from None


def abs_info(fd, axis):
    # Linux arm64 asm-generic _IOR('E', 0x40 + axis, struct input_absinfo).
    # input_absinfo is six signed 32-bit native-endian fields; ABS_X=0, ABS_Y=1.
    if axis not in (0, 1) or struct.calcsize("=6i") != 24:
        raise InstallerError("Unsupported ABS ABI")
    request = (2 << 30) | (24 << 16) | (ord("E") << 8) | (0x40 + axis)
    response = fcntl.ioctl(fd, request, bytes(24))
    if len(response) != 24:
        raise InstallerError("Truncated ABS observation")
    fields = struct.unpack("=6i", response)
    if fields[1] >= fields[2]:
        raise InstallerError("Invalid ABS observation")
    return fields[1:3]


def ads7846_event():
    """Select by device identity; event numbers are only discovered endpoints."""
    devices = []
    for event in Path("/sys/class/input").glob("event*"):
        if (event / "device/name").read_text().strip() == "ADS7846 Touchscreen":
            devices.append(event)
    if len(devices) != 1:
        raise InstallerError("Unique ADS7846 device unavailable")
    return devices[0]


def observe_dt_bounds(event):
    device = (event / "device").resolve(strict=True)
    nodes = [p / "of_node" for p in (device, *device.parents) if (p / "of_node").exists()]
    nodes = [
        p.resolve(strict=True)
        for p in nodes
        if b"ti,ads7846" in (p / "compatible").read_bytes().split(b"\0")
    ]
    if len(set(nodes)) != 1:
        raise InstallerError("Unique ADS7846 DT observation unavailable")
    node = nodes[0]
    if not str(node).startswith("/sys/firmware/devicetree/base/"):
        raise InstallerError("Unexpected device-tree origin")
    dt = []
    for axis in ("x", "y"):
        limits = []
        for bound in ("min", "max"):
            raw = (node / f"ti,{axis}-{bound}").read_bytes()
            if len(raw) != 2:
                raise InstallerError("ADS7846 DT bounds require 16-bit properties")
            limits.append(int.from_bytes(raw, "big"))
        dt.append(tuple(limits))
    return dt


def observe_abs_bounds(event):
    numbers = tuple(int(n) for n in (event / "dev").read_text().strip().split(":"))
    fd = os.open("/dev/input/" + event.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        info = os.fstat(fd)
        if (
            not stat.S_ISCHR(info.st_mode)
            or (os.major(info.st_rdev), os.minor(info.st_rdev)) != numbers
        ):
            raise InstallerError("Input device identity mismatch")
        # Verify the device name on the opened descriptor, not just the sysfs label.
        name = fcntl.ioctl(fd, (2 << 30) | (256 << 16) | (ord("E") << 8) | 6, bytes(256))
        if name.split(b"\0", 1)[0] != b"ADS7846 Touchscreen":
            raise InstallerError("Opened input device name mismatch")
        bounds = [abs_info(fd, axis) for axis in (0, 1)]
    finally:
        os.close(fd)
    return bounds


def observe_inputclass(layout, device_node):
    """Read a standard log only when an active Xorg process holds that inode open."""
    display = os.environ.get("DISPLAY", "")
    if re.fullmatch(r":[0-9]+(?:\.[0-9]+)?", display) is None:
        raise InstallerError("Local Xorg display unavailable")
    number = display[1:].split(".", 1)[0]
    with Files(layout) as files:
        raw, snapshot = files.read(f"var/log/Xorg.{number}.log")
    holders = []
    for process in Path("/proc").glob("[0-9]*"):
        try:
            if (process / "comm").read_text().strip() != "Xorg":
                continue
            # Inspect process properties, never environments or authentication files.
            args = (process / "cmdline").read_bytes().split(b"\0")
            if f":{number}".encode() not in args:
                continue
            if any(arg in args for arg in (b"-config", b"-configdir")):
                raise InstallerError("Custom Xorg configuration scope is unsupported")
            for descriptor in (process / "fd").iterdir():
                info = descriptor.stat()
                if (info.st_dev, info.st_ino) == (snapshot["dev"], snapshot["ino"]):
                    holders.append(process.name)
                    break
        except (FileNotFoundError, PermissionError):
            continue
    if len(holders) != 1:
        raise InstallerError("Current Xorg log provenance unavailable")
    log = text_content(raw)
    starts = list(
        re.finditer(
            r"config/udev: Adding input device ADS7846 Touchscreen \("
            + re.escape(device_node)
            + r"\)",
            log,
        )
    )
    if not starts:
        raise InstallerError("Current ADS7846 device log unavailable")
    block = log[starts[-1].end() :]
    block = re.split(r"config/udev: Adding input device |Removing device ADS7846", block)[0]
    if 'XINPUT: Adding extended input device "ADS7846 Touchscreen"' not in block:
        raise InstallerError("Incomplete ADS7846 startup observation")
    applied = f'ADS7846 Touchscreen: Applying InputClass "{IDENTIFIER}"' in block
    driver = "Using input driver 'libinput' for 'ADS7846 Touchscreen'" in block
    return "match" if applied and driver else "mismatch"


def xinput_query(*args):
    # Query only the caller's existing local X session. Never discover credentials.
    display = os.environ.get("DISPLAY", "")
    if re.fullmatch(r":[0-9]+(?:\.[0-9]+)?", display) is None:
        raise InstallerError("Existing local Xorg session unavailable")
    env = {"PATH": "/usr/bin:/bin", "LC_ALL": "C", "DISPLAY": display}
    if "XAUTHORITY" in os.environ:
        env["XAUTHORITY"] = os.environ["XAUTHORITY"]
    result = subprocess.run(
        ["/usr/bin/xinput", *args], env=env, capture_output=True, timeout=5, check=False
    )
    if result.returncode or len(result.stdout) > LIMIT:
        raise InstallerError("Live Xorg properties unavailable")
    return result.stdout.decode("utf-8", errors="strict")


def runtime_report(layout, profile_name):
    p = profile(profile_name)
    report = {
        k: "unavailable"
        for k in ("bounds", "dt_bounds", "abs_bounds", "inputclass", "matrix", "ctm", "runtime")
    }
    report["physical"] = "not-examined"
    if layout.root != Path("/") or sys.platform != "linux" or platform.machine() != "aarch64":
        return report
    try:
        event = ads7846_event()
    except (OSError, ValueError, InstallerError):
        event = None
    expected = [(p["x_min"], p["x_max"]), (p["y_min"], p["y_max"])]
    if event is not None:
        for field, observer in (
            ("dt_bounds", observe_dt_bounds),
            ("abs_bounds", observe_abs_bounds),
        ):
            try:
                report[field] = "match" if observer(event) == expected else "mismatch"
            except (OSError, ValueError, InstallerError):
                pass  # Explicit unavailable field remains; never substitute saved text.
    components = (report["dt_bounds"], report["abs_bounds"])
    if components == ("match", "match"):
        report["bounds"] = "match"
    elif "mismatch" in components:
        report["bounds"] = "mismatch"
    try:
        ids = xinput_query("list", "--id-only", "ADS7846 Touchscreen").split()
        if len(ids) != 1 or not ids[0].isdigit():
            raise InstallerError("Unique Xorg ADS7846 device unavailable")
        props = xinput_query("list-props", ids[0])
        found = {}
        for label in ("libinput Calibration Matrix", "Coordinate Transformation Matrix"):
            matches = re.findall(
                r"^\s*" + re.escape(label) + r" \([0-9]+\):\s*([^\n]+)$", props, re.MULTILINE
            )
            if len(matches) == 1:
                found[label] = matrix_values(matches[0])
        live = found.get("libinput Calibration Matrix")
        if live is not None:
            report["matrix"] = (
                "match"
                if all(abs(a - float(b)) <= 1e-6 for a, b in zip(live, p["matrix"], strict=True))
                else "mismatch"
            )
        ctm = found.get("Coordinate Transformation Matrix")
        if ctm is not None:
            report["ctm"] = "match" if ctm == IDENTITY else "mismatch"
        nodes = re.findall(r'Device Node \([0-9]+\):\s*"(/dev/input/event[0-9]+)"', props)
        if len(nodes) == 1 and event is not None and nodes[0] == "/dev/input/" + event.name:
            report["inputclass"] = observe_inputclass(layout, nodes[0])
    except (OSError, ValueError, InstallerError, subprocess.TimeoutExpired):
        pass
    required = ("bounds", "dt_bounds", "abs_bounds", "inputclass", "matrix", "ctm")
    if all(report[key] == "match" for key in required):
        report["runtime"] = "match"
    elif "mismatch" in report.values():
        report["runtime"] = "mismatch"
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description="MPI3508 panel-specific touchscreen installer")
    commands = parser.add_subparsers(dest="command", required=True)
    for command in ("preview", "install", "verify"):
        sub = commands.add_parser(command)
        sub.add_argument(
            "--profile",
            choices=tuple(PROFILES),
            required=command != "verify",
            default=None if command != "verify" else "pi5-kali-reference",
        )
        if command == "install":
            sub.add_argument(
                "--yes", action="store_true", help="Acknowledge prerequisites and changes"
            )
    sub = commands.add_parser("restore")
    sub.add_argument("--transaction", required=True)
    sub.add_argument("--yes", action="store_true")
    args = parser.parse_args(argv)
    try:
        check_environment()
        layout = Layout()
        if args.command in {"install", "restore"} and os.geteuid() != 0:
            raise InstallerError("Root privileges required")
        if args.command != "restore":
            runtime = runtime_report(layout, args.profile)
            include_xorg = all(
                runtime.get(k) == "match" for k in ("bounds", "dt_bounds", "abs_bounds")
            )
        if args.command in {"install", "restore"}:
            print("Requires an already working display and an independent recovery route.")
            if args.command == "install":
                print(profile(args.profile)["wiring"])
                print(profile(args.profile)["caveat"])
                # Show this run's own plan; install refuses if its locked plan differs.
                with Files(layout) as files:
                    boot, rule, _, _ = preflight(files, args.profile)
                plans = plan_targets(boot, rule, args.profile, include_xorg)
                show_plan(plans)
            if not args.yes:
                try:
                    answer = input("Confirm prerequisites and these changes by typing yes: ")
                except EOFError:
                    raise InstallerError("Confirmation unavailable; no changes made") from None
                if answer != "yes":
                    raise InstallerError("Not confirmed; no changes made")
        if args.command == "restore":
            restore(layout, args.transaction)
            print("Saved transaction restored. Runtime and physical state not examined.")
            return 0
        if args.command == "preview":
            with Files(layout) as files:
                boot, rule, _, _ = preflight(files, args.profile)
            show_plan(plan_targets(boot, rule, args.profile, include_xorg))
            print(profile(args.profile)["caveat"])
            print(profile(args.profile)["wiring"])
            print(
                "Matrix eligible" if include_xorg else "Boot-only plan; reboot and rerun required."
            )
        elif args.command == "install":
            tx = install(
                layout, args.profile, include_xorg=include_xorg, confirmed=plan_changes(plans)
            )
            print("saved-configured" if include_xorg else "boot-configured-reboot-required")
            print(f"Transaction: {tx}. Restore stage transactions in reverse installation order.")
            print("Reboot is user-controlled. Rerun after reboot to examine effective bounds.")
            print("Runtime acceptance not established; physical accuracy not examined.")
        else:
            report = verify_saved(layout, args.profile)
            report.update(runtime)
            print(json.dumps(report, sort_keys=True))
            return 0 if report["saved"] == "match" and report["runtime"] == "match" else 1
        return 0
    except (InstallerError, OSError) as error:
        diagnostic = str(error) if isinstance(error, InstallerError) else type(error).__name__
        print("Refused: " + diagnostic, file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
