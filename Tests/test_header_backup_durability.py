#!/usr/bin/env python3
# Copyright (c) 2026 LambCrypt contributors
# Governed by the Apache License 2.0, the full text of which is contained in
# the file License.txt included in LambCrypt binary and source code
# distribution packages.
"""Exercise header backup export and header restore through the text CLI.

Run after building: python3 -B Tests/test_header_backup_durability.py --binary src/Main/LambCrypt
Needs no sudo, mount or GUI. Each case uses a disposable 2 MiB container.

Checks that an existing backup file is replaced by rename (a hard link to the
old file keeps its old contents) and never truncated in place, that a declined
overwrite or a symlink target leaves the destination unchanged, that no
temporary file is left behind, and that restoring from an external backup
rewrites both the primary and the embedded backup header.
"""

import argparse
import os
from pathlib import Path
import subprocess
import sys
import tempfile

PASSWORD = "test1234567890ab"
HEADER_SIZE = 65536
BACKUP_SIZE = 2 * HEADER_SIZE


def run(binary, args, answers, cwd):
    result = subprocess.run([str(binary), "--text", *args, "--random-source=/dev/urandom"],
        input=answers, capture_output=True, text=True, cwd=cwd, timeout=300)
    return result.returncode, (result.stdout + result.stderr).replace("\r", "\n")


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def create_volume(binary, volume):
    code, output = run(binary, ["--non-interactive", "--create", str(volume), "--size=2M",
        "--password=" + PASSWORD, "--encryption=AES", "--hash=SHA-512", "--filesystem=none",
        "--pim=0", "-k", "", "--volume-type=normal", "--quick"], "", volume.parent)
    require(code == 0 and volume.stat().st_size == 2 * 1024 * 1024, "volume creation failed:\n" + output)


def backup(binary, volume, target, extra_args=(), overwrite_answer=""):
    # Password, PIM, keyfile, hidden volume, confirmation, file name, overwrite prompt.
    answers = f"{PASSWORD}\n\n\nn\ny\n{target}\n{overwrite_answer}"
    return run(binary, ["--backup-headers", str(volume), *extra_args], answers, volume.parent)


def header_state(binary, volume):
    """Opens the volume as the backup command does: 'primary', 'backup' or 'none'."""
    code, output = run(binary, ["--backup-headers", str(volume)], f"{PASSWORD}\n\n\nn\nn\n", volume.parent)
    if "is damaged" in output:
        return "backup"
    if "Incorrect password" in output:
        return "none"
    return "primary"


def zero(volume, offset, length):
    with open(volume, "r+b") as f:
        f.seek(offset)
        f.write(bytes(length))
        f.flush()
        os.fsync(f.fileno())


def restore_external(binary, volume, backup_file):
    code, output = run(binary, ["--restore-headers", str(volume)], f"2\ny\n{backup_file}\n{PASSWORD}\n\n\n", volume.parent)
    require("successfully restored" in output, "external restore failed:\n" + output)


def restore_internal(binary, volume):
    code, output = run(binary, ["--restore-headers", str(volume)], f"1\n{PASSWORD}\n\n\ny\n", volume.parent)
    require("successfully restored" in output, "internal restore failed:\n" + output)


def no_temporary_files(directory):
    leftovers = [p.name for p in directory.iterdir() if p.name.startswith(".")]
    require(not leftovers, f"temporary files left behind: {leftovers}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", type=Path, required=True)
    binary = parser.parse_args().binary.resolve()

    with tempfile.TemporaryDirectory() as temp:
        directory = Path(temp)
        volume = directory / "volume.hc"
        create_volume(binary, volume)

        new_backup = directory / "new.bak"
        code, output = backup(binary, volume, new_backup)
        require(code == 0 and new_backup.stat().st_size == BACKUP_SIZE, "new backup failed:\n" + output)

        replaced = directory / "replaced.bak"
        replaced.write_bytes(b"OLD")
        os.link(replaced, directory / "replaced.link")
        code, output = backup(binary, volume, replaced, overwrite_answer="y\n")
        require(code == 0 and replaced.stat().st_size == BACKUP_SIZE, "confirmed overwrite failed:\n" + output)
        require((directory / "replaced.link").read_bytes() == b"OLD", "backup was rewritten in place, not replaced by rename")

        declined = directory / "declined.bak"
        declined.write_bytes(b"KEEP")
        backup(binary, volume, declined, overwrite_answer="n\n")
        require(declined.read_bytes() == b"KEEP", "declined overwrite changed the file")

        forced = directory / "forced.bak"
        forced.write_bytes(b"OLD")
        code, output = backup(binary, volume, forced, extra_args=["--force"])
        require(code == 0 and forced.stat().st_size == BACKUP_SIZE, "--force overwrite failed:\n" + output)

        link = directory / "link.bak"
        link.symlink_to(new_backup.name)
        before = new_backup.read_bytes()
        code, output = backup(binary, volume, link, extra_args=["--force"])
        require(code != 0 and link.is_symlink() and new_backup.read_bytes() == before, "symlink target was replaced or followed:\n" + output)

        no_temporary_files(directory)
        print("PASS: header backup export replaces atomically and never truncates an existing backup")

        require(header_state(binary, volume) == "primary", "fresh volume does not open from its primary header")
        zero(volume, 0, HEADER_SIZE)
        require(header_state(binary, volume) == "backup", "zeroed primary header still opens")
        restore_external(binary, volume, new_backup)
        require(header_state(binary, volume) == "primary", "external restore did not rewrite the primary header")

        size = volume.stat().st_size
        zero(volume, size - 2 * HEADER_SIZE, 2 * HEADER_SIZE)
        restore_external(binary, volume, new_backup)
        zero(volume, 0, HEADER_SIZE)
        require(header_state(binary, volume) == "backup", "external restore did not rewrite the embedded backup header")

        restore_internal(binary, volume)
        require(header_state(binary, volume) == "primary", "internal restore did not rewrite the primary header")
        print("PASS: header restore rewrites the primary and embedded backup headers")


if __name__ == "__main__":
    try:
        main()
    except AssertionError as e:
        print(f"FAIL: {e}", file=sys.stderr)
        sys.exit(1)
