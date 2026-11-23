#!/usr/bin/env python3
"""Disposable macOS container and background GUI lifecycle; no sudo required.

Requires a logged-in macOS desktop and no other LambCrypt or VeraCrypt processes or mounts.
Uses only a disposable container, isolated preferences, and a local app bundle.
No fault injection, device reassignment, or forced unmount is performed.
The default tests FUSE-T. Select --fskit-external-eject for signed FSKit and HFS+.
Select --fskit-kernel-fat on an isolated Tahoe host for the signed FSKit CLI trial.
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
from xml.parsers.expat import ExpatError


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


def require_no_retained_fat_image():
    # Disk Arbitration can remove a mount-table row before it releases the image.
    try:
        inventory = plistlib.loads(subprocess.check_output(["/usr/bin/hdiutil", "info", "-plist"], timeout=8))
    except (OSError, subprocess.SubprocessError, ValueError, ExpatError) as error:
        raise RuntimeError("could not verify Disk Images inventory for the FAT trial") from error
    if not isinstance(inventory, dict) or not isinstance(inventory.get("images"), list):
        raise RuntimeError("Disk Images inventory is incomplete")
    for record in inventory["images"]:
        image = record.get("image-path") if isinstance(record, dict) else None
        if not isinstance(image, str) or not image:
            raise RuntimeError("Disk Images inventory is incomplete")
        directories = Path(image).parts[:-1]
        if any(part.startswith((".veracrypt_aux_mnt", "lambcrypt-fskit.", "lambcrypt-fat-repro-"))
               for part in directories):
            raise RuntimeError(f"a previous LambCrypt or VeraCrypt disk image remains attached at {image}")


def confirm_closed(mounts, root, volume, active, kernel_fat):
    mount_table = mounts()
    assert str(root) not in mount_table, "Disposable mount remains"
    if kernel_fat:
        # A stalled detach can leave the image attached after the mount row
        # disappears. Confirm both inventories before probing its paths.
        if active:
            assert f" on {active[1]} (" not in mount_table, "Auxiliary mount remains"
        require_no_retained_fat_image()
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
    handles = subprocess.run(["/usr/sbin/lsof", "-t", str(volume)], capture_output=True, text=True, timeout=8)
    assert handles.returncode == 1 and not handles.stdout.strip(), "Backing file still open"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", required=True, type=Path)
    parser.add_argument("--release-binary", type=Path,
                        help="Create and verify the container with this released FUSE-T client")
    parser.add_argument("--cli-only", action="store_true",
                        help="Verify the container round trip without launching the background GUI")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--fskit-external-eject", action="store_true",
                      help="Test a signed FSKit bundle with HFS+ and Disk Arbitration eject")
    mode.add_argument("--fskit-kernel-fat", action="store_true",
                      help="Test production FSKit read-write teardown with the kernel FAT driver")
    parser.add_argument("--isolated-host", action="store_true",
                        help="Confirm this is a dedicated test host for the FAT trial")
    parser.add_argument("--keep-artifacts", action="store_true")
    args = parser.parse_args()
    if args.fskit_kernel_fat:
        if not args.isolated_host:
            parser.error("--fskit-kernel-fat requires --isolated-host")
        if sys.platform != "darwin" or os.uname().machine != "arm64" or os.geteuid() == 0:
            parser.error("run the kernel FAT trial as a regular user on Apple Silicon macOS")
    fskit = args.fskit_external_eject or args.fskit_kernel_fat
    cli_only = args.cli_only or args.fskit_kernel_fat
    binary = args.binary.resolve(strict=True)
    release = args.release_binary.resolve(strict=True) if args.release_binary else binary
    if fskit:
        if (not is_fskit(binary) or binary.parent.name != "MacOS" or binary.parents[2].suffix != ".app"
                or args.release_binary or (args.fskit_external_eject and cli_only)):
            parser.error("the FSKit modes require a signed FSKit bundle and no release binary")
        app = binary.parents[2]
        if args.fskit_kernel_fat:
            extension = app / "Contents/Extensions/LambCryptFSKit.appex/Contents"
            if Path("/Applications") in app.parents or not (extension / "embedded.provisionprofile").is_file():
                parser.error("the kernel FAT trial requires a provisioned scratch FSKit bundle")
        subprocess.run(["/usr/bin/codesign", "--verify", "--deep", "--strict", app], check=True, timeout=10)
    elif is_fskit(binary) or is_fskit(release):
        parser.error("select an explicit FSKit mode for the signed app")

    def mounts():
        return subprocess.check_output(["/sbin/mount"], text=True, timeout=8)

    initial_mounts = mounts()
    if ".veracrypt_aux_mnt" in initial_mounts or fskit_mounts(initial_mounts):
        raise RuntimeError("Dismount existing LambCrypt or VeraCrypt volumes before this isolated GUI test")
    if args.fskit_kernel_fat:
        require_no_retained_fat_image()
    processes = subprocess.check_output(["/bin/ps", "-axo", "comm="], text=True)
    if any(Path(line.strip()).name.lower() in {"lambcrypt", "lambcrypt-fskit", "veracrypt"}
           for line in processes.splitlines()):
        raise RuntimeError("Close other LambCrypt or VeraCrypt processes before this isolated GUI test")

    root = Path(tempfile.mkdtemp(prefix="vc-gui-lifecycle-", dir="/private/tmp" if args.fskit_kernel_fat else None)).resolve()
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
    if not cli_only:
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
        log = root / (label + ".log")
        try:
            result = subprocess.run(command, env=env, capture_output=True, text=True, timeout=timeout)
        except subprocess.TimeoutExpired as error:
            log.write_bytes((error.stdout or b"") + (error.stderr or b"") + f"\nTimed out after {timeout} seconds.\n".encode())
            raise
        log.write_text(result.stdout + result.stderr)
        if result.returncode != expected_returncode:
            raise RuntimeError(f"{label} failed; see {log}")
        return result

    def vc(label, *options, client=binary, expected_returncode=0):
        return run(label, [client, "--text", "--non-interactive", *options],
                   expected_returncode=expected_returncode)

    def mount(read_only=False, client=binary):
        nonlocal active, mount_client
        mount_client = client
        before = fskit_mounts(mounts()) if fskit else set()
        target = "--filesystem=none" if args.fskit_kernel_fat else mountpoint
        label = "mount-readonly" if args.fskit_kernel_fat and read_only else "mount"
        vc(label, "--mount", volume, target, "--password=" + password,
           "--pim=1", "--keyfiles=", "--protect-hidden=no",
           *(["--mount-options=ro"] if read_only else []), client=client)
        if fskit:
            aux, = fskit_mounts(mounts()) - before
            assert aux.parent.as_posix().startswith("/private/tmp/lambcrypt-fskit."), aux
            workers = subprocess.check_output(["/usr/sbin/lsof", "-t", volume], text=True, timeout=8)
            pid, = {int(pid) for pid in workers.split()}
            active = (pid, aux, None)
            if args.fskit_kernel_fat:
                image, = fskit_images(aux)
                assert not any(entry.get("mount-point") for entry in image["system-entities"])
                device = kernel_fat_device(image, read_only)
                evidence = "fat-attachment-readonly.plist" if read_only else "fat-attachment.plist"
                (root / evidence).write_bytes(plistlib.dumps({
                    "device": device, "writeable": image["writeable"],
                    "uses-helper": bool(image.get("hdid-pid")), "diskimages2": bool(image.get("diskimages2")),
                }))
                options = "ro,nosuid,nodev" if read_only else "nosuid,nodev"
                run("mount-kernel-fat-readonly" if read_only else "mount-kernel-fat",
                    ["/sbin/mount_msdos", "-o", options, device, mountpoint], timeout=15)
                assert confirm_kernel_fat(aux, read_only) == device
            else:
                confirm_fskit_attachment(aux, read_only)
            return
        identities = list(temporary.glob("**/.veracrypt_aux_mnt*/shutdown"))
        assert len(identities) == 1, "Expected one disposable FUSE-T service"
        aux = identities[0].parent
        active = (int(identities[0].read_text().split()[0]), aux,
                  Path((aux / "shutdown-socket").read_text().strip()))

    def fskit_images(aux):
        inventory = subprocess.check_output(["/usr/bin/hdiutil", "info", "-plist"], timeout=8)
        return [image for image in plistlib.loads(inventory)["images"]
                if image.get("image-path") == str(aux / "volume.dmg")]

    def kernel_fat_device(image, read_only):
        assert image.get("writeable") is (not read_only), "Unexpected Disk Images protection"
        device, = (entry["dev-entry"] for entry in image["system-entities"]
                   if re.fullmatch(r"/dev/disk[0-9]+", entry.get("dev-entry", "")))
        return device

    def confirm_kernel_fat(aux, read_only):
        image, = fskit_images(aux)
        device = kernel_fat_device(image, read_only)
        prefix = f"{device} on {mountpoint} (msdos, "
        line, = (line for line in mounts().splitlines() if line.startswith(prefix))
        flags = line[len(prefix):].removesuffix(")").split(", ")
        assert "fskit" not in flags and ("read-only" in flags) == read_only, line
        return device

    def confirm_fskit_attachment(aux, read_only):
        image, = fskit_images(aux)
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

    def check_busy_kernel_fat(stream, payload):
        pid, aux, _ = active
        device = confirm_kernel_fat(aux, read_only=False)
        result = vc("busy-kernel-fat-unmount", "--unmount", volume, expected_returncode=1)
        assert "The volume is in use." in result.stdout + result.stderr
        listing = vc("busy-kernel-fat-list", "--list", "--verbose", volume).stdout
        assert str(volume) in listing and str(mountpoint) in listing
        assert confirm_kernel_fat(aux, read_only=False) == device
        holders = run("busy-kernel-fat-worker", ["/usr/sbin/lsof", "-t", volume], timeout=8)
        assert {int(word) for word in holders.stdout.split()} == {pid}
        stream.seek(0)
        assert stream.read() == payload

    filesystem = "HFS+" if args.fskit_external_eject else "FAT"
    try:
        vc("create", "--create", volume, "--size=33554432", "--volume-type=normal",
           "--encryption=AES", "--hash=sha512", f"--filesystem={filesystem}", "--password=" + password,
           "--pim=1", "--keyfiles=", "--random-source=/dev/urandom", client=release)
        mount()
        if args.fskit_kernel_fat:
            marker = mountpoint / "before.bin"
            marker.write_bytes(b"LambCrypt FAT test")
            renamed = marker.with_name("after.bin")
            marker.rename(renamed)
            assert renamed.read_bytes() == b"LambCrypt FAT test"
            renamed.unlink()
        payload = bytes(range(256)) * 4096
        with payload_path.open("w+b" if args.fskit_kernel_fat else "wb") as stream:
            stream.write(payload)
            stream.flush()
            if args.fskit_external_eject:
                check_writable_metadata(stream)
            os.fsync(stream.fileno())
            if args.fskit_kernel_fat:
                check_busy_kernel_fat(stream, payload)
        vc("unmount-write", "--unmount", volume)
        confirm_closed(mounts, root, volume, active, args.fskit_kernel_fat)
        if args.release_binary or cli_only:
            mount(read_only=True, client=release)
            assert hashlib.sha256((mountpoint / "payload.bin").read_bytes()).digest() == hashlib.sha256(payload).digest()
            if args.fskit_kernel_fat:
                assert not (mountpoint / "before.bin").exists() and not (mountpoint / "after.bin").exists()
            vc("unmount-release", "--unmount", volume, client=release)
            confirm_closed(mounts, root, volume, active, args.fskit_kernel_fat)
            print("PASS: create, write/fsync, read-only remount, payload integrity, service/file cleanup", flush=True)
        if cli_only:
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
        confirm_closed(mounts, root, volume, active, args.fskit_kernel_fat)
        succeeded = True
        print("PASS: payload integrity, initial background discovery, external-dismount refresh, automatic exit, service/file cleanup", flush=True)
    finally:
        if gui and gui.poll() is None:
            gui.terminate()
            gui.wait(timeout=10)
        # Keep a failed FAT trial available for diagnosis without another detach.
        if not args.fskit_kernel_fat and (str(root) in mounts() or (active and active[1].exists())):
            vc("test-cleanup", "--unmount", volume, client=mount_client)
        if succeeded and not args.keep_artifacts:
            confirm_closed(mounts, root, volume, active, args.fskit_kernel_fat)
            shutil.rmtree(root)


if __name__ == "__main__":
    main()
