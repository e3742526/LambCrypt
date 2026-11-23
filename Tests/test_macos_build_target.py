#!/usr/bin/env python3
# Copyright (c) 2026 LambCrypt contributors
# Governed by the Apache License 2.0, the full text of which is contained in
# the file License.txt included in LambCrypt binary and source code
# distribution packages.
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
        self.stub("wx-config", "exit 0\n")
        self.stub("brew", '[ "$1" = --prefix ] && [ "$2" = wxwidgets ]\n'
                  'dirname "$(dirname "$0")"\n')
        self.stub("make", 'for target do :; done\n'
                  'printf "build-settings %s %s %s %s\\n" '
                  '"$VC_OSX_TARGET" "$VC_OSX_SDK" "$LOCAL_DEVELOPMENT_BUILD" "$target"\n')

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
        self.assertEqual(self.build_settings("-b"),
                         [["26.0", "27.2", "true", target] for target in ("clean", "bundle")])

    def test_source_build_uses_the_same_default(self):
        self.assertEqual(self.build_settings(),
                         [["26.0", "27.2", "true", target] for target in ("clean", "bundle")])

    def test_explicit_homebrew_target_is_preserved(self):
        self.assertEqual(self.build_settings("-b", "-t", "26.4", "-s"),
                         [["26.4", "27.2", "true", target] for target in ("clean", "prepare")])

    def test_local_package_uses_signed_app(self):
        self.assertEqual(self.build_settings("-b", "-p")[-1][-1], "package")

    @unittest.skipUnless(sys.platform == "darwin", "FSKit requires macOS")
    def test_legacy_backends_cannot_be_selected(self):
        for option, diagnostic in (("WITHFUSET=1", "WITHFUSET is retired"),
                                   ("WITHFSKIT=0", "FSKit is required on macOS")):
            with self.subTest(option=option):
                result = subprocess.run(["/usr/bin/make", "-C", BUILD.parent, "-n", option],
                                        capture_output=True, text=True, timeout=10)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(diagnostic, result.stderr)

    @unittest.skipUnless(sys.platform == "darwin", "FSKit requires macOS")
    def test_default_make_does_not_query_fuse_packages(self):
        self.stub("pkg-config", 'case "$*" in *fuse*) touch "$PKG_CONFIG_FUSE_PROBE" ;; esac\nexit 1\n')
        probe = self.root / "fuse-probe"
        target = self.root / "backend.mk"
        target.write_text("report-backend:\n\t@printf '%s\\n' '$(APPNAME)' '$(C_CXX_FLAGS)' '$(LFLAGS)'\n")
        result = subprocess.run(["/usr/bin/make", "-C", BUILD.parent, "-f", "Makefile", "-f", target,
                                 f"PKG_CONFIG={self.bin / 'pkg-config'}", "report-backend"],
                                env=dict(os.environ, PKG_CONFIG_FUSE_PROBE=str(probe)),
                                capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("LambCrypt-FSKit", result.stdout)
        self.assertIn("-DVC_MACOSX_FSKIT", result.stdout)
        self.assertIn("-framework FSKit", result.stdout)
        self.assertFalse(probe.exists(), "macOS Makefile queried a FUSE package")

    @unittest.skipUnless(sys.platform == "darwin", "requires macOS signing tools")
    def test_development_bundle_verifier_requires_target_device(self):
        bundle = os.environ.get("VC_TEST_FSKIT_DEV_BUNDLE")
        if not bundle:
            self.skipTest("set VC_TEST_FSKIT_DEV_BUNDLE to a signed development app for this Mac")
        verifier = BUILD.parent / "Setup/MacOSX/verify_fskit_bundle.sh"
        command = ["/bin/bash", verifier, bundle]
        env = dict(os.environ)
        env.pop("VC_FSKIT_TARGET_UDID", None)
        valid = subprocess.run(command, env=env, capture_output=True, text=True, timeout=15)
        self.assertEqual(valid.returncode, 0, valid.stdout + valid.stderr)
        env["VC_FSKIT_TARGET_UDID"] = "00000000-0000-0000-0000-000000000000"
        wrong = subprocess.run(command, env=env, capture_output=True, text=True, timeout=15)
        self.assertEqual(wrong.returncode, 1, wrong.stdout + wrong.stderr)
        self.assertIn("does not authorize the target Mac's exact Provisioning UDID", wrong.stderr)

    @unittest.skipUnless(sys.platform == "darwin", "requires the macOS plutil command")
    def test_native_bundle_metadata_supports_side_by_side_installation(self):
        build = self.script.parent
        src = build.parent
        main = src / "Main"
        main.mkdir()
        files = ("Main/Main.make", "Build/Resources/MacOSX/Info.plist.xml",
                 "Common/Tcdefs.h", "Driver/FSKit/Info.plist", "License.txt", "NOTICE")
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
        (main / "LambCrypt-FSKit").touch()
        self.stub("xcrun", 'for last do :; done\n: > "$last"\n')
        command = ["/usr/bin/make", "-f", "Main.make", "bundle", "PLATFORM=MacOSX", "OBJS=", "PCH=",
                   "TC_BUILD_CONFIG=Release", f"BASE_DIR={src}", f"BUILD_INC={build}",
                   "WX_CONFIG=true", "CC=false", "VC_OSX_TARGET=26.0", "VC_OSX_SDK=27.2"]
        env = dict(os.environ, PATH=f"{self.bin}:/usr/bin:/bin")
        env.pop("VC_FSKIT_BUILD_VERSION", None)
        contents = main / "LambCrypt-FSKit.app/Contents"
        plists = (contents / "Info.plist",
                  contents / "Extensions/LambCryptFSKit.appex/Contents/Info.plist")
        for value in (None, "42", "42.7.1", "42.7.1.4", "42..1", "42\n7"):
            with self.subTest(build_version=value):
                if value is not None:
                    env["VC_FSKIT_BUILD_VERSION"] = value
                result = subprocess.run([*command, "APPNAME=LambCrypt-FSKit"],
                                        cwd=main, env=env, capture_output=True,
                                        text=True, timeout=15)
                if value in (None, "42", "42.7.1"):
                    self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                    app = plistlib.loads(plists[0].read_bytes())
                    version = app["CFBundleShortVersionString"]
                    for path in plists:
                        info = plistlib.loads(path.read_bytes())
                        self.assertEqual(info["CFBundleShortVersionString"], version)
                        self.assertEqual(info["CFBundleVersion"], value or version)
                    self.assertEqual(app["CFBundleDocumentTypes"][0]["LSHandlerRank"], "Alternate")
                else:
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn("one to three dot-separated integers", result.stderr)


if __name__ == "__main__":
    unittest.main(verbosity=2)
