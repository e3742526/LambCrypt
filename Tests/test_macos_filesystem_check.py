#!/usr/bin/env python3
# Copyright (c) 2026 LambCrypt contributors
# Governed by the Apache License 2.0, the full text of which is contained in
# the file License.txt included in LambCrypt binary and source code
# distribution packages.
"""Exercise macOS filesystem-check media guards with synthetic registry data."""

import os
from pathlib import Path
import plistlib
import subprocess
import sys
import tempfile


ROOT = Path(__file__).resolve().parents[1]
BOOT = "11111111-2222-3333-4444-555555555555"
DEVICE = "/dev/disk42"
MEDIA = {"BSD Name": "disk42", "IORegistryEntryID": 220}
UNRELATED = {"BSD Name": "disk1", "IORegistryEntryID": 119}


def build_generator(work):
    source = (ROOT / "src/Core/Unix/MacOSX/CoreMacOSX.cpp").read_text()
    plist_helpers = source[source.index("\tclass CFHolder"):source.index("\tstatic string CanonicalizeDiskImagePath")]
    checks = source[source.index("\tstatic int64_t GetDiskMediaRegistryId"):
                    source.index("\tvoid CoreMacOSX::CheckFilesystem")]
    prelude = r"""
#include <CoreFoundation/CoreFoundation.h>
#include <cstdint>
#include <fstream>
#include <iostream>
#include <list>
#include <stdexcept>
#include <string>
using namespace std;
#define SRC_POS "fixture"
struct ParameterIncorrect : runtime_error { using runtime_error::runtime_error; };
struct MountServiceUnavailable : runtime_error {
    MountServiceUnavailable(const char *where, const wstring &) : runtime_error(where) {}
};
struct StringConverter {
    static wstring ToWide(const string &text) { return wstring(text.begin(), text.end()); }
};
static string RegistryFixture;
struct Process {
    static string ExecuteBounded(const string &path, const list<string> &arguments, int timeout) {
        if (path != "/usr/sbin/ioreg" || arguments != list<string>{"-a", "-r", "-c", "IOMedia", "-d", "1"}
                || timeout != 2000)
            throw runtime_error("unexpected registry query");
        ifstream stream(RegistryFixture);
        return string(istreambuf_iterator<char>(stream), {});
    }
};
"""
    main = r"""
int main(int argc, char **argv) {
    if (argc != 5) return 2;
    RegistryFixture = argv[1];
    try {
        const string device = argv[2], bsdName = device.substr(5);
        const auto identity = GetDiskMediaRegistryId(bsdName);
        cout << BuildFilesystemCheckScript(string(argv[4]) == "repair", device, bsdName, identity, argv[3]);
    } catch (const exception &) { return 1; }
}
"""
    unit = work / "generator.cpp"
    unit.write_text(prelude + plist_helpers + checks + main)
    generator = work / "generator"
    subprocess.run(["xcrun", "clang++", "-std=c++11", "-mmacosx-version-min=26.0",
                    unit, "-framework", "CoreFoundation", "-o", generator], check=True, timeout=20)
    return generator


def check_launch(work):
    generator = build_generator(work)
    selected = work / "selected.plist"
    for initial in ([UNRELATED], [MEDIA, MEDIA], [{"BSD Name": "disk42", "IORegistryEntryID": "220"}]):
        selected.write_bytes(plistlib.dumps(initial))
        refused = subprocess.run([generator, selected, DEVICE, BOOT, "repair"],
                                 capture_output=True, timeout=4)
        assert refused.returncode == 1 and not refused.stdout
    selected.write_bytes(plistlib.dumps([UNRELATED, MEDIA]))

    shims = {
        "/usr/sbin/sysctl": 'printf "%s\\n" "$TEST_BOOT"',
        "/usr/sbin/ioreg": 'cat "$TEST_REGISTRY"',
        "/usr/sbin/diskutil": 'printf "%s\\n" "$*" > "$TEST_CALLS"\nexit 7',
    }
    for command, body in shims.items():
        path = work / Path(command).name
        path.write_text(f"#!/bin/sh\n{body}\n")
        path.chmod(0o700)

    registry = work / "current.plist"
    calls = work / "calls"
    script = work / "check.command"
    for operation in ("verify", "repair"):
        contents = subprocess.check_output([generator, selected, DEVICE, BOOT, operation],
                                           text=True, timeout=4)
        for command in shims:
            contents = contents.replace(command, str(work / Path(command).name))
        for label, entries, boot, applies in (
            ("matching attachment", [UNRELATED, MEDIA], BOOT, True),
            ("same number, new media", [UNRELATED, dict(MEDIA, IORegistryEntryID=221)], BOOT, False),
            ("same media, different number", [dict(MEDIA, **{"BSD Name": "disk43"})], BOOT, False),
            ("different boot", [MEDIA], "11111111-2222-3333-4444-555555555556", False),
            ("missing entry", [], BOOT, False),
            ("malformed inventory", None, BOOT, False),
        ):
            registry.write_bytes(b"invalid plist" if entries is None else plistlib.dumps(entries))
            script.write_text(contents)
            calls.unlink(missing_ok=True)
            result = subprocess.run(
                ["/bin/sh", script], stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=5,
                env=dict(os.environ, TEST_BOOT=boot, TEST_REGISTRY=str(registry), TEST_CALLS=str(calls)),
            )
            assert not script.exists(), label
            if applies:
                assert result.returncode == 7 and calls.read_text() == f"{operation}Volume {DEVICE}\n", label
            else:
                assert result.returncode == 1 and not calls.exists(), label
                assert "selected volume is no longer confirmed" in result.stdout, label


if __name__ == "__main__":
    if sys.platform != "darwin":
        sys.exit("This test requires macOS Core Foundation and plutil")
    with tempfile.TemporaryDirectory(prefix="lambcrypt-fsck-test-", dir="/private/tmp") as directory:
        check_launch(Path(directory))
    print("PASS: filesystem-check command rejects reused disk numbers, a new boot, and unknown media")
