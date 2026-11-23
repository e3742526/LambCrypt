#!/usr/bin/env python3
"""Exercise FSKit trial preflight and teardown checks with simulated inventories."""
from pathlib import Path
import plistlib
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import test_macos_gui_lifecycle as lifecycle


class FSKitPreflightTests(unittest.TestCase):
    def exercise(self, inventory, expected_error, mode=("--fskit-kernel-fat", "--isolated-host")):
        with tempfile.TemporaryDirectory() as directory:
            app = Path(directory) / "LambCrypt-FSKit.app"
            binary = app / "Contents/MacOS/LambCrypt-FSKit"
            binary.parent.mkdir(parents=True)
            binary.touch()
            profile = app / "Contents/Extensions/LambCryptFSKit.appex/Contents/embedded.provisionprofile"
            profile.parent.mkdir(parents=True)
            profile.touch()

            def check_output(command, **kwargs):
                if command == ["/usr/bin/hdiutil", "info", "-plist"]:
                    if isinstance(inventory, Exception):
                        raise inventory
                    if isinstance(inventory, bytes):
                        return inventory
                    return plistlib.dumps(inventory)
                if command in (["/sbin/mount"], ["/bin/ps", "-axo", "comm="]):
                    return ""
                raise AssertionError(command)

            with (patch.object(sys, "argv", ["lifecycle", "--binary", str(binary), *mode]),
                  patch.object(sys, "platform", "darwin"),
                  patch.object(lifecycle.os, "uname", return_value=SimpleNamespace(machine="arm64")),
                  patch.object(lifecycle.os, "geteuid", return_value=501),
                  patch.object(lifecycle.subprocess, "run") as sign,
                  patch.object(lifecycle.subprocess, "check_output", side_effect=check_output),
                  patch.object(lifecycle.tempfile, "mkdtemp",
                               side_effect=AssertionError("Scratch creation reached")) as create):
                with self.assertRaisesRegex(*expected_error):
                    lifecycle.main()
                sign.assert_called_once()
                if expected_error[0] is AssertionError:
                    create.assert_called_once()
                else:
                    create.assert_not_called()

    def test_retained_images_without_mount_rows(self):
        for path in (
            "/private/tmp/lambcrypt-fskit.12345678/.veracrypt_aux_mnt/volume.dmg",
            "/tmp/.veracrypt_aux_mnt-12345678/volume.dmg",
            "/Users/test/Library/Caches/lambcrypt-fat-repro-example/fskit-mount/volume.dmg",
            "/Users/test/Library/Caches/lambcrypt-fat-repro-example/lambcrypt-isolated-plain-fat.raw",
            "/private/tmp/lambcrypt-worker.12345678/1/aux/volume.dmg",
        ):
            with self.subTest(path=path):
                self.exercise({"images": [{"image-path": path}]}, (RuntimeError, "remains attached"))

    def test_incomplete_or_unavailable_inventory(self):
        for inventory in ({}, {"images": [{}]}, {"images": ["not a record"]}):
            with self.subTest(inventory=inventory):
                self.exercise(inventory, (RuntimeError, "inventory is incomplete"))
        self.exercise(subprocess.TimeoutExpired("hdiutil", 8),
                      (RuntimeError, "could not verify Disk Images inventory"))
        self.exercise(b'<?xml version="1.0"?><plist><dict>',
                      (RuntimeError, "could not verify Disk Images inventory"))

    def test_unrelated_image_allows_trial(self):
        self.exercise({"images": [{"image-path": "/tmp/other/volume.dmg"}]},
                      (AssertionError, "Scratch creation reached"))

    def test_hfs_cli_and_finder_check_the_inventory_before_creating_a_fixture(self):
        for option in ("--cli-only", "--finder-eject"):
            with self.subTest(option=option):
                mode = ("--fskit-external-eject", option)
                self.exercise({"images": []}, (AssertionError, "Scratch creation reached"), mode)
                self.exercise({"images": [{"image-path": "/tmp/lambcrypt-fskit.abcd/aux/volume.dmg"}]},
                              (RuntimeError, "remains attached"), mode)


class FSKitTeardownTests(unittest.TestCase):
    root = Path("/private/tmp/vc-gui-lifecycle-test")
    volume = root / "ordinary.hc"
    aux = Path("/private/tmp/lambcrypt-fskit.12345678/.veracrypt_aux_mnt")
    active = (42, aux, None)

    def test_retained_mount_or_image_refused_before_path_probes(self):
        retained_image = {"images": [{"image-path": str(self.aux / "volume.dmg")}]}
        for mounts, inventory, error in (
            (f"/dev/disk9s1 on {self.root / 'mounted'} (msdos, local)", {"images": []},
             (AssertionError, "Disposable mount remains")),
            (f"lambcryptfs on {self.aux} (lambcryptfs, local)", {"images": []},
             (AssertionError, "Auxiliary mount remains")),
            ("", retained_image, (RuntimeError, "remains attached")),
            ("", {}, (RuntimeError, "inventory is incomplete")),
        ):
            with (self.subTest(mounts=mounts, inventory=inventory),
                  patch.object(lifecycle.subprocess, "check_output", return_value=plistlib.dumps(inventory)),
                  patch.object(lifecycle.os, "kill", side_effect=ProcessLookupError),
                  patch.object(Path, "exists", side_effect=AssertionError("probed a retained mount path")) as probe,
                  patch.object(lifecycle.subprocess, "run") as lsof):
                with self.assertRaisesRegex(*error):
                    lifecycle.confirm_closed(lambda: mounts, self.root, self.volume, self.active, fskit=True)
                probe.assert_not_called()
                lsof.assert_not_called()

    def test_clean_inventory_checks_backing_handle_with_deadline(self):
        with (patch.object(lifecycle.subprocess, "check_output", return_value=plistlib.dumps({"images": []})),
              patch.object(lifecycle.os, "kill", side_effect=ProcessLookupError),
              patch.object(Path, "exists", return_value=False),
              patch.object(lifecycle.subprocess, "run", return_value=SimpleNamespace(returncode=1, stdout="")) as lsof):
            lifecycle.confirm_closed(lambda: "", self.root, self.volume, self.active, fskit=True)
        lsof.assert_called_once_with(["/usr/sbin/lsof", "-t", str(self.volume)],
                                     capture_output=True, text=True, timeout=8)


if __name__ == "__main__":
    unittest.main()
