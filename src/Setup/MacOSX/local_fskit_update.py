#!/usr/bin/env python3
# Copyright (c) 2026 LambCrypt contributors
# Governed by the Apache License 2.0; see src/License.txt.
"""Build and update the canonical Apple Development-signed FSKit app."""

import argparse
import ctypes
from datetime import datetime, timezone
import fcntl
import hashlib
import os
from pathlib import Path
import plistlib
import re
import stat
import subprocess
import sys
import tempfile


ROOT = Path(__file__).resolve().parents[3]
APP = Path("/Applications/LambCrypt-FSKit.app")
APP_ID = "io.github.e3742526.LambCrypt.fskit"
EXTENSION = Path("Contents/Extensions/LambCryptFSKit.appex")
BINARY = Path("Contents/MacOS/LambCrypt-FSKit")
INFO = Path("Contents/Info.plist")
WORKER_PREFIXES = (".veracrypt_aux_mnt", "lambcrypt-fskit.", "lambcrypt-worker.", "lambcrypt-fat-repro-")


def run(*args, timeout=30):
    return subprocess.check_output(args, timeout=timeout)


def version(value):
    if not re.fullmatch(r"[1-9][0-9]{0,3}(\.[0-9]{1,2}){0,2}", value):
        raise ValueError("expected a CFBundleVersion such as 1.29.8")
    fields = tuple(map(int, value.split(".")))
    return fields + (0,) * (3 - len(fields))


def next_version(previous, requested):
    major, minor, patch = previous
    carry, patch = divmod(patch + 1, 100)
    carry, minor = divmod(minor + carry, 100)
    candidate = version(requested) if requested else (major + carry, minor, patch)
    if not previous < candidate < (10000, 0, 0):
        raise ValueError("the build must be higher than the installed and previously allocated builds")
    return ".".join(map(str, candidate))


def private_directory(path):
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    info = path.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
        raise RuntimeError(f"Local update directory must be privately owned: {path}")


def identity_and_profile():
    selected = os.environ.get("VC_APP_SIGN_IDENTITY", "")
    identities = run("/usr/bin/security", "find-identity", "-v", "-p", "codesigning").decode()
    matches = [fingerprint for fingerprint, name in re.findall(
        r'^\s*\d+\) ([A-F0-9]{40}) "(Apple Development:[^"]+)"', identities, re.M)
        if selected.upper() == fingerprint or selected == name]
    if len(matches) != 1:
        raise RuntimeError("Set VC_APP_SIGN_IDENTITY to a valid Apple Development identity with its private key in Keychain.")
    profile = os.environ.get("VC_FSKIT_PROVISIONING_PROFILE", "")
    if not Path(profile).is_absolute() or not Path(profile).is_file():
        raise RuntimeError("Set VC_FSKIT_PROVISIONING_PROFILE to the absolute path of the development profile.")
    raw = Path(profile).read_bytes()
    try:
        decoded = run("/usr/bin/security", "cms", "-D", "-i", profile)
        properties = plistlib.loads(decoded)
        expiry = properties["ExpirationDate"].replace(tzinfo=timezone.utc)
        entitlements = properties["Entitlements"]
        team = entitlements["com.apple.developer.team-identifier"]
    except (subprocess.CalledProcessError, ValueError, KeyError, AttributeError) as error:
        raise RuntimeError("Cannot read the FSKit development provisioning profile.") from error
    if expiry <= datetime.now(timezone.utc):
        raise RuntimeError("The FSKit development provisioning profile has expired.")
    if (properties.get("ProvisionsAllDevices") or not re.fullmatch(r"[A-Z0-9]{10}", team)
            or entitlements.get("com.apple.developer.fskit.fsmodule") is not True
            or entitlements.get("com.apple.application-identifier") != f"{team}.{APP_ID}.module"):
        raise RuntimeError("The development profile must authorize the exact LambCrypt FSKit module and team.")
    hardware = run("/usr/sbin/system_profiler", "-xml", "SPHardwareDataType")
    udid = plistlib.loads(hardware)[0]["_items"][0].get("provisioning_UDID")
    if not udid or udid not in properties.get("ProvisionedDevices", []):
        raise RuntimeError("The development profile must authorize this Mac's exact Provisioning UDID.")
    fingerprints = {hashlib.sha1(cert).hexdigest().upper() for cert in properties.get("DeveloperCertificates", [])}
    if matches[0] not in fingerprints:
        raise RuntimeError("The development profile does not authorize the selected signing certificate.")
    return matches[0], team, raw


def application_info():
    if APP.is_symlink() or (APP.exists() and not APP.is_dir()):
        raise RuntimeError("The canonical application must be a bundle directory.")
    if not APP.exists():
        return None
    info = plistlib.loads((APP / INFO).read_bytes())
    if info.get("CFBundleIdentifier") != APP_ID:
        raise RuntimeError("A different bundle occupies the canonical application path.")
    return info


def ensure_idle(team):
    mounts = run("/sbin/mount", timeout=8).decode()
    if re.search(r"\(lambcryptfs,|\.veracrypt_aux_mnt|lambcrypt-fskit\.", mounts, re.I):
        raise RuntimeError("Dismount LambCrypt volumes and confirm auxiliary cleanup before installing.")
    processes = run("/bin/ps", "-axo", "comm=").decode().splitlines()
    names = {Path(item.strip()).name.lower() for item in processes}
    if names & {"lambcrypt", "lambcrypt-fskit", "lambcryptfskit", "veracrypt"}:
        raise RuntimeError("Close LambCrypt and VeraCrypt and wait for their workers and extensions to exit.")
    images = plistlib.loads(run("/usr/bin/hdiutil", "info", "-plist", timeout=8)).get("images")
    if not isinstance(images, list):
        raise RuntimeError("Disk Images returned an incomplete inventory.")
    for image in images:
        path = image.get("image-path") if isinstance(image, dict) else None
        if not isinstance(path, str) or not path:
            raise RuntimeError("Disk Images returned an incomplete inventory.")
        if any(part.startswith(WORKER_PREFIXES) for part in Path(path).parts):
            raise RuntimeError("A LambCrypt or VeraCrypt Disk Images attachment is still present.")

    group = Path.home() / "Library/Group Containers" / f"{team}.lambcrypt-fskit"
    if not group.exists():
        return
    private_directory(group)
    for worker in group.iterdir():
        if (worker / "io").exists() or (worker / "attachment-pending").exists():
            raise RuntimeError("The App Group still contains a worker endpoint or a pending attachment.")
    locks = group / "mount-locks"
    if locks.exists():
        for lock in locks.iterdir():
            fd = os.open(lock, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK)
            try:
                if not stat.S_ISREG(os.fstat(fd).st_mode):
                    raise RuntimeError("Encountered an unexpected LambCrypt reservation.")
                try:
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError as error:
                    raise RuntimeError("A LambCrypt mount reservation is still held.") from error
            finally:
                os.close(fd)


def extension_registrations():
    result = subprocess.run(
        ["/usr/bin/pluginkit", "-m", "-A", "-D", "-v", "-i", APP_ID + ".module"],
        capture_output=True, text=True, timeout=10,
    )
    if result.returncode and result.stdout.strip() != "(no matches)" and result.stderr.strip() != "(no matches)":
        raise RuntimeError("Could not check PlugInKit registrations.")
    paths = []
    for row in result.stdout.splitlines():
        if APP_ID + ".module" not in row:
            continue
        path = row.split("\t")[-1].strip()
        if not path.startswith("/"):
            raise RuntimeError("Could not identify the PlugInKit registered bundle path.")
        paths.append(Path(path).resolve())
    if any(path != APP / EXTENSION for path in paths):
        raise RuntimeError("PlugInKit lists a second LambCrypt extension. Archive that copy and consult the reactivation runbook.")
    return paths


def publish(candidate, work, had_app, team):
    with tempfile.TemporaryDirectory(prefix=".lambcrypt-update-", dir=APP.parent) as staging:
        staged = Path(staging) / "candidate.bundle"
        subprocess.run(["/usr/bin/ditto", candidate, staged], check=True)
        subprocess.run(["/bin/bash", ROOT / "src/Setup/MacOSX/verify_fskit_bundle.sh", "--local", staged], check=True)
        if had_app:
            backup = work / "previous-app.zip"
            subprocess.run(["/usr/bin/ditto", "-c", "-k", "--keepParent", APP, backup], check=True)
            subprocess.run(["/usr/bin/unzip", "-tq", backup], check=True)
            print(f"Previous app archived at {backup}", flush=True)
        ensure_idle(team)
        extension_registrations()
        # Swap atomically on APFS. For a first install, require the destination
        # to still be absent. Both operations stay on the Applications volume.
        rename = ctypes.CDLL(None, use_errno=True).renamex_np
        rename.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_uint]
        rename.restype = ctypes.c_int
        flag = 0x00000002 if had_app else 0x00000004  # RENAME_SWAP / RENAME_EXCL
        if rename(os.fsencode(staged), os.fsencode(APP), flag) != 0:
            error = ctypes.get_errno()
            raise OSError(error, os.strerror(error), str(APP))


def update(args, state):
    identity, team, profile = identity_and_profile()
    old_info = application_info()
    if old_info and old_info.get("LambCryptFSKitIPCGroup") != f"{team}.lambcrypt-fskit":
        raise RuntimeError("The installed app and the selected development identity use different App Groups.")
    if not args.build_only:
        ensure_idle(team)
        extension_registrations()
    counter = state / "last-build-version"
    previous = max(version(counter.read_text().strip()) if counter.exists() else (1, 0, 0),
                   version(old_info["CFBundleVersion"]) if old_info else (1, 0, 0))
    build = next_version(previous, args.build_version)
    commit = run("/usr/bin/git", "-C", ROOT, "rev-parse", "--verify", "--end-of-options", args.ref + "^{commit}").decode().strip()
    work = Path(tempfile.mkdtemp(prefix=f"{build}-", dir=state))
    (work / "source-commit").write_text(commit + "\n")
    (work / "allocated-version").write_text(build + "\n")
    (work / "allocated-version").replace(counter)
    source = work / "source"
    source.mkdir()
    archive = work / "source.tar"
    subprocess.run(["/usr/bin/git", "-C", ROOT, "archive", "--format=tar", "-o", archive, commit], check=True)
    subprocess.run(["/usr/bin/tar", "-xf", archive, "-C", source], check=True)
    archive.unlink()

    print(f"Building {commit} as {build}. Build log is in {work}.", flush=True)
    with tempfile.TemporaryDirectory(dir=work) as private:
        profile_path = Path(private) / "profile.provisionprofile"
        profile_path.write_bytes(profile)
        env = dict(os.environ, VC_APP_SIGN_IDENTITY=identity, VC_FSKIT_PROVISIONING_PROFILE=str(profile_path),
                   VC_FSKIT_BUILD_VERSION=build, VC_OSX_TARGET="26.0")
        env.pop("VC_FSKIT_TARGET_UDID", None)
        with (work / "build.log").open("wb") as log:
            status = subprocess.run(
                ["/usr/bin/make", f"-j{args.jobs}", "-C", source / "src", "WXSTATIC=FULL",
                 "WX_BUILD_DIR=" + str(args.wx_build_dir), "LOCAL_DEVELOPMENT_BUILD=true", "prepare"],
                stdout=log, stderr=subprocess.STDOUT, env=env,
            )
        built = source / "src/Main" / APP.name
        candidate = work / "candidate.bundle"
        if built.exists():
            built.rename(candidate)
        if status.returncode:
            raise RuntimeError(f"Build or signing failed. See {work / 'build.log'}.")
    verifier = ROOT / "src/Setup/MacOSX/verify_fskit_bundle.sh"
    subprocess.run(["/bin/bash", verifier, "--local", candidate], check=True)
    if args.build_only:
        print(f"Verified development build {build} at {candidate}.")
        return
    if not os.access(APP.parent, os.W_OK):
        raise RuntimeError("The logged-in user must have write access to /Applications.")
    probe = work / "check_fskit_activation"
    subprocess.run(["/usr/bin/xcrun", "swiftc", ROOT / "Tests/check_fskit_activation.swift", "-o", probe], check=True)
    subprocess.run(["/usr/bin/codesign", "--force", "--sign", identity, probe], check=True)
    if application_info() != old_info:
        raise RuntimeError("The canonical application changed while building. Start the update again.")
    publish(candidate, work, old_info is not None, team)
    print(f"Installed {build} at {APP}.", flush=True)
    result = subprocess.run([probe, "--register", APP], timeout=12)
    if result.returncode:
        raise RuntimeError("Installation is preserved. Check File System Extensions and the reactivation runbook.")
    if len(extension_registrations()) != 1:
        raise RuntimeError("Installation is preserved. PlugInKit did not list exactly one canonical extension.")
    if args.smoke:
        env = dict(os.environ, LAMBCRYPT_LICENSE_ACCEPTED="1")
        subprocess.run([sys.executable, "-B", ROOT / "Tests/test_macos_gui_lifecycle.py",
                        "--isolated-host", "--fskit-routed-fat", "12", "--binary", APP / BINARY],
                       env=env, check=True, timeout=300)
    else:
        print("The canonical module is enabled. Disposable mount testing was skipped.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--wx-build-dir", type=Path, required=True, help="Existing static arm64 wxWidgets build")
    parser.add_argument("--ref", default="HEAD", help="Git commit or ref to build, including a known-good rollback ref")
    parser.add_argument("--build-version", help="Explicit build number greater than any prior local update")
    parser.add_argument("--jobs", type=int, default=min(8, os.cpu_count() or 1))
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--build-only", action="store_true", help="Build and verify privately without installing")
    modes.add_argument("--smoke", action="store_true", help="After installing, exercise a disposable FAT12 lifecycle")
    args = parser.parse_args()
    os.umask(0o077)
    if sys.platform != "darwin" or os.uname().machine != "arm64" or os.geteuid() == 0:
        parser.error("Run this as the logged-in user on an Apple Silicon Mac.")
    if int(run("/usr/bin/sw_vers", "-productVersion").split(b".")[0]) < 26:
        parser.error("macOS 26 or later is required.")
    args.wx_build_dir = args.wx_build_dir.resolve()
    if args.jobs < 1 or not os.access(args.wx_build_dir / "wx-config", os.X_OK):
        parser.error("Supply an existing wx-config from a static wxWidgets build and a positive job count.")
    state = Path.home() / "Library/Application Support/LambCrypt-FSKit/Local Updates"
    try:
        private_directory(state)
        fd = os.open(state / "update.lock", os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            update(args, state)
        finally:
            os.close(fd)
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
        parser.exit(1, f"Local FSKit update failed. {error}\n")


if __name__ == "__main__":
    main()
