#!/usr/bin/env python3
"""Run the production FSKit worker with real Disk Images and an injected mount observation.

The disposable raw images are backed by APFS. This trial needs a matching
FSKit build to create encrypted fixtures, and runs without loading an extension
or unmounting a real filesystem to induce auxiliary loss.
"""

import argparse
from datetime import datetime
import fcntl
import os
from pathlib import Path
import plistlib
import re
import shutil
import socket
import struct
import subprocess
import sys
import tempfile
import time

from test_fskit_volume_protocol import ROOT, SIGNATURE, exchange, inspect_worker
from test_macos_gui_lifecycle import require_no_retained_fskit_image


HDIUTIL = "/usr/bin/hdiutil"
PASSWORD = "disposable-worker-lifecycle-test"


def build_probe(build, probe):
    src = ROOT / "src"
    subprocess.run([
        "xcrun", "clang++", "-std=c++11", "-O2", "-DTC_UNIX", "-DTC_BSD", "-DTC_MACOSX",
        "-DVC_MACOSX_FSKIT", "-DARGON2_NO_THREADS", "-D_FILE_OFFSET_BITS=64",
        "-I", src, "-I", src / "Crypto", "-I", src / "Crypto/Argon2/include",
        "-I", src / "PKCS11", ROOT / "Tests/macos_fskit_worker_lifecycle_test.mm",
        build / "Core/Core.a", build / "Driver/Fuse/Driver.a", build / "Volume/Volume.a",
        build / "Platform/Platform.a", "-Wl,-dead_strip", "-framework", "CoreFoundation",
        "-framework", "Foundation", "-framework", "FSKit", "-framework", "IOKit",
        "-framework", "DiskArbitration", "-framework", "Security", "-o", probe,
    ], check=True, timeout=90)


def attached_device(image):
    inventory = plistlib.loads(subprocess.check_output([HDIUTIL, "info", "-plist"], timeout=8))
    records = inventory["images"]
    if not isinstance(records, list) or any(
        not isinstance(row, dict) or not isinstance(row.get("image-path"), str) or not row["image-path"]
        for row in records
    ):
        raise RuntimeError("Disk Images returned an incomplete inventory")
    matches = [row for row in records if row["image-path"] == str(image)]
    if not matches:
        return None
    record, = matches
    if record["writeable"] is not False or any(row.get("mount-point") for row in record["system-entities"]):
        raise RuntimeError("The fixture attachment was expected to be read-only and unmounted")
    device, = (row["dev-entry"] for row in record["system-entities"]
               if re.fullmatch(r"/dev/disk[0-9]+", row.get("dev-entry", "")))
    return device


class Worker:
    def __init__(self, root, slot, probe, binary):
        self.root = root / str(slot)
        self.probe = probe
        self.root.mkdir(mode=0o700)
        self.endpoint = self.root / "socket"
        self.endpoint.mkdir(mode=0o700)
        self.image = self.root / "aux/volume.dmg"
        self.image.parent.mkdir(mode=0o700)
        self.volume = self.root / "volume.hc"
        self.attachment = None
        group = root / "group"
        group.mkdir(mode=0o700, exist_ok=True)
        with (self.root / "create.log").open("wb") as log:
            subprocess.run([
                binary, "--text", "--non-interactive", "--create", self.volume, "--size=4194304",
                "--volume-type=normal", "--encryption=AES", "--hash=sha512", "--filesystem=FAT",
                f"--password={PASSWORD}", "--pim=1", "--keyfiles=", "--random-source=/dev/urandom",
            ], env={**os.environ, "XDG_CONFIG_HOME": str(root / "prefs")},
                stdout=log, stderr=subprocess.STDOUT, check=True, timeout=30)
        st = self.volume.stat()
        self.reservations = [group / "mount-locks" / name
                             for name in (f"slot-{slot}", f"file-{st.st_dev}-{st.st_ino}")]
        self.present = self.root / "auxiliary-present"
        self.present.touch()
        self.channel, child = socket.socketpair()
        with child, (self.root / "worker.log").open("wb") as log:
            self.process = subprocess.Popen([probe, self.root, group, str(slot), str(child.fileno()), PASSWORD],
                                            pass_fds=(child.fileno(),), stdout=log, stderr=subprocess.STDOUT,
                                            start_new_session=True)

    def wait_for(self, name, seconds=15):
        deadline = time.monotonic() + seconds
        while not (self.root / name).exists():
            status = self.process.poll()
            if status is not None:
                raise RuntimeError(f"Worker {self.process.pid} exited with {status} before reaching {name}")
            if time.monotonic() >= deadline:
                raise RuntimeError(f"Worker {self.process.pid} timed out before reaching {name}")
            time.sleep(0.05)

    def start(self):
        self.wait_for("socket-ready")
        self.generation = inspect_worker(self.endpoint)
        size, _, identifier, read_only = self.generation
        assert size > 512 and read_only == 1
        (self.root / "worker-identity.txt").write_text(f"{self.process.pid} {identifier.hex()}\n")
        self.channel.sendall(b"\x01")
        self.wait_for("auxiliary-observed")
        with self.image.open("xb") as image:
            for offset in range(0, size, 128 * 1024):
                length = min(128 * 1024, size - offset)
                image.write(self.read_image(offset, length))

    def read_image(self, offset, length):
        packet = struct.pack("<IIQII16s", SIGNATURE, 2, offset, length, 0, self.generation[2])
        reply = exchange(self.endpoint, packet)
        assert len(reply) == length + 8 and struct.unpack_from("<II", reply) == (0, length)
        return reply[8:]

    def media_id(self, device):
        return int(subprocess.check_output([self.probe, "--media-id", device], timeout=5))

    def attach(self):
        with (self.root / "attach.plist").open("wb") as log:
            subprocess.run([HDIUTIL, "attach", self.image, "-readonly", "-nomount", "-plist",
                            "-imagekey", "diskimage-class=CRawDiskImage"],
                           stdout=log, check=True, timeout=25)
        device = attached_device(self.image)
        if device is None:
            raise RuntimeError("Disk Images did not publish the fixture attachment")
        self.attachment = device, self.media_id(device)
        (self.root / "attachment.txt").write_text(
            f"{datetime.now().astimezone().isoformat()} {device} {self.attachment[1]}\n")

    def check_reservations(self, locked):
        for path in self.reservations:
            with path.open("rb") as lock:
                try:
                    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError:
                    assert locked, f"Reservation remained held: {path.name}"
                else:
                    assert not locked, f"Reservation released early: {path.name}"

    def check_retained(self):
        assert self.process.poll() is None
        assert inspect_worker(self.endpoint) == self.generation
        with self.image.open("rb") as raw:
            assert self.read_image(0, 512) == raw.read(512)
        self.check_reservations(locked=True)
        if self.attachment:
            device, media = self.attachment
            assert attached_device(self.image) == device and self.media_id(device) == media

    def detach(self):
        device, media = self.attachment
        if attached_device(self.image) != device or self.media_id(device) != media:
            raise RuntimeError("Fixture attachment identity changed before detach")
        subprocess.run([HDIUTIL, "detach", device], check=True, timeout=20)
        if attached_device(self.image) is not None:
            raise RuntimeError("Disk Images did not release the fixture")
        self.attachment = None

    def check_closed(self):
        assert self.process.wait(timeout=12) == 0
        assert not self.endpoint.exists() and attached_device(self.image) is None
        self.check_reservations(locked=False)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build-dir", type=Path, required=True, help="src directory of matching FSKit build")
    parser.add_argument("--keep-artifacts", action="store_true")
    args = parser.parse_args()
    if sys.platform != "darwin" or os.uname().machine != "arm64" or os.geteuid() == 0:
        parser.error("Run as an ordinary user on Apple Silicon macOS")
    require_no_retained_fskit_image()
    build = args.build_dir.resolve(strict=True)
    binary = (build / "Main/LambCrypt-FSKit.app/Contents/MacOS/LambCrypt-FSKit").resolve(strict=True)
    root = Path(tempfile.mkdtemp(prefix="lambcrypt-worker.", dir="/private/tmp"))
    print(f"Artifacts: {root}", flush=True)
    (root / "prefs/LambCrypt").mkdir(parents=True)
    probe = root / "worker"
    build_probe(build, probe)

    workers = []
    try:
        for slot in (1, 2):
            worker = Worker(root, slot, probe, binary)
            workers.append(worker)
            worker.start()
        known, late = workers
        assert known.generation[2] != late.generation[2]
        known.channel.sendall(struct.pack("<Q", 2**64 - 1))
        known.attach()
        known.present.unlink()
        known.channel.sendall(struct.pack("<Q", known.attachment[1]))
        known.channel.close()
        known.wait_for("image-attached")
        known.check_retained()

        late.channel.sendall(struct.pack("<Q", 2**64 - 1))
        late.present.unlink()
        late.channel.close()
        late.wait_for("image-absent")
        late.check_retained()
        late.attach()
        assert known.attachment[1] != late.attachment[1]
        late.wait_for("image-attached")
        late.check_retained()
        known.check_retained()

        known.detach()
        known.check_closed()
        late.check_retained()
        late.detach()
        late.check_closed()
    finally:
        for worker in workers:
            worker.present.unlink(missing_ok=True)
            worker.channel.close()
    if not args.keep_artifacts:
        shutil.rmtree(root)
    print("PASS: two native attachments, injected auxiliary loss, late publication, "
          "independent workers, and socket and reservation release")


if __name__ == "__main__":
    main()
