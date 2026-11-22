#!/usr/bin/env python3
"""Disposable macOS container and background GUI lifecycle; no sudo required.

Requires a logged-in macOS desktop and no other LambCrypt or VeraCrypt processes or mounts.
Uses only a disposable container, isolated preferences, and a local app bundle.
No fault injection, device reassignment, or forced unmount is performed.
The default tests FUSE-T. Select --fskit-external-eject for signed FSKit and HFS+.
"""
import argparse
import errno
import fcntl
import hashlib
import os
from pathlib import Path
import plistlib
import re
import shutil
import subprocess
import sys
import tempfile
import time


def is_fskit(binary):
    if binary.name.lower() == "lambcrypt-fskit":
        return True
    contents = binary.parent.parent
    plist = contents / "Info.plist"
    if binary.parent.name == "MacOS" and contents.name == "Contents" and plist.is_file():
        return "LambCryptFSKitIPCGroup" in plistlib.loads(plist.read_bytes())
    return False


def fskit_mounts(mount_table):
    paths = set()
    for line in mount_table.splitlines():
        target, _, flags = line.rpartition(" (")
        if flags.startswith("lambcryptfs,"):
            paths.add(Path(target.rpartition(" on ")[2]))
    return paths


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", required=True, type=Path)
    parser.add_argument("--release-binary", type=Path,
                        help="Create and verify the container with this released FUSE-T client")
    parser.add_argument("--cli-only", action="store_true",
                        help="Verify the container round trip without launching the background GUI")
    parser.add_argument("--fskit-external-eject", action="store_true",
                        help="Test a signed FSKit bundle with HFS+ and Disk Arbitration eject")
    parser.add_argument("--keep-artifacts", action="store_true")
    args = parser.parse_args()
    binary = args.binary.resolve(strict=True)
    release = args.release_binary.resolve(strict=True) if args.release_binary else binary
    if args.fskit_external_eject:
        if (not is_fskit(binary) or binary.parent.name != "MacOS" or binary.parents[2].suffix != ".app"
                or args.cli_only or args.release_binary):
            parser.error("--fskit-external-eject requires a signed FSKit bundle and the background GUI")
        subprocess.run(["/usr/bin/codesign", "--verify", "--deep", "--strict", binary.parents[2]],
                       check=True, timeout=10)
    elif is_fskit(binary) or is_fskit(release):
        parser.error("the FUSE-T check uses FAT. For FSKit, use --fskit-external-eject with the signed app")

    def mounts():
        return subprocess.check_output(["/sbin/mount"], text=True, timeout=8)

    initial_mounts = mounts()
    if ".veracrypt_aux_mnt" in initial_mounts or fskit_mounts(initial_mounts):
        raise RuntimeError("Dismount existing LambCrypt or VeraCrypt volumes before this isolated GUI test")
    processes = subprocess.check_output(["/bin/ps", "-axo", "comm="], text=True)
    if any(Path(line.strip()).name.lower() in {"lambcrypt", "lambcrypt-fskit", "veracrypt"}
           for line in processes.splitlines()):
        raise RuntimeError("Close other LambCrypt or VeraCrypt processes before this isolated GUI test")

    root = Path(tempfile.mkdtemp(prefix="vc-gui-lifecycle-")).resolve()
    print("Artifacts:", root, flush=True)
    temporary = root / "tmp"
    mountpoint = root / "mount"
    config = root / "config" / "LambCrypt"
    temporary.mkdir(mode=0o700)
    mountpoint.mkdir()
    config.mkdir(parents=True)
    prefs = dict(BackgroundTaskEnabled=1, CloseBackgroundTaskOnNoVolumes=1,
                 DismountOnInactivity=0, DismountOnLogOff=1, DismountOnPowerSaving=0,
                 MountFavoritesOnLogon=0, MountDevicesOnLogon=0,
                 OpenExplorerWindowAfterMount=0, SaveHistory=0)
    (config / "Configuration.xml").write_text("<VeraCrypt><configuration>" + "".join(
        f'<config key="{key}">{value}</config>' for key, value in prefs.items()
    ) + "</configuration></VeraCrypt>")
    env = dict(os.environ, TMPDIR=str(temporary) + "/", XDG_CONFIG_HOME=str(root / "config"))
    executable = binary
    if not args.cli_only:
        contents = binary.parent.parent
        in_app_bundle = (binary.parent.name == "MacOS" and contents.name == "Contents"
                         and contents.parent.suffix == ".app" and (contents / "Info.plist").is_file())
        if not in_app_bundle:
            contents = root / "LambCryptTest.app" / "Contents"
            executable = contents / "MacOS" / "LambCrypt"
            executable.parent.mkdir(parents=True)
            shutil.copy2(binary, executable)
            (contents / "Info.plist").write_bytes(plistlib.dumps(dict(
                CFBundleExecutable="LambCrypt", CFBundleName="LambCrypt Lifecycle Test",
                CFBundleIdentifier=f"io.github.e3742526.LambCrypt.lifecycle-test.{os.getpid()}",
                CFBundlePackageType="APPL", NSHighResolutionCapable=True)))
    volume = root / "ordinary.hc"
    password = "Disposable-normal-lifecycle-only"
    gui = None
    active = None
    mount_client = binary
    succeeded = False

    def run(label, command, timeout=90, expected_returncode=0):
        result = subprocess.run(command, env=env, capture_output=True, text=True, timeout=timeout)
        (root / (label + ".log")).write_text(result.stdout + result.stderr)
        if result.returncode != expected_returncode:
            raise RuntimeError(f"{label} failed; see {root / (label + '.log')}")
        return result

    def vc(label, *options, client=binary):
        run(label, [client, "--text", "--non-interactive", *options])

    def mount(read_only=False, client=binary):
        nonlocal active, mount_client
        mount_client = client
        before = fskit_mounts(mounts()) if args.fskit_external_eject else set()
        vc("mount", "--mount", volume, mountpoint, "--password=" + password,
           "--pim=1", "--keyfiles=", "--protect-hidden=no",
           *(["--mount-options=ro"] if read_only else []), client=client)
        if args.fskit_external_eject:
            aux, = fskit_mounts(mounts()) - before
            assert aux.parent.as_posix().startswith("/private/tmp/lambcrypt-fskit."), aux
            workers = subprocess.check_output(["/usr/sbin/lsof", "-t", volume], text=True, timeout=8)
            pid, = {int(pid) for pid in workers.split()}
            active = (pid, aux, None)
            confirm_fskit_attachment(aux, read_only)
            return
        identities = list(temporary.glob("**/.veracrypt_aux_mnt*/shutdown"))
        assert len(identities) == 1, "Expected one disposable FUSE-T service"
        aux = identities[0].parent
        active = (int(identities[0].read_text().split()[0]), aux,
                  Path((aux / "shutdown-socket").read_text().strip()))

    def confirm_closed():
        if active:
            pid, aux, endpoint = active
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                pass
            else:
                raise AssertionError("Disposable service still running")
            assert not aux.exists() and not aux.parent.exists(), "Auxiliary mount or directory remains"
            assert endpoint is None or not endpoint.exists(), "Shutdown endpoint remains"
        assert str(root) not in mounts(), "Disposable mount remains"
        handles = subprocess.run(["/usr/sbin/lsof", "-t", str(volume)], capture_output=True, text=True)
        assert handles.returncode == 1 and not handles.stdout.strip(), "Backing file still open"

    def confirm_fskit_attachment(aux, read_only):
        inventory = subprocess.check_output(["/usr/bin/hdiutil", "info", "-plist"], timeout=8)
        image, = (image for image in plistlib.loads(inventory)["images"]
                  if image.get("image-path") == str(aux / "volume.dmg"))
        device, = (entity["dev-entry"] for entity in image["system-entities"]
                   if entity.get("mount-point") == str(mountpoint))
        assert re.fullmatch(r"/dev/disk[0-9]+(?:s[0-9]+)?", device), device
        table_entry = f"{device} on {mountpoint} (hfs,"
        line, = (line for line in mounts().splitlines() if line.startswith(table_entry))
        assert (", read-only" in line) == read_only, line

    xattr = "/usr/bin/xattr"
    xattr_name = "io.github.e3742526.LambCrypt.lifecycle"
    xattr_value = "00FF4C430A00"
    payload_path = mountpoint / "payload.bin"

    def check_xattr(label):
        result = run(label, [xattr, "-px", xattr_name, payload_path])
        assert bytes.fromhex(result.stdout) == bytes.fromhex(xattr_value)

    def check_writable_metadata(stream):
        run("xattr-create", [xattr, "-wx", xattr_name, "01", payload_path])
        run("xattr-replace", [xattr, "-wx", xattr_name, xattr_value, payload_path])
        check_xattr("xattr-before-remount")
        deleted = xattr_name + ".removed"
        run("xattr-create-to-delete", [xattr, "-w", deleted, "discard", payload_path])
        run("xattr-remove", [xattr, "-d", deleted, payload_path])
        assert deleted not in run("xattr-list", [xattr, payload_path]).stdout.splitlines()

        lock_probe = """
import errno
import fcntl
import sys

with open(sys.argv[1], 'r+b') as stream:
    try:
        fcntl.lockf(stream, fcntl.LOCK_EX | fcntl.LOCK_NB, 1, int(sys.argv[2]))
    except OSError as error:
        if error.errno not in (errno.EACCES, errno.EAGAIN):
            raise
        print(error.errno)
        sys.exit(1)
"""
        probe = [sys.executable, "-c", lock_probe, payload_path]
        # POSIX record locks are per process. A second open here cannot test contention.
        fcntl.lockf(stream, fcntl.LOCK_EX | fcntl.LOCK_NB, 1)
        conflict = run("lock-conflict", [*probe, "0"], timeout=8, expected_returncode=1)
        assert int(conflict.stdout.strip()) in (errno.EACCES, errno.EAGAIN)
        run("lock-adjacent-byte", [*probe, "1"], timeout=8)
        fcntl.lockf(stream, fcntl.LOCK_UN, 1)
        run("lock-after-release", [*probe, "0"], timeout=8)

    filesystem = "HFS+" if args.fskit_external_eject else "FAT"
    try:
        vc("create", "--create", volume, "--size=33554432", "--volume-type=normal",
           "--encryption=AES", "--hash=sha512", f"--filesystem={filesystem}", "--password=" + password,
           "--pim=1", "--keyfiles=", "--random-source=/dev/urandom", client=release)
        mount()
        payload = bytes(range(256)) * 4096
        with payload_path.open("wb") as stream:
            stream.write(payload)
            stream.flush()
            if args.fskit_external_eject:
                check_writable_metadata(stream)
            os.fsync(stream.fileno())
        vc("unmount-write", "--unmount", volume)
        confirm_closed()
        if args.release_binary or args.cli_only:
            mount(read_only=True, client=release)
            assert hashlib.sha256((mountpoint / "payload.bin").read_bytes()).digest() == hashlib.sha256(payload).digest()
            vc("unmount-release", "--unmount", volume, client=release)
            confirm_closed()
            print("PASS: create, write/fsync, read-only remount, payload integrity, service/file cleanup", flush=True)
        if args.cli_only:
            succeeded = True
            return
        mount(read_only=True)
        assert hashlib.sha256((mountpoint / "payload.bin").read_bytes()).digest() == hashlib.sha256(payload).digest()
        if args.fskit_external_eject:
            check_xattr("xattr-after-remount")
            assert xattr_name + ".removed" not in run("xattr-remount-list", [xattr, payload_path]).stdout.splitlines()
            denied = run("xattr-readonly-denied", [xattr, "-wx", xattr_name, "01", payload_path],
                         expected_returncode=1)
            assert f"[Errno {errno.EROFS}]" in denied.stderr, denied.stderr
            check_xattr("xattr-readonly-preserved")
            print("PASS: HFS+ binary xattrs and cross-process POSIX advisory locks", flush=True)
        with (root / "gui.log").open("w") as log:
            gui = subprocess.Popen([str(executable), "--background-task"], env=env,
                                   stdout=log, stderr=log, start_new_session=True)
        time.sleep(5)
        assert gui.poll() is None, "Background app exited with a mounted volume"
        if args.fskit_external_eject:
            confirm_fskit_attachment(active[1], read_only=True)
            run("external-eject", ["/usr/sbin/diskutil", "eject", mountpoint], timeout=30)
        else:
            vc("unmount-readonly", "--unmount", volume)
        assert gui.wait(timeout=20) == 0, "Background app did not exit cleanly"
        confirm_closed()
        succeeded = True
        print("PASS: payload integrity, initial background discovery, external-dismount refresh, automatic exit, service/file cleanup", flush=True)
    finally:
        if gui and gui.poll() is None:
            gui.terminate()
            gui.wait(timeout=10)
        if str(root) in mounts() or (active and active[1].exists()):
            vc("test-cleanup", "--unmount", volume, client=mount_client)
        if succeeded and not args.keep_artifacts:
            confirm_closed()
            shutil.rmtree(root)


if __name__ == "__main__":
    main()
