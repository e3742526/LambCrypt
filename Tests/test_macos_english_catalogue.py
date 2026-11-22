#!/usr/bin/env python3
"""Compile and exercise the embedded Unix English catalogue loader on macOS.

Pass the src directory and wx-config used for a matching LambCrypt build.
The test uses a temporary catalogue and opens no volume or GUI window.
"""

import argparse
from pathlib import Path
import shlex
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET


ROOT = Path(__file__).resolve().parents[1]
TEST_SOURCE = r"""
#include "Main/LanguageStrings.h"
#include <iostream>

int main ()
{
    VeraCrypt::LangString.Init();
    if (VeraCrypt::LangString.Get ("ESCAPE_TEXT_TEST") != L"Caf\u00e9 & <English>")
    {
        std::cerr << "embedded English selection or XML entity decoding failed\n";
        return 1;
    }
    if (VeraCrypt::LangString.Get ("ESCAPE_LOADER_TEST") != L"Line\nTab\tC:\\new\\Folder")
    {
        std::cerr << "embedded Unix catalogue decoded a tab or literal backslash incorrectly\n";
        return 1;
    }
    std::cout << "PASS: embedded English selection, XML entities, newlines, tabs, and literal backslashes\n";
}
"""


def make_catalogue(work):
    header = work / "Common/Language.xml.h"
    header.parent.mkdir()
    catalogue = ET.parse(ROOT / "src/Common/Language.xml")
    localization = catalogue.getroot().find("localization")
    for language, key, text in (
        ("en", "ESCAPE_LOADER_TEST", r"Line\nTab\tC:\\new\\Folder"),
        ("en", "ESCAPE_TEXT_TEST", "Café & <English>"),
        ("fr", "ESCAPE_TEXT_TEST", "Remplacement"),
    ):
        ET.SubElement(localization, "entry", lang=language, key=key).text = text
    data = ET.tostring(catalogue.getroot(), encoding="utf-8")
    header.write_text(",\n".join(
        ",".join(f"0x{byte:02x}" for byte in data[start:start + 32])
        for start in range(0, len(data), 32)
    ), encoding="ascii")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build-dir", required=True, type=Path)
    parser.add_argument("--wx-config", required=True, type=Path)
    args = parser.parse_args()
    if sys.platform != "darwin":
        parser.error("This harness links the macOS application dependencies")

    def wx_flags(*options):
        return shlex.split(subprocess.check_output([
            args.wx_config.resolve(), "--unicode", "--static", *options
        ], text=True, timeout=10))

    with tempfile.TemporaryDirectory(prefix="lambcrypt-english-") as directory:
        work = Path(directory)
        make_catalogue(work)
        test = work / "test.cpp"
        test.write_text(TEST_SOURCE, encoding="ascii")
        source = ROOT / "src"
        subprocess.run([
            "xcrun", "--sdk", "macosx", "clang++", "-std=c++11", "-O2", "-mmacosx-version-min=26.0",
            "-DTC_UNIX", "-DTC_BSD", "-DTC_MACOSX", "-DARGON2_NO_THREADS", "-D_FILE_OFFSET_BITS=64",
            "-I", work, "-I", source, "-I", source / "Main", "-I", source / "Common",
            "-I", source / "Crypto", "-I", source / "Crypto/Argon2/include", "-I", source / "PKCS11",
            *wx_flags("--cxxflags"), source / "Main/LanguageStrings.cpp", source / "Main/Xml.cpp",
            test, args.build_dir.resolve() / "Platform/Platform.a", *wx_flags("--libs", "base"),
            "-Wl,-dead_strip", "-o", work / "loader",
        ], check=True, timeout=40)
        subprocess.run([work / "loader"], check=True, timeout=10)


if __name__ == "__main__":
    main()
