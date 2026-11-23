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
import random
import re
import shutil
import subprocess
import struct
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
                      help="Control trial with a manual kernel FAT mount after attach-only")
    mode.add_argument("--fskit-routed-fat", type=int, choices=(12, 16, 32),
                      help="Test the app's FAT routing and lifecycle")
    parser.add_argument("--fat-default-directory", action="store_true",
                        help="Use the default directory on the writable routed FAT mount")
    parser.add_argument("--fat-finder-eject", action="store_true",
                        help="Wait up to 90 seconds for a Finder eject of a writable routed FAT mount")
    parser.add_argument("--isolated-host", action="store_true",
                        help="Confirm this is a dedicated test host for the FAT trial")
    parser.add_argument("--keep-artifacts", action="store_true")
    args = parser.parse_args()
    fat_trial = args.fskit_kernel_fat or args.fskit_routed_fat is not None
    if (args.fat_default_directory or args.fat_finder_eject) and not args.fskit_routed_fat:
        parser.error("routed FAT directory and Finder options require --fskit-routed-fat")
    if fat_trial:
        if not args.isolated_host:
            parser.error("the FAT trials require --isolated-host")
        if sys.platform != "darwin" or os.uname().machine != "arm64" or os.geteuid() == 0:
            parser.error("run the kernel FAT trial as a regular user on Apple Silicon macOS")
    fskit = args.fskit_external_eject or fat_trial
    cli_only = args.cli_only or fat_trial
    binary = args.binary.resolve(strict=True)
    release = args.release_binary.resolve(strict=True) if args.release_binary else binary
    if fskit:
        if (not is_fskit(binary) or binary.parent.name != "MacOS" or binary.parents[2].suffix != ".app"
                or args.release_binary or (args.fskit_external_eject and cli_only)):
            parser.error("the FSKit modes require a signed FSKit bundle and no release binary")
        app = binary.parents[2]
        if fat_trial:
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
    if fat_trial:
        require_no_retained_fat_image()
    processes = subprocess.check_output(["/bin/ps", "-axo", "comm="], text=True)
    if any(Path(line.strip()).name.lower() in {"lambcrypt", "lambcrypt-fskit", "veracrypt"}
           for line in processes.splitlines()):
        raise RuntimeError("Close other LambCrypt or VeraCrypt processes before this isolated GUI test")

    root = Path(tempfile.mkdtemp(prefix="vc-gui-lifecycle-", dir="/private/tmp" if fat_trial else None)).resolve()
    print("Artifacts:", root, flush=True)
    temporary = root / "tmp"
    explicit_mount = root / "mount"
    mountpoint = explicit_mount
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
        nonlocal active, mount_client, mountpoint
        mount_client = client
        before = fskit_mounts(mounts()) if fskit else set()
        default_directory = args.fskit_routed_fat and (args.fat_default_directory != read_only)
        mountpoint = explicit_mount
        if args.fskit_kernel_fat:
            target = ["--filesystem=none"]
        elif default_directory:
            target = []
        else:
            target = [explicit_mount]
        label = "mount-readonly" if fat_trial and read_only else "mount"
        vc(label, "--mount", volume, *target, "--password=" + password,
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
            elif args.fskit_routed_fat:
                if default_directory:
                    mountpoint = aux.parent / "volume"
                device = confirm_kernel_fat(aux, read_only)
                with (aux / "volume.dmg").open("rb", buffering=0) as image:
                    boot = image.read(512)
                type_offset = 82 if struct.unpack_from("<H", boot, 22)[0] == 0 else 54
                assert boot[type_offset:type_offset + 8].strip() == f"FAT{args.fskit_routed_fat}".encode()
                print(f"FAT{args.fskit_routed_fat} kernel route: {'read-only' if read_only else 'writable'}, "
                      f"{'default' if default_directory else 'explicit'} mount directory", flush=True)
                (root / f"{label}-device.txt").write_text(device + "\n")
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

    def confirm_kernel_fat(aux, read_only, directory=None):
        image, = fskit_images(aux)
        device = kernel_fat_device(image, read_only)
        prefix = f"{device} on {directory or mountpoint} (msdos, "
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
    def check_xattr(label, payload_path):
        result = run(label, [xattr, "-px", xattr_name, payload_path])
        assert bytes.fromhex(result.stdout) == bytes.fromhex(xattr_value)

    def check_writable_metadata(payload_path):
        run("xattr-create", [xattr, "-wx", xattr_name, "01", payload_path])
        run("xattr-replace", [xattr, "-wx", xattr_name, xattr_value, payload_path])
        check_xattr("xattr-before-remount", payload_path)
        deleted = xattr_name + ".removed"
        run("xattr-create-to-delete", [xattr, "-w", deleted, "discard", payload_path])
        run("xattr-remove", [xattr, "-d", deleted, payload_path])
        assert deleted not in run("xattr-list", [xattr, payload_path]).stdout.splitlines()

    def check_posix_locks(stream, payload_path):
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

    def check_independent_volume():
        second = root / "second.hc"
        target = root / "second-mount"
        keyfile = root / "second.key"
        target.mkdir(mode=0o700)
        keyfile.write_bytes(bytes(range(256)))
        keyfile.chmod(0o600)
        keyfiles = f"--keyfiles={keyfile}"
        vc("create-second", "--create", second, "--size=4194304", "--volume-type=normal",
           "--encryption=AES", "--hash=sha512", "--filesystem=FAT", "--password=" + password,
           "--pim=1", keyfiles, "--random-source=/dev/urandom")
        before = fskit_mounts(mounts())
        vc("mount-second", "--mount", second, target, "--password=" + password,
           "--pim=1", keyfiles, "--protect-hidden=no", "--mount-options=headerbak,ro")
        secondary_aux, = fskit_mounts(mounts()) - before
        confirm_kernel_fat(secondary_aux, read_only=True, directory=target)
        devices = vc("list-two", "--list", "--verbose").stdout
        assert str(volume) in devices and str(second) in devices, devices
        vc("unmount-second", "--unmount", second)
        assert fskit_mounts(mounts()) == before
        assert not fskit_images(secondary_aux) and not secondary_aux.parent.exists()
        run("second-worker-closed", ["/usr/sbin/lsof", "-t", second], timeout=8, expected_returncode=1)
        assert confirm_kernel_fat(active[1], read_only=False)
        print("PASS: a second keyfile/backup-header mount dismounted while the first remained busy", flush=True)

    def wait_for_fat_cleanup(seconds):
        deadline = time.monotonic() + seconds
        while f" on {active[1]} (" in mounts() and time.monotonic() < deadline:
            time.sleep(0.25)
        while active[1].parent.exists() and time.monotonic() < deadline:
            time.sleep(0.25)
        confirm_closed(mounts, root, volume, active, fat_trial)

    filesystem = "HFS+" if args.fskit_external_eject else "FAT"
    file_size = {12: 4 << 20, 16: 32 << 20, 32: 96 << 20}.get(args.fskit_routed_fat, 32 << 20)
    try:
        vc("create", "--create", volume, f"--size={file_size}", "--volume-type=normal",
           "--encryption=AES", "--hash=sha512", f"--filesystem={filesystem}", "--password=" + password,
           "--pim=1", "--keyfiles=", "--random-source=/dev/urandom", client=release)
        if args.fskit_routed_fat:
            with volume.open("rb") as encrypted:
                initial_encrypted = hashlib.file_digest(encrypted, "sha256").hexdigest()
        mount()
        if fat_trial:
            marker = mountpoint / "before.bin"
            marker.write_bytes(b"LambCrypt FAT test")
            renamed = marker.with_name("after.bin")
            marker.rename(renamed)
            assert renamed.read_bytes() == b"LambCrypt FAT test"
            renamed.unlink()
        if fskit:
            directory = mountpoint / "before-dir"
            directory.mkdir()
            (directory / "remove.txt").write_text("disposable")
            renamed_directory = directory.with_name("after-dir")
            directory.rename(renamed_directory)
            (renamed_directory / "remove.txt").unlink()
            renamed_directory.rmdir()
        payload = bytes(range(256)) * 4096
        payload_path = mountpoint / "payload.bin"
        with payload_path.open("w+b" if fskit else "wb") as stream:
            assert stream.write(payload) == len(payload)
            if fskit:
                expected = bytearray(payload)
                rng = random.Random(42)
                for offset in [511, 4093, *rng.sample(range(8192, len(payload) - 4096), 16)]:
                    patch = rng.randbytes(777)
                    stream.seek(offset)
                    assert stream.write(patch) == len(patch)
                    expected[offset:offset + len(patch)] = patch
                stream.truncate(700_003)
                stream.truncate(800_007)
                payload = bytes(expected[:700_003]) + bytes(100_004)
                stream.seek(0)
                assert stream.read() == payload
                mtime = 1_700_000_000
                os.utime(payload_path, (mtime, mtime))
                assert abs(payload_path.stat().st_mtime - mtime) <= 2
            stream.flush()
            if args.fskit_external_eject:
                check_writable_metadata(payload_path)
                check_posix_locks(stream, payload_path)
            os.fsync(stream.fileno())
            if fat_trial:
                check_busy_kernel_fat(stream, payload)
                if args.fskit_routed_fat == 16:
                    check_independent_volume()
                    stream.seek(0)
                    assert stream.read() == payload
        vc("unmount-write", "--unmount", volume)
        confirm_closed(mounts, root, volume, active, fat_trial)
        if args.fskit_routed_fat:
            with volume.open("rb") as encrypted:
                final_encrypted = hashlib.file_digest(encrypted, "sha256").hexdigest()
            assert initial_encrypted != final_encrypted, "The write trial did not change the encrypted data"
            (root / "encrypted-checksums.txt").write_text(f"{initial_encrypted}\n{final_encrypted}\n")
        if args.release_binary or cli_only:
            mount(read_only=True, client=release)
            assert hashlib.sha256((mountpoint / "payload.bin").read_bytes()).digest() == hashlib.sha256(payload).digest()
            if fat_trial:
                assert not (mountpoint / "before.bin").exists() and not (mountpoint / "after.bin").exists()
            if args.fskit_routed_fat:
                assert abs((mountpoint / "payload.bin").stat().st_mtime - mtime) <= 2
                run("external-eject", ["/usr/sbin/diskutil", "eject", confirm_kernel_fat(active[1], read_only=True)], timeout=30)
                wait_for_fat_cleanup(15)
                with volume.open("rb") as encrypted:
                    assert hashlib.file_digest(encrypted, "sha256").hexdigest() == final_encrypted
                if args.fat_finder_eject:
                    mount()
                    print(f"Eject the disposable FAT volume in Finder at {mountpoint}", flush=True)
                    wait_for_fat_cleanup(90)
                    print("PASS: external eject and worker cleanup for the writable FAT mount", flush=True)
            else:
                vc("unmount-release", "--unmount", volume, client=release)
                confirm_closed(mounts, root, volume, active, fat_trial)
            print("PASS: create, write/fsync, read-only remount, payload integrity, service/file cleanup", flush=True)
        if cli_only:
            succeeded = True
            return
        mount(read_only=True)
        assert hashlib.sha256((mountpoint / "payload.bin").read_bytes()).digest() == hashlib.sha256(payload).digest()
        if args.fskit_external_eject:
            assert abs(payload_path.stat().st_mtime - mtime) <= 2
            check_xattr("xattr-after-remount", payload_path)
            assert xattr_name + ".removed" not in run("xattr-remount-list", [xattr, payload_path]).stdout.splitlines()
            denied = run("xattr-readonly-denied", [xattr, "-wx", xattr_name, "01", payload_path],
                         expected_returncode=1)
            assert f"[Errno {errno.EROFS}]" in denied.stderr, denied.stderr
            check_xattr("xattr-readonly-preserved", payload_path)
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
        confirm_closed(mounts, root, volume, active, fat_trial)
        succeeded = True
        print("PASS: payload integrity, initial background discovery, external-dismount refresh, automatic exit, service/file cleanup", flush=True)
    finally:
        if gui and gui.poll() is None:
            gui.terminate()
            gui.wait(timeout=10)
        # Keep a failed FAT trial available for diagnosis without another detach.
        if not fat_trial and (str(root) in mounts() or (active and active[1].exists())):
            vc("test-cleanup", "--unmount", volume, client=mount_client)
        if succeeded and not args.keep_artifacts:
            confirm_closed(mounts, root, volume, active, fat_trial)
            shutil.rmtree(root)


if __name__ == "__main__":
    main()
