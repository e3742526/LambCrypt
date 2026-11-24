#!/usr/bin/env python3
# Copyright (c) 2026 LambCrypt contributors
# Governed by the Apache License 2.0, the full text of which is contained in
# the file License.txt included in LambCrypt binary and source code
# distribution packages.
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
import test_macos_fskit_filesystems as filesystems


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


class FSKitFormatGuardTests(unittest.TestCase):
    image = Path("/private/tmp/lambcrypt-fskit.fixture/.veracrypt_aux_mnt/volume.dmg")
    disk = "/dev/disk60"
    size = 96 << 20

    def check_target(self, entities, *, previous=None, current=None, image=None, writable=True):
        records = [{"image-path": str(image or self.image), "system-entities": entities, "writeable": writable}]
        if current is None:
            current = {self.disk: {"IORegistryEntryID": 123, "Size": self.size, "Whole": True, "Writable": True}}
        return filesystems.format_target(records, self.image, previous or {}, current, self.size)

    def test_exact_new_writable_whole_disk(self):
        self.assertEqual(self.check_target([{"dev-entry": self.disk}]), (self.disk, 123))

    def test_refuses_non_disposable_physical_and_existing_media(self):
        for disk in ("/dev/disk0", "/dev/disk60s1", "/dev/rdisk60"):
            with self.subTest(disk=disk), self.assertRaisesRegex(RuntimeError, "Refusing|Disk Images"):
                self.check_target([{"dev-entry": disk}], previous={"/dev/disk0": {"IORegistryEntryID": 10}})
        with self.assertRaisesRegex(RuntimeError, "Refusing to format"):
            self.check_target([{"dev-entry": self.disk}], previous={self.disk: {"IORegistryEntryID": 321}})
        with self.assertRaisesRegex(RuntimeError, "exactly one"):
            self.check_target([{"dev-entry": self.disk}], image=Path("/private/tmp/another/volume.dmg"))

    def test_disk_arbitration_must_also_identify_a_virtual_disk_image(self):
        information = dict(BusProtocol="Disk Image", VirtualOrPhysical="Virtual", WholeDisk=True,
                           Internal=False, DeviceNode=self.disk)
        filesystems.require_virtual_whole_disk(self.disk, information)
        for key, value in (("VirtualOrPhysical", "Physical"), ("Internal", True),
                           ("WholeDisk", False), ("DeviceNode", self.disk + "s1")):
            with self.subTest(key=key), self.assertRaisesRegex(RuntimeError, "Disk Arbitration"):
                filesystems.require_virtual_whole_disk(self.disk, dict(information, **{key: value}))

    def test_refuses_existing_filesystem_multiple_children_and_readonly(self):
        cases = [
            [{"dev-entry": self.disk, "mount-point": "/Volumes/Existing"}],
            [{"dev-entry": self.disk}, {"dev-entry": self.disk + "s1"}],
            [{"dev-entry": self.disk}, {"dev-entry": self.disk}],
        ]
        for entities in cases:
            with self.subTest(entities=entities), self.assertRaises(RuntimeError):
                self.check_target(entities)
        with self.assertRaisesRegex(RuntimeError, "one writable"):
            self.check_target([{"dev-entry": self.disk}], writable=False)

    def test_refuses_active_user_mounts_and_processes(self):
        for mounts, processes in (
            ("foreign on /private/tmp/.veracrypt_aux_mnt (osxfuse, local)\n", ""),
            ("foreign on /private/tmp/another/aux (lambcryptfs, local)\n", ""),
            ("", "/Applications/VeraCrypt.app/Contents/MacOS/VeraCrypt\n"),
        ):
            with self.subTest(mounts=mounts, processes=processes), self.assertRaises(RuntimeError):
                filesystems.require_empty_session(mounts, processes)


if __name__ == "__main__":
    unittest.main()
