#!/usr/bin/env python3
"""Check the macOS build wrapper and FSKit bundle metadata without compiling."""

import os
from pathlib import Path
import plistlib
import shutil
import subprocess
import sys
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

    @unittest.skipUnless(sys.platform == "darwin", "FSKit requires macOS")
    def test_fskit_and_fuse_t_cannot_be_selected_together(self):
        result = subprocess.run(["/usr/bin/make", "-C", BUILD.parent, "-n", "WITHFSKIT=1", "WITHFUSET=1"],
                                capture_output=True, text=True, timeout=10)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("WITHFSKIT and WITHFUSET select different backends", result.stderr)

    @unittest.skipUnless(sys.platform == "darwin", "requires the macOS plutil command")
    def test_fskit_bundle_metadata_keeps_the_standard_app_preferred(self):
        build = self.script.parent
        src = build.parent
        main = src / "Main"
        main.mkdir()
        files = ("Main/Main.make", "Build/Resources/MacOSX/Info.plist.xml",
                 "Common/Tcdefs.h", "Driver/FSKit/Info.plist")
        for name in files:
            path = src / name
            path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(BUILD.parent / name, path)
        (build / "Makefile.inc").touch()
        (src.parent / "doc/html/en").mkdir(parents=True)
        icons = src / "Resources/Icons"
        icons.mkdir(parents=True)
        for name in ("LambCrypt.icns", "LambCrypt_Volume.icns"):
            (icons / name).touch()
        for name in ("LambCrypt-FSKit", "LambCrypt"):
            (main / name).touch()
        self.stub("xcrun", 'for last do :; done\n: > "$last"\n')
        command = ["/usr/bin/make", "-f", "Main.make", "bundle", "PLATFORM=MacOSX", "OBJS=", "PCH=",
                   "TC_BUILD_CONFIG=Release", f"BASE_DIR={src}", f"BUILD_INC={build}",
                   "WX_CONFIG=true", "CC=false", "VC_OSX_TARGET=26.0", "VC_OSX_SDK=27.2"]
        env = dict(os.environ, PATH=f"{self.bin}:/usr/bin:/bin")
        env.pop("VC_FSKIT_BUILD_VERSION", None)
        standard = subprocess.run([*command, "APPNAME=LambCrypt", "VC_OSX_FSKIT=0"], cwd=main,
                                  env=dict(env, VC_FSKIT_BUILD_VERSION="42"), capture_output=True,
                                  text=True, timeout=15)
        self.assertEqual(standard.returncode, 0, standard.stdout + standard.stderr)
        info = plistlib.loads((main / "LambCrypt.app/Contents/Info.plist").read_bytes())
        version = info["CFBundleShortVersionString"]
        self.assertEqual(info["CFBundleVersion"], version)
        self.assertEqual(info["CFBundleDocumentTypes"][0]["LSHandlerRank"], "Owner")
        contents = main / "LambCrypt-FSKit.app/Contents"
        plists = (contents / "Info.plist",
                  contents / "Extensions/LambCryptFSKit.appex/Contents/Info.plist")
        for value in (None, "42", "42.7.1", "42.7.1.4", "42..1", "42\n7"):
            with self.subTest(build_version=value):
                if value is not None:
                    env["VC_FSKIT_BUILD_VERSION"] = value
                result = subprocess.run([*command, "APPNAME=LambCrypt-FSKit", "VC_OSX_FSKIT=1"],
                                        cwd=main, env=env, capture_output=True,
                                        text=True, timeout=15)
                if value in (None, "42", "42.7.1"):
                    self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                    for path in plists:
                        info = plistlib.loads(path.read_bytes())
                        self.assertEqual(info["CFBundleShortVersionString"], version)
                        self.assertEqual(info["CFBundleVersion"], value or version)
                    app = plistlib.loads(plists[0].read_bytes())
                    self.assertEqual(app["CFBundleDocumentTypes"][0]["LSHandlerRank"], "Alternate")
                else:
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn("one to three dot-separated integers", result.stderr)


if __name__ == "__main__":
    unittest.main(verbosity=2)
