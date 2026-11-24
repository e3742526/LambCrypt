#!/usr/bin/env python3
# Modified for LambCrypt by the LambCrypt contributors. Changes from VeraCrypt are in the git history; see UPSTREAM.md.
"""Signed FSKit integration gate for disposable writable exFAT and APFS."""

import argparse
import errno
import fcntl
import hashlib
import os
from pathlib import Path
import plistlib
import random
import re
import stat
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from urllib.parse import unquote, urlsplit

from test_macos_gui_lifecycle import fskit_mounts, is_fskit, require_no_retained_fskit_image


DISK = re.compile(r"/dev/disk[0-9]+(?:s[0-9]+)*")
WHOLE = re.compile(r"/dev/disk[0-9]+")
PASSWORD = "Disposable-FSKit-filesystem-control"
PAYLOAD = Path("trial tree/retained/payload.bin")
MTIME = 1_700_000_000
XATTR = "io.github.e3742526.LambCrypt.filesystem-trial"
XATTR_DATA = b"\0LambCrypt\xff"


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def command(*arguments, timeout=12):
    return subprocess.check_output(arguments, stderr=subprocess.PIPE, timeout=timeout)


def inventory():
    records = plistlib.loads(command("/usr/bin/hdiutil", "info", "-plist"))["images"]
    require(isinstance(records, list) and all(isinstance(r.get("image-path"), str) for r in records),
            "Incomplete Disk Images inventory")
    return records


def media():
    records = plistlib.loads(command("/usr/sbin/ioreg", "-arp", "IOService",
                                     "-k", "BSD Name", "-c", "IOMedia", "-d", "1"))
    return {"/dev/" + record["BSD Name"]: record for record in records}


def mount_table():
    return command("/sbin/mount").decode()


def exact_attachment(records, image_path):
    matches = [rec for rec in records if Path(rec["image-path"]).resolve() == image_path]
    require(len(matches) == 1, f"Expected exactly one Disk Images attachment for {image_path}")
    return matches[0]


def attachment_devices(attachment):
    entities = attachment["system-entities"]
    devices = {rec["dev-entry"]: rec for rec in entities}
    require(devices and len(devices) == len(entities) and all(DISK.fullmatch(dev) for dev in devices),
            "Disk Images did not report a complete, unique set of disk entities")
    return devices


def require_empty_session(mounts, processes):
    require(".veracrypt_aux_mnt" not in mounts and not fskit_mounts(mounts),
            "Dismount existing LambCrypt or VeraCrypt volumes before the native trial")
    require(not any(Path(line.strip()).name.lower() in {"lambcrypt", "lambcrypt-fskit", "veracrypt"}
                    for line in processes.splitlines()),
            "Close other LambCrypt or VeraCrypt processes before the native trial")


def format_target(records, image_path, prior, current, size):
    attachment = exact_attachment(records, image_path)
    devices = attachment_devices(attachment)
    require(len(devices) == 1 and attachment.get("writeable") is True,
            "Formatting requires one writable, unpartitioned Disk Images device")
    device, = devices
    entry = current.get(device, {})
    identity = entry.get("IORegistryEntryID")
    require(WHOLE.fullmatch(device) and device not in prior and identity
            and entry.get("Whole") is True and entry.get("Writable") is True and entry.get("Size") == size
            and not devices[device].get("mount-point"),
            f"Refusing to format {device}: disposable whole-media ownership was not established")
    require(all(device not in [entity.get("dev-entry") for entity in rec.get("system-entities", [])]
                for rec in records if rec is not attachment),
            f"Refusing to format {device}: another Disk Images attachment claims it")
    return device, identity


def require_virtual_whole_disk(device, information):
    require(information.get("BusProtocol") == "Disk Image" and information.get("VirtualOrPhysical") == "Virtual"
            and information.get("WholeDisk") is True and information.get("Internal") is False
            and information.get("DeviceNode") == device,
            "Disk Arbitration did not identify the target as a virtual Disk Images whole disk")


def fixture_identity(path, root, size):
    info = path.lstat()
    require(path.parent == root and root.stat().st_uid == os.getuid()
            and not root.stat().st_mode & 0o077
            and stat.S_ISREG(info.st_mode) and info.st_uid == os.getuid()
            and info.st_nlink == 1 and info.st_size == size,
            f"Expected a newly created private regular fixture at {path}")
    return info.st_dev, info.st_ino


def file_hash(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def wait_for(observe, seconds=15):
    deadline = time.monotonic() + seconds
    while True:
        try:
            return observe()
        except (OSError, RuntimeError, subprocess.SubprocessError, KeyError, ValueError):
            if time.monotonic() >= deadline:
                raise
        time.sleep(0.25)


@dataclass
class Attachment:
    auxiliary: Path
    endpoint: Path
    pid: int
    started: str
    mountpoint: Path | None = None

    @property
    def image(self):
        return self.auxiliary / "volume.dmg"


class Trial:
    def __init__(self, args, filesystem):
        self.args = args
        self.filesystem = filesystem
        # Small APFS containers can have a one-volume limit on macOS.
        self.size = (1024 if args.apfs_multiple else 256 if filesystem == "apfs" else 96) << 20
        self.image_size = self.size - (256 << 10)  # Normal VeraCrypt header areas.
        self.root = Path(tempfile.mkdtemp(prefix=f"lambcrypt-{filesystem}-trial-", dir="/private/tmp"))
        print(f"Artifacts: {self.root}", flush=True)
        self.volume = self.root / "disposable.hc"
        self.custom_mount = self.root / "mount"
        self.custom_mount.mkdir()
        self.env = dict(os.environ, XDG_CONFIG_HOME=str(self.root / "config"))
        config = self.root / "config" / "LambCrypt"
        config.mkdir(parents=True)
        (config / "Configuration.xml").write_text(
            '<VeraCrypt><configuration><config key="MountFavoritesOnLogon">0</config>'
            '<config key="MountDevicesOnLogon">0</config><config key="OpenExplorerWindowAfterMount">0</config>'
            '<config key="SaveHistory">0</config></configuration></VeraCrypt>')
        self.prior_media = media()
        self.evidence("initial", mount_table(), inventory(), self.prior_media)

    def evidence(self, label, mounts, records, devices):
        (self.root / f"{label}-mounts.txt").write_text(mounts)
        (self.root / f"{label}-images.plist").write_bytes(plistlib.dumps(records))
        # Save the media identities and geometry without the large registry properties.
        fields = ("IORegistryEntryID", "IOObjectClass", "Base", "Size", "Whole", "Writable")
        summary = {name: {key: record[key] for key in fields if key in record}
                   for name, record in devices.items()}
        (self.root / f"{label}-media.plist").write_bytes(plistlib.dumps(summary))

    def run(self, label, *arguments, timeout=90, expected=0):
        log = self.root / f"{label}.log"
        try:
            result = subprocess.run(arguments, env=self.env, capture_output=True, timeout=timeout)
        except subprocess.TimeoutExpired as error:
            log.write_bytes((error.stdout or b"") + (error.stderr or b""))
            raise
        log.write_bytes(result.stdout + result.stderr)
        require(result.returncode == expected, f"{label} exited {result.returncode}; see {log}")
        return (result.stdout + result.stderr).decode(errors="replace")

    def vc(self, label, *arguments, expected=0):
        return self.run(label, self.args.binary, "--text", "--non-interactive", *arguments, expected=expected)

    def holders(self):
        return set(map(int, command("/usr/sbin/lsof", "-t", str(self.volume)).split()))

    def check_worker(self, active):
        require(fixture_identity(self.volume, self.root, self.size) == self.backing,
                "The disposable encrypted fixture changed identity")
        require(self.holders() == {active.pid}
                and command("/bin/ps", "-p", str(active.pid), "-o", "lstart=").decode().strip() == active.started,
                "The disposable encrypted fixture is no longer held by the same worker")
        require(stat.S_ISSOCK(active.endpoint.lstat().st_mode), "The worker socket is unavailable")
        with self.volume.open("rb") as stream:
            try:
                fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                return
        raise RuntimeError("The worker did not retain the backing-file reservation")

    def mount(self, label, *, attach_only=False, read_only=False, default=False):
        require_empty_session(mount_table(), command("/bin/ps", "-axo", "comm=").decode())
        require_no_retained_fskit_image()
        target = ["--filesystem=none"] if attach_only else [] if default else [self.custom_mount]
        self.vc(label, "--mount", self.volume, *target, "--password=" + PASSWORD,
                "--pim=0", "--keyfiles=", "--protect-hidden=no", *(["--mount-options=ro"] if read_only else []))
        mounts = mount_table()
        auxiliary, = fskit_mounts(mounts)
        row, = (line for line in mounts.splitlines() if f" on {auxiliary} (lambcryptfs," in line)
        source = urlsplit(row.split(f" on {auxiliary} (", 1)[0])
        resource = Path(unquote(source.path))
        require(auxiliary.parent.parent == Path("/private/tmp")
                and auxiliary.parent.name.startswith("lambcrypt-fskit.")
                and source.scheme == "file" and not source.netloc
                and resource.is_absolute() and resource.name == auxiliary.parent.name,
                "Unexpected FSKit auxiliary mount or worker endpoint")
        pid, = self.holders()
        active = Attachment(auxiliary, resource / "io", pid,
                            command("/bin/ps", "-p", str(pid), "-o", "lstart=").decode().strip())
        self.check_worker(active)
        self.evidence(label, mounts, inventory(), media())
        (self.root / f"{label}-worker.plist").write_bytes(plistlib.dumps({
            "pid": active.pid, "started": active.started, "auxiliary": str(auxiliary),
            "endpoint": str(active.endpoint), "file-device": self.backing[0],
            "file-inode": self.backing[1], "file-size": self.size, "image-size": self.image_size,
        }))
        return active

    def format(self, active):
        require(active.image.stat().st_size == self.image_size, "Unexpected decrypted image geometry")
        self.check_worker(active)
        device, identity = format_target(inventory(), active.image, self.prior_media, media(), self.image_size)
        disk = plistlib.loads(command("/usr/sbin/diskutil", "info", "-plist", device))
        require_virtual_whole_disk(device, disk)
        raw = Path("/dev/r" + device.removeprefix("/dev/"))
        # This is the same private directory lock used by LambCrypt teardown.
        # The formatter needs exclusive access, so release the raw probe before
        # the final ownership check and keep the worker lock through formatting.
        lock = os.open(active.auxiliary.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            fd = os.open(raw, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW | os.O_CLOEXEC)
            try:
                state = os.fstat(fd)
                require(stat.S_ISCHR(state.st_mode) and state.st_rdev == raw.stat().st_rdev,
                        "The raw disk changed while opening it")
            finally:
                os.close(fd)
            mounts = mount_table()
            require(fskit_mounts(mounts) == {active.auxiliary}, "Another FSKit volume became active")
            require(not any(row.startswith(device + " on ") for row in mounts.splitlines()),
                    "The disposable whole disk already has a mounted filesystem")
            self.check_worker(active)
            require(format_target(inventory(), active.image, self.prior_media, media(), self.image_size)
                    == (device, identity), "The exact attachment changed before formatting")
            if self.filesystem == "exfat":
                self.run("format", "/sbin/newfs_exfat", "-v", "LCEXFAT", raw)
            else:
                self.run("format", "/usr/sbin/diskutil", "partitionDisk", device, "GPT", "APFS", "LCAPFS", "0")
                if self.args.apfs_multiple:
                    def container_identity():
                        records, devices = inventory(), media()
                        _, whole, _, container = self.layout(active, records, devices)
                        require(whole == device and devices[whole]["IORegistryEntryID"] == identity
                                and container not in self.prior_media,
                                "The APFS container does not belong to the disposable media")
                        return container, devices[container]["IORegistryEntryID"]

                    expected = wait_for(container_identity)
                    self.check_worker(active)
                    require(container_identity() == expected, "The disposable APFS container changed identity")
                    self.run("add-apfs-volume", "/usr/sbin/diskutil", "apfs", "addVolume",
                             expected[0], "APFS", "LCAPFSSecond", "-nomount")
        finally:
            os.close(lock)
        return device, identity

    def layout(self, active, records, devices, volume_count=1):
        attachment = exact_attachment(records, active.image)
        entities = attachment_devices(attachment)
        require(all(device in devices and devices[device].get("IORegistryEntryID") for device in entities),
                "A Disk Images child is missing its I/O Registry media")
        if self.filesystem == "exfat":
            whole, = entities
            require(WHOLE.fullmatch(whole) and devices[whole]["Size"] == self.image_size,
                    "Unexpected unpartitioned exFAT layout")
            return attachment, whole, (whole,), None

        whole, = (dev for dev, entry in entities.items() if entry.get("content-hint") == "GUID_partition_scheme")
        require(WHOLE.fullmatch(whole) and devices[whole]["Size"] == self.image_size,
                "Unexpected APFS GUID whole-disk geometry")
        partitions = {dev for dev in entities if dev.startswith(whole + "s")}
        require(partitions, "No physical GPT partitions were reported")
        for dev in partitions:
            start, size = devices[dev]["Base"], devices[dev]["Size"]
            require(0 < start < start + size <= self.image_size, f"Partition exceeds fixture geometry: {dev}")
        containers = plistlib.loads(command("/usr/sbin/diskutil", "apfs", "list", "-plist"))["Containers"]
        container, = (entry for entry in containers if any("/dev/" + store["DeviceIdentifier"] in partitions
                      for store in entry["PhysicalStores"]))
        store, = container["PhysicalStores"]
        children = tuple("/dev/" + volume["DeviceIdentifier"] for volume in container["Volumes"])
        physical = "/dev/" + store["DeviceIdentifier"]
        synthesized = "/dev/" + container["ContainerReference"]
        require(len(children) == volume_count and physical in partitions
                and set(entities) == {whole, *partitions, synthesized, *children}
                and devices[synthesized]["IOObjectClass"] == "AppleAPFSMedia"
                and all(devices[child]["IOObjectClass"] == "AppleAPFSVolume" for child in children),
                "APFS entities do not all resolve to the disposable image's single physical store")
        return attachment, whole, children, synthesized

    def verify_mount(self, active, label, *, read_only=False, default=False):
        self.check_worker(active)
        mounts, records, devices = mount_table(), inventory(), media()
        attachment, whole, (child,), _ = self.layout(active, records, devices)
        entities = attachment_devices(attachment)
        require(attachment.get("writeable") is (not read_only), "Unexpected Disk Images write protection")
        point = Path(entities[child]["mount-point"])
        require(point != active.auxiliary and (point.parent == Path("/Volumes") if default else point == self.custom_mount),
                f"Unexpected inner filesystem mount directory: {point}")
        prefix = f"{child} on {point} ({self.filesystem}, "
        line, = (row for row in mounts.splitlines() if row.startswith(prefix))
        require(("read-only" in line[len(prefix):].removesuffix(")").split(", ")) == read_only,
                "Unexpected inner filesystem access mode")
        require([dev for dev, item in entities.items() if item.get("mount-point")] == [child],
                "The exact image exposed an unexpected additional mount")
        active.mountpoint = point
        listing = self.vc(label + "-list", "--list", "--verbose", self.volume)
        require(str(point) in listing and str(self.volume) in listing, "LambCrypt did not list the inner volume")
        self.evidence(label, mounts, records, devices)
        return whole

    def verify_closed(self, active, label, identities, seconds=15):
        def closed():
            mounts, records, devices = mount_table(), inventory(), media()
            require(not fskit_mounts(mounts) and not active.auxiliary.parent.exists() and not active.endpoint.exists(),
                    "The auxiliary mount or worker endpoint remains")
            require(not active.mountpoint or f" on {active.mountpoint} (" not in mounts, "The inner mount remains")
            require(not any(Path(record["image-path"]).resolve() == active.image for record in records),
                    "Disk Images still retains the fixture")
            require(identities.isdisjoint(entry.get("IORegistryEntryID") for entry in devices.values()),
                    "An original disk image media object remains")
            holders = subprocess.run(["/usr/sbin/lsof", "-t", self.volume], capture_output=True, timeout=10)
            require(holders.returncode == 1 and not holders.stdout and not holders.stderr, "Fixture handles remain")
            process = subprocess.run(["/bin/ps", "-p", str(active.pid), "-o", "lstart="],
                                     capture_output=True, text=True, timeout=10)
            require(process.stdout.strip() != active.started, "The original worker is still running")
            with self.volume.open("rb") as stream:
                fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
            self.evidence(label, mounts, records, devices)
        wait_for(closed, seconds)

    def identities(self, active):
        records, devices = inventory(), media()
        return {devices[device]["IORegistryEntryID"] for device in
                attachment_devices(exact_attachment(records, active.image))}

    def unmount(self, active, label):
        identities = self.identities(active)
        self.vc(label, "--unmount", self.volume)
        self.verify_closed(active, label + "-closed", identities)

    def write_tree(self, active):
        point = active.mountpoint
        tree = point / "temporary"
        (tree / "retained").mkdir(parents=True)
        (tree / "discard").write_bytes(b"disposable")
        (tree / "discard").unlink()
        tree.rename(point / PAYLOAD.parts[0])
        path = point / PAYLOAD
        rng = random.Random(42)
        payload = bytearray(rng.randbytes(1 << 20))
        original = path.with_name("original.bin")
        with original.open("w+b") as stream:
            require(stream.write(payload) == len(payload), "Initial write was short")
            for offset in (511, 4093, *rng.sample(range(8192, len(payload) - 4096), 16)):
                patch = rng.randbytes(777)
                stream.seek(offset)
                require(stream.write(patch) == len(patch), "Overwrite was short")
                payload[offset:offset + len(patch)] = patch
            stream.truncate(700_003)
            stream.truncate(800_007)
            payload = payload[:700_003] + bytes(100_004)
            os.utime(original, (MTIME, MTIME))
            if self.filesystem == "apfs":
                self.run("xattr-write", "/usr/bin/xattr", "-wx", XATTR, XATTR_DATA.hex(), original)
            stream.flush()
            os.fsync(stream.fileno())
            original.rename(path)
            result = self.vc("busy-unmount", "--unmount", self.volume, expected=1)
            require("The volume is in use." in result, "Busy dismount did not report the open file")
            self.verify_mount(active, "busy-retained")
            stream.seek(0)
            require(stream.read() == payload, "Open file changed during refused dismount")
        return hashlib.sha256(payload).hexdigest()

    def verify_readonly(self, active, expected_hash):
        point = active.mountpoint
        payload = point / PAYLOAD
        require(file_hash(payload) == expected_hash and abs(payload.stat().st_mtime - MTIME) <= 2,
                "Payload hash or timestamp changed after read-only remount")
        require(not any(path.exists() for path in
                        (payload.with_name("original.bin"), point / "temporary", point / PAYLOAD.parts[0] / "discard")),
                "Renamed or deleted entries changed after remount")
        if self.filesystem == "apfs":
            value = self.run("xattr-readonly", "/usr/bin/xattr", "-px", XATTR, payload)
            require(bytes.fromhex(value) == XATTR_DATA, "APFS extended attribute changed")
        try:
            with payload.open("r+b"):
                pass
        except OSError as error:
            require(error.errno == errno.EROFS, f"Read-only access returned unexpected error: {error}")
        else:
            raise RuntimeError("Read-only mount permitted opening the payload for writing")

    def reject_multiple_volumes(self):
        before = {record["IORegistryEntryID"] for record in media().values()}
        result = self.vc("mount-multiple", "--mount", self.volume, "--password=" + PASSWORD,
                         "--pim=0", "--keyfiles=", "--protect-hidden=no", expected=1)
        require("requires one APFS container and one volume" in result, "APFS rejection did not explain the layout")
        mounts, records, devices = mount_table(), inventory(), media()
        self.evidence("reject-multiple-closed", mounts, records, devices)
        require(not fskit_mounts(mounts)
                and all(record["IORegistryEntryID"] in before for record in devices.values()),
                "APFS rejection retained a mount or published media")
        require_no_retained_fskit_image()
        self.run("multiple-worker-closed", "/usr/sbin/lsof", self.volume, expected=1)
        with self.volume.open("rb") as stream:
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        print("PASS: ordinary mount refused two APFS volumes and released the backing image", flush=True)

    def execute(self):
        require(not self.volume.exists(), "Refusing to overwrite a fixture")
        self.vc("create", "--create", self.volume, f"--size={self.size}", "--volume-type=normal", "--encryption=AES",
                "--hash=sha512", "--filesystem=none", "--password=" + PASSWORD, "--pim=0",
                "--keyfiles=", "--random-source=/dev/urandom")
        self.backing = fixture_identity(self.volume, self.root, self.size)
        active = self.mount("attach-blank", attach_only=True)
        whole, identity = self.format(active)
        def formatted_layout():
            records, devices = inventory(), media()
            _, detected_whole, _, _ = self.layout(active, records, devices, 2 if self.args.apfs_multiple else 1)
            require(detected_whole == whole and devices[whole]["IORegistryEntryID"] == identity,
                    "Formatting did not preserve the disposable image's whole-media identity")
            self.evidence("formatted", mount_table(), records, devices)
        wait_for(formatted_layout)
        self.unmount(active, "detach-formatted")
        if self.args.apfs_multiple:
            self.reject_multiple_volumes()
            return

        active = self.mount("mount-write")
        self.verify_mount(active, "mounted-write")
        expected_hash = self.write_tree(active)
        self.unmount(active, "unmount-write")
        encrypted = file_hash(self.volume)
        (self.root / "checksums.txt").write_text(f"payload {expected_hash}\nencrypted after write {encrypted}\n")

        active = self.mount("mount-readonly", read_only=True, default=True)
        whole = self.verify_mount(active, "mounted-readonly", read_only=True, default=True)
        self.verify_readonly(active, expected_hash)
        plaintext = file_hash(active.image)
        identities = self.identities(active)
        self.run("disk-arbitration-eject", "/usr/sbin/diskutil", "eject", whole, timeout=30)
        self.verify_closed(active, "disk-arbitration-eject-closed", identities)
        require(file_hash(self.volume) == encrypted, "Read-only remount changed the encrypted fixture")

        if self.args.reader:
            output = self.root / "upstream.plain"
            with output.open("xb") as decrypted, (self.root / "independent-verify.log").open("wb") as errors:
                subprocess.run([self.args.reader, self.volume, PASSWORD, "0"],
                               stdout=decrypted, stderr=errors, timeout=300, check=True)
            require(output.stat().st_size == self.image_size and file_hash(output) == plaintext,
                    "Independent VeraCrypt plaintext does not match the complete decrypted image")
            require(file_hash(self.volume) == encrypted, "Independent reader changed the encrypted fixture")
            (self.root / "independent.sha256").write_text(plaintext + "\n")
            output.unlink()

        if self.args.finder_eject:
            active = self.mount("mount-finder", default=True)
            self.verify_mount(active, "mounted-finder", default=True)
            identities = self.identities(active)
            print(f"Eject the disposable {self.filesystem} volume in Finder at {active.mountpoint}", flush=True)
            self.verify_closed(active, "finder-eject-closed", identities, seconds=90)
        complete = self.args.reader and self.args.finder_eject
        print(f"{'PASS' if complete else 'PARTIAL'}: {self.filesystem} integrated write, busy retry, read-only hash, "
              "Disk Arbitration eject and cleanup. See the trial artifacts.", flush=True)


def signing_team(path):
    result = subprocess.run(["/usr/bin/codesign", "-dv", path], capture_output=True, text=True, check=True, timeout=10)
    team, = (line.partition("=")[2] for line in result.stderr.splitlines() if line.startswith("TeamIdentifier="))
    require(team != "not set", "Code must be team signed")
    return team


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument("--fskit-exfat", action="store_const", const="exfat", dest="filesystem")
    modes.add_argument("--fskit-apfs", action="store_const", const="apfs", dest="filesystem")
    parser.add_argument("--isolated-host", action="store_true", required=True)
    parser.add_argument("--binary", required=True, type=Path)
    parser.add_argument("--activation-probe", required=True, type=Path)
    parser.add_argument("--reader", type=Path,
                        help="Upstream VeraCrypt reader taking VOLUME PASSWORD PIM and writing plaintext to stdout")
    parser.add_argument("--finder-eject", action="store_true", help="Wait for native Finder eject of a writable mount")
    parser.add_argument("--apfs-multiple", action="store_true",
                        help="Create two disposable APFS volumes and verify ordinary mount rejection")
    parser.add_argument("--build-commit", required=True, help="Source commit or base commit and patch digest of the signed app")
    args = parser.parse_args()
    if args.apfs_multiple and (args.filesystem != "apfs" or args.finder_eject or args.reader):
        parser.error("--apfs-multiple requires --fskit-apfs and runs the layout rejection trial alone")
    if not __debug__ or sys.platform != "darwin" or os.uname().machine != "arm64" or os.geteuid() == 0:
        parser.error("Run as a regular user on Apple Silicon macOS with Python checks enabled")
    version = command("/usr/bin/sw_vers", "-productVersion").decode().strip()
    require(int(version.split(".")[0]) >= 26, "macOS 26 or later is required")
    args.binary = args.binary.resolve(strict=True)
    args.activation_probe = args.activation_probe.resolve(strict=True)
    if args.reader:
        args.reader = args.reader.resolve(strict=True)
    app = args.binary.parents[2]
    extension = app / "Contents/Extensions/LambCryptFSKit.appex"
    require(app.suffix == ".app" and args.binary.parent.name == "MacOS" and is_fskit(args.binary)
            and Path("/Applications") not in app.parents and Path("/System") not in app.parents
            and (extension / "Contents/embedded.provisionprofile").is_file(),
            "Use a provisioned scratch FSKit app outside the installed app locations")
    command("/usr/bin/codesign", "--verify", "--deep", "--strict", str(app))
    command("/usr/bin/codesign", "--verify", "--strict", str(args.activation_probe))
    require(signing_team(app) == signing_team(extension) == signing_team(args.activation_probe),
            "The app, extension and FSClient probe must be signed by the same team")
    require_empty_session(mount_table(), command("/bin/ps", "-axo", "comm=").decode())
    require_no_retained_fskit_image()
    result = subprocess.run([args.activation_probe, app], stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            text=True, timeout=12)
    activation = result.stdout
    require(result.returncode == 0 and f"enabled=true {extension}" in activation,
            "FSClient did not confirm the exact scratch module. " + activation.strip())
    trial = Trial(args, args.filesystem)
    (trial.root / "host-build.txt").write_text(
        command("/usr/bin/sw_vers").decode() + f"Architecture: {os.uname().machine}\n"
        f"Reported source commit: {args.build_commit}\nBinary: {args.binary}\nSHA-256: {file_hash(args.binary)}\n"
        f"{activation}")
    try:
        trial.execute()
    except Exception:
        try:
            trial.evidence("failure", mount_table(), inventory(), media())
        except Exception as evidence_error:
            print(f"Could not capture final inventory: {evidence_error}", file=sys.stderr)
        raise


if __name__ == "__main__":
    main()
