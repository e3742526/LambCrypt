"""Focused local updater guards. The canonical application is never modified."""

from pathlib import Path
import fcntl
import os
import plistlib
import sys
import tempfile
import unittest
from unittest.mock import patch


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src/Setup/MacOSX"))
import local_fskit_update as updater


class LocalUpdateTests(unittest.TestCase):
    def test_build_numbers_carry_and_increase(self):
        self.assertEqual(updater.next_version((1, 29, 99), None), "1.30.0")
        self.assertEqual(updater.next_version((1, 99, 99), None), "2.0.0")
        for requested in ("1.29.7", "1.29.8", "1.29.001", "1.29.100"):
            with self.subTest(requested=requested), self.assertRaises(ValueError):
                updater.next_version((1, 29, 8), requested)

    def test_mount_and_attachment_stop_update(self):
        for mounts, images in (
            (b"file:///worker on /private/tmp/aux (lambcryptfs, local)", []),
            (b"", [{"image-path": "/private/tmp/lambcrypt-fskit.example/mnt/volume.dmg"}]),
            (b"", [{}]),
        ):
            inventory = plistlib.dumps({"images": images})
            with patch.object(updater, "run", side_effect=[mounts, b"", inventory]):
                with self.assertRaises(RuntimeError):
                    updater.ensure_idle("TEST")

    def test_pending_marker_and_live_reservation_stop_update(self):
        with tempfile.TemporaryDirectory() as temp:
            home = Path(temp)
            group = home / "Library/Group Containers/TEST.lambcrypt-fskit"
            group.mkdir(mode=0o700, parents=True)
            locks = group / "mount-locks"
            locks.mkdir()
            worker = group / "worker"
            worker.mkdir()
            pending = worker / "attachment-pending"
            pending.touch()
            inventory = plistlib.dumps({"images": []})
            with patch.object(Path, "home", return_value=home), patch.object(updater, "run") as run:
                run.side_effect = [b"", b"", inventory]
                with self.assertRaisesRegex(RuntimeError, "pending attachment"):
                    updater.ensure_idle("TEST")
                pending.unlink()
                fd = os.open(locks / "slot-1", os.O_RDWR | os.O_CREAT, 0o600)
                try:
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    run.side_effect = [b"", b"", inventory]
                    with self.assertRaisesRegex(RuntimeError, "reservation is still held"):
                        updater.ensure_idle("TEST")
                finally:
                    os.close(fd)
                run.side_effect = [b"", b"", inventory]
                updater.ensure_idle("TEST")


if __name__ == "__main__":
    unittest.main()
