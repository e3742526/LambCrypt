#!/usr/bin/env python3
"""Exercise the isolated FAT trial preflight with simulated Disk Images inventory."""
from pathlib import Path
import plistlib
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import test_macos_gui_lifecycle as lifecycle


class FatPreflightTests(unittest.TestCase):
    def exercise(self, inventory, expected_error):
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

            with (patch.object(sys, "argv", ["lifecycle", "--binary", str(binary),
                                             "--fskit-kernel-fat", "--isolated-host"]),
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


if __name__ == "__main__":
    unittest.main()
