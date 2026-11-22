#!/usr/bin/env python3
"""Check the macOS build wrapper's SDK and deployment settings without compiling."""

import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


BUILD = Path(__file__).resolve().parents[1] / "src/Build"


class MacOSBuildTargetTests(unittest.TestCase):
    def setUp(self):
        work = tempfile.TemporaryDirectory(prefix="lambcrypt-build-target-")
        self.addCleanup(work.cleanup)
        self.root = Path(work.name)
        build = self.root / "checkout/src/Build"
        (build / "Tools").mkdir(parents=True)
        self.script = build / "build_lambcrypt_macosx.sh"
        shutil.copyfile(BUILD / self.script.name, self.script)
        shutil.copyfile(BUILD / "Tools/private_tmp_dir.sh", build / "Tools/private_tmp_dir.sh")
        (self.root / "wxWidgets-3.2.10").mkdir()
        wx_build = self.root / "wxBuild-3.2.10"
        wx_build.mkdir()
        (wx_build / "wx-config").symlink_to("wx-config-stub")
        self.bin = self.root / "bin"
        self.bin.mkdir()
        self.stub("xcrun", "printf '%s\\n' 27.2\n")
        self.stub("brew", 'case "$1" in\n'
                  '  --cellar) printf "%s\\n" /local/Cellar/wxwidgets ;;\n'
                  '  list) printf "%s\\n" "wxwidgets 3.2.10" ;;\n'
                  '  *) exit 2 ;;\nesac\n')
        self.stub("yasm", "exit 0\n")
        self.stub("make", 'printf "build-settings %s %s %s\\n" '
                  '"$VC_OSX_TARGET" "$VC_OSX_SDK" "$VC_OSX_FUSET"\n')

    def stub(self, name, command):
        path = self.bin / name
        path.write_text("#!/bin/sh\nset -eu\n" + command)
        path.chmod(0o755)

    def build_settings(self, *args):
        env = dict(os.environ, PATH=f"{self.bin}:/usr/bin:/bin")
        result = subprocess.run(["/bin/bash", self.script, *args], env=env,
                                capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        settings = [line.removeprefix("build-settings ").split() for line in result.stdout.splitlines()
                    if line.startswith("build-settings ")]
        self.assertTrue(settings, result.stdout)
        return settings

    def test_homebrew_build_uses_tahoe_on_a_newer_sdk(self):
        for settings in self.build_settings("-b"):
            self.assertEqual(settings, ["26.0", "27.2", "0"])

    def test_source_build_uses_the_same_default(self):
        for settings in self.build_settings("-l", "-f"):
            self.assertEqual(settings, ["26.0", "27.2", "1"])

    def test_explicit_homebrew_target_is_preserved(self):
        for settings in self.build_settings("-b", "-t", "26.4"):
            self.assertEqual(settings, ["26.4", "27.2", "0"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
