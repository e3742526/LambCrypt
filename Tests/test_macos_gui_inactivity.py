#!/usr/bin/env python3
# Modified for LambCrypt by the LambCrypt contributors. Changes from VeraCrypt are in the git history; see UPSTREAM.md.
"""Inactivity auto-dismount in the background GUI; no sudo required.

Requires a logged-in macOS desktop and no other LambCrypt or VeraCrypt processes or mounts.
Two disposable HFS+ containers are attached read-only. The GUI must track each
idle timer independently. With --active-second, reads of the second volume's
backing image reset its timer. With --busy-first, an open directory on the first
filesystem prevents its automatic dismount until release.
Takes about two minutes.
"""
import argparse
import os
from pathlib import Path
import plistlib
import shutil
import subprocess
import tempfile
import time


def aux_mounts():
    output = subprocess.check_output(["/sbin/mount"], text=True, timeout=8)
    paths = set()
    for line in output.splitlines():
        path = line.partition(" on ")[2].rpartition(" (")[0]
        if Path(path).name.startswith(".veracrypt_aux_mnt"):
            paths.add(path)
    return paths


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", required=True, type=Path)
    parser.add_argument("--active-second", action="store_true", help="exercise independent read activity")
    parser.add_argument("--busy-first", action="store_true", help="disable forced dismount and hold the first volume busy")
    parser.add_argument("--keep-artifacts", action="store_true")
    args = parser.parse_args()
    binary = args.binary.resolve(strict=True)
    if aux_mounts():
        raise RuntimeError("Dismount existing LambCrypt or VeraCrypt volumes before this isolated GUI test")
    processes = subprocess.check_output(["/bin/ps", "-axo", "comm="], text=True)
    if any(Path(line.strip()).name.lower() in {"lambcrypt", "lambcrypt-fskit", "veracrypt"}
           for line in processes.splitlines()):
        raise RuntimeError("Close other LambCrypt or VeraCrypt processes before this isolated GUI test")

    root = Path(tempfile.mkdtemp(prefix="vc-gui-inactivity-")).resolve()
    print("Artifacts:", root, flush=True)
    temporary = root / "tmp"
    first_filesystem = root / "first-mount"
    config = root / "config" / "LambCrypt"
    temporary.mkdir(mode=0o700)
    config.mkdir(parents=True)
    if args.busy_first:
        first_filesystem.mkdir()
    prefs = dict(BackgroundTaskEnabled=1, CloseBackgroundTaskOnNoVolumes=1, DismountOnInactivity=1,
                 MaxVolumeIdleTime=1, ForceAutoDismount=int(not args.busy_first), DismountOnLogOff=0,
                 WipeCacheOnAutoDismount=0,
                 MountFavoritesOnLogon=0, MountDevicesOnLogon=0, OpenExplorerWindowAfterMount=0, SaveHistory=0)
    (config / "Configuration.xml").write_text("<VeraCrypt><configuration>" + "".join(
        f'<config key="{key}">{value}</config>' for key, value in prefs.items()
    ) + "</configuration></VeraCrypt>")
    env = dict(os.environ, TMPDIR=str(temporary) + "/", XDG_CONFIG_HOME=str(root / "config"))
    executable = binary
    contents = binary.parent.parent
    in_app_bundle = (binary.parent.name == "MacOS" and contents.name == "Contents"
                     and contents.parent.suffix == ".app" and (contents / "Info.plist").is_file())
    if not in_app_bundle:
        contents = root / "LambCryptTest.app" / "Contents"
        executable = contents / "MacOS" / "LambCrypt"
        executable.parent.mkdir(parents=True)
        shutil.copy2(binary, executable)
        (contents / "Info.plist").write_bytes(plistlib.dumps(dict(
            CFBundleExecutable="LambCrypt", CFBundleName="LambCrypt Inactivity Test",
            CFBundleIdentifier=f"io.github.e3742526.LambCrypt.inactivity-test.{os.getpid()}",
            CFBundlePackageType="APPL", NSHighResolutionCapable=True)))
    password = "Disposable-inactivity-only"
    volumes = {name: root / f"{name}.hc" for name in ("first", "second")}
    gui = None
    holder = None
    succeeded = False
    tracked = {}

    def vc(label, *options, expected_code=0):
        result = subprocess.run([str(binary), "--text", "--non-interactive", *map(str, options)],
                                env=env, capture_output=True, text=True, timeout=90)
        (root / (label + ".log")).write_text(result.stdout + result.stderr)
        if result.returncode != expected_code:
            raise RuntimeError(f"{label} failed; see {root / (label + '.log')}")
        return result.stdout

    def tracked_mounts():
        current = aux_mounts()
        if current.difference(tracked.values()):
            raise RuntimeError("Unexpected auxiliary mount appeared during the inactivity check")
        return current

    def mount(name, read_only=True):
        before = tracked_mounts()
        location = (first_filesystem,) if name == "first" and args.busy_first else ("--filesystem=none",)
        protection = ("--mount-options=ro",) if read_only else ()
        vc("mount-" + name, "--mount", volumes[name], *location, "--password=" + password,
           "--pim=1", "--keyfiles=", "--protect-hidden=no", *protection)
        added = aux_mounts() - before
        assert len(added) == 1, "Expected one new auxiliary mount"
        tracked[name] = added.pop()

    def read_counter(label):
        output = vc(label, "--volume-properties", volumes["second"])
        return next(line for line in output.splitlines() if line.startswith("Data Read since Mount:"))

    try:
        for name, volume in volumes.items():
            vc("create-" + name, "--create", volume, "--size=33554432", "--volume-type=normal",
               "--encryption=AES", "--hash=sha512", "--filesystem=HFS+", "--password=" + password,
               "--pim=1", "--keyfiles=", "--random-source=/dev/urandom")
        if args.busy_first:
            # A new HFS+ journal can require a writable mount before the
            # disposable fixture can be opened read-only.
            mount("first", read_only=False)
            vc("prepare-first-filesystem", "--unmount", volumes["first"])
            assert tracked["first"] not in tracked_mounts(), "First filesystem remained attached after preparation"
            tracked.pop("first")
        mount("first")
        if args.busy_first:
            holder = subprocess.Popen(["/bin/sleep", "150"], cwd=first_filesystem)
            vc("busy-first-control", "--unmount", volumes["first"], expected_code=1)
            busy = (root / "busy-first-control.log").read_text()
            assert "in use" in busy.lower(), "The open directory did not prevent a normal dismount"
        with (root / "gui.log").open("w") as log:
            gui = subprocess.Popen([str(executable), "--background-task"], env=env,
                                   stdout=log, stderr=log, start_new_session=True)
        start = time.monotonic()
        time.sleep(24 if args.active_second else 30)
        assert gui.poll() is None, "Background GUI exited before the second mount"
        mount("second")
        second_mounted = time.monotonic()
        second_idle_since = second_mounted
        if args.active_second:
            before = read_counter("second-before-reads")
            for offset_mib in (4, 12, 20):
                time.sleep(4)
                assert tracked["second"] in tracked_mounts(), "Second volume disappeared during activity"
                with (Path(tracked["second"]) / "volume.dmg").open("rb", buffering=0) as image:
                    assert len(os.pread(image.fileno(), 512 * 1024, offset_mib * 1024 * 1024)) == 512 * 1024
                second_idle_since = time.monotonic()
            after = read_counter("second-after-reads")
            assert before != after, "The second volume's worker did not record the test reads"
            print(f"second volume activity at {second_idle_since - second_mounted:.1f} s after attach. {before}. {after}.", flush=True)
        gone = {}
        while time.monotonic() - start < 150 and len(gone) < 2:
            current = tracked_mounts()
            if holder is not None:
                assert holder.poll() is None, "The open directory handle was lost"
                assert tracked["first"] in current, "A busy volume was forcibly unmounted with forcing disabled"
                if time.monotonic() - start >= 72:
                    holder.terminate()
                    holder.wait(timeout=5)
                    holder = None
                    print("First volume remained mounted through its idle deadline and was released", flush=True)
            for name, path in tracked.items():
                if name not in gone and path not in current:
                    gone[name] = time.monotonic()
            time.sleep(0.5)
        assert "first" in gone, "First idle volume was not unmounted automatically"
        assert "second" in gone, "Second idle volume was not unmounted automatically"
        first_idle = gone["first"] - start
        second_idle = gone["second"] - second_idle_since
        print(f"first unmounted after {first_idle:.1f} s; second after {second_idle:.1f} s idle", flush=True)
        assert gone["first"] < gone["second"], "The idle volume did not unmount first"
        assert 55 <= first_idle < (87 if args.busy_first else 80), "The first volume missed its dismount deadline"
        assert 55 <= second_idle < 78, "The second volume did not expire relative to its own idle start"
        if args.active_second:
            assert gone["second"] - second_mounted > 70, "Second volume activity did not extend its deadline"
        assert gui.wait(timeout=20) == 0, "Background app did not exit cleanly"
        for volume in volumes.values():
            closed = subprocess.run(["/usr/sbin/lsof", "-t", volume], capture_output=True, text=True, timeout=8)
            assert closed.returncode == 1 and not closed.stdout.strip(), "A worker still holds a disposable container"
        succeeded = True
        print("PASS: independent idle timers, automatic unmounts, automatic exit", flush=True)
    finally:
        if holder is not None and holder.poll() is None:
            holder.terminate()
            holder.wait(timeout=5)
        if gui and gui.poll() is None:
            gui.terminate()
            gui.wait(timeout=10)
        for name, volume in volumes.items():
            if tracked.get(name) in aux_mounts():
                subprocess.run([str(binary), "--text", "--non-interactive", "--unmount", str(volume)],
                               env=env, capture_output=True, text=True, timeout=90)
        if succeeded and not args.keep_artifacts:
            assert not tracked_mounts(), "Disposable mount remains"
            shutil.rmtree(root)


if __name__ == "__main__":
    main()
