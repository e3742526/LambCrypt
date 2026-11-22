#!/usr/bin/env python3
"""Check text-mode keyfile and header-backup overwrite behavior without mounting."""

import argparse
from concurrent.futures import ThreadPoolExecutor
import os
from pathlib import Path
import shutil
import subprocess
import tempfile


ROOT = Path(__file__).resolve().parents[1]
SAVE = b"existing output must be preserved"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--veracrypt", type=Path, default=ROOT / "src/Main/veracrypt")
    args = parser.parse_args()

    with tempfile.TemporaryDirectory(prefix="vc-overwrite-") as directory:
        work = Path(directory)
        env = dict(os.environ, LC_ALL="C", XDG_CONFIG_HOME=str(work))
        binary = str(args.veracrypt.resolve())
        fixture = work / "volume.hc"
        shutil.copyfile(ROOT / "Tests/test.sha512.hc", fixture)

        def run(*arguments, replies=""):
            return subprocess.run(
                [binary, "--text", "--random-source=/dev/urandom", *map(str, arguments)],
                input=replies, capture_output=True, text=True, env=env, timeout=30,
            )

        def status(result, expected):
            if result.returncode != expected:
                raise AssertionError(f"Expected exit {expected}: {result.stdout}{result.stderr}")

        key = work / "keyfile"
        key.write_bytes(SAVE)
        status(run("--non-interactive", "--create-keyfile", key), 1)
        assert key.read_bytes() == SAVE
        status(run("--non-interactive", "--force", "--create-keyfile", key), 0)
        assert key.stat().st_size == 128 and key.read_bytes() != SAVE

        link = work / "symlink"
        link.symlink_to(work / "missing")
        status(run("--non-interactive", "--create-keyfile", link), 1)
        assert link.is_symlink() and not link.exists()

        shared = work / "new-keyfile"
        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(
                lambda _: run("--non-interactive", "--create-keyfile", shared), range(2)
            ))
        assert sorted(result.returncode for result in results) == [0, 1], results
        assert shared.stat().st_size == 128

        backup = work / "header"
        backup_args = ("--backup-headers", fixture, "--hash=sha512")
        replies = f"test\n\n\nn\ny\n{backup}\n"
        status(run(*backup_args, replies=replies), 0)
        backup_size = backup.stat().st_size
        assert backup_size > 0

        backup.write_bytes(SAVE)
        declined = run(*backup_args, replies=replies + "n\n")
        assert "do you really want to overwrite it?" in declined.stdout
        assert backup.read_bytes() == SAVE
        status(run("--non-interactive", *backup_args, replies=replies), 1)
        assert backup.read_bytes() == SAVE
        status(run(*backup_args, replies=replies + "y\n"), 0)
        assert backup.stat().st_size == backup_size
        backup.write_bytes(SAVE)
        status(run("--force", *backup_args, replies=replies), 0)
        assert backup.stat().st_size == backup_size

    print("PASS: keyfile and header-backup overwrite handling")


if __name__ == "__main__":
    main()
