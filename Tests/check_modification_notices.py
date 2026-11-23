#!/usr/bin/env python3
# Copyright (c) 2026 LambCrypt contributors
# Governed by the Apache License 2.0. See License.txt and src/NOTICE.
"""Check that files changed from upstream VeraCrypt carry a modification notice.

The Apache License 2.0, section 4(b), requires modified files to carry
prominent notices stating that they were changed. This compares the working
tree with the upstream commit LambCrypt was forked from:

- Text files that allow comments must contain the notice marker.
- Other files (images, icons, help archives, XML catalogues and installer
  definitions) must be listed in MODIFICATIONS.md instead.

Run from the repository root of a full clone (the upstream commit must be
present). Pass --fix to insert missing notices and rewrite the list.
"""

import argparse
import re
import subprocess
import sys
from pathlib import Path

UPSTREAM_BASE = "f38c80905e0adb484fb32cb9d188c07bbc10c2ad"
MARKER = "Modified for LambCrypt"
NOTICE = ("Modified for LambCrypt by the LambCrypt contributors. "
          "Changes from VeraCrypt are in the git history; see UPSTREAM.md.")
LIST_FILE = Path("MODIFICATIONS.md")
LIST_BEGIN = "<!-- BEGIN FILES WITHOUT INLINE NOTICE -->"
LIST_END = "<!-- END FILES WITHOUT INLINE NOTICE -->"

C_STYLE = {".c", ".cpp", ".h", ".hpp", ".mm", ".m", ".swift", ".rc"}
HASH_STYLE = {".py", ".sh", ".yml", ".yaml", ".make", ".in", ".desktop",
              ".config", ".cmake", ".gitignore"}
HASH_NAMES = {"Makefile", "PKGBUILD", "CMakeLists.txt", "prerm", "postinst",
              "postrm", "preinst", "AppRun", ".gitignore"}


def style_for(path, data):
    if path.suffix in C_STYLE:
        return "c"
    if path.suffix in {".html", ".htm"}:
        return "html"
    if path.suffix == ".md":
        return "md"
    if path.suffix == ".bat":
        return "bat"
    if path.suffix in HASH_STYLE or path.name in HASH_NAMES:
        return "hash"
    if data.startswith(b"#!"):
        return "hash"
    if path.suffix == ".txt" or path.name == "NOTICE":
        return "text"
    return None


def modified_files():
    out = subprocess.run(["git", "diff", "--name-status", "-M", "-z", UPSTREAM_BASE],
        check=True, capture_output=True).stdout.decode("utf-8").split("\0")
    files = []
    i = 0
    while i < len(out) and out[i]:
        status = out[i]
        if status.startswith("R") or status.startswith("C"):
            # A pure rename keeps the upstream content and needs no notice.
            if status != "R100":
                files.append(out[i + 2])
            i += 3
        else:
            if status == "M":
                files.append(out[i + 1])
            i += 2
    return sorted(set(files))


def insert_notice(data, style):
    bom = b"\xef\xbb\xbf" if data.startswith(b"\xef\xbb\xbf") else b""
    text = data[len(bom):].decode("utf-8")
    nl = "\r\n" if "\r\n" in text else "\n"
    lines = text.split(nl)
    at = 0
    if style == "c":
        line = f"/* {NOTICE} */"
    elif style == "hash":
        line = f"# {NOTICE}"
        if lines and lines[0].startswith("#!"):
            at = 1
        if len(lines) > at and re.match(r"#.*coding[:=]", lines[at]):
            at += 1
    elif style == "html":
        line = f"<!-- {NOTICE} -->"
        if lines and lines[0].lower().startswith("<!doctype"):
            at = 1
    elif style == "md":
        line = f"<!-- {NOTICE} -->"
        if lines and lines[0].strip() == "---":
            # Keep YAML front matter (issue templates) first.
            end = next((n for n in range(1, len(lines)) if lines[n].strip() == "---"), None)
            if end is not None:
                at = end + 1
    elif style == "bat":
        line = f"@REM {NOTICE}"
        if lines and lines[0].strip().lower() == "@echo off":
            at = 1
    else:
        line = NOTICE
    lines.insert(at, line)
    return bom + nl.join(lines).encode("utf-8")


def read_list():
    if not LIST_FILE.exists():
        return set()
    text = LIST_FILE.read_text(encoding="utf-8")
    if LIST_BEGIN not in text:
        return set()
    body = text.split(LIST_BEGIN, 1)[1].split(LIST_END, 1)[0]
    return set(re.findall(r"^- `([^`]+)`$", body, re.M))


def write_list(paths):
    text = LIST_FILE.read_text(encoding="utf-8")
    head, rest = text.split(LIST_BEGIN, 1)
    tail = rest.split(LIST_END, 1)[1]
    body = "\n".join(f"- `{p}`" for p in sorted(paths))
    LIST_FILE.write_text(f"{head}{LIST_BEGIN}\n{body}\n{LIST_END}{tail}", encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--fix", action="store_true", help="insert missing notices and update the list")
    args = parser.parse_args()

    missing, unlisted, listed_needed = [], [], set()
    for name in modified_files():
        path = Path(name)
        data = path.read_bytes()
        style = style_for(path, data)
        if style is None or b"\0" in data:
            listed_needed.add(name)
            continue
        if MARKER.encode() in data:
            continue
        missing.append(name)
        if args.fix:
            path.write_bytes(insert_notice(data, style))

    listed = read_list()
    unlisted = sorted(listed_needed - listed)
    stale = sorted(listed - listed_needed)
    if args.fix and (unlisted or stale):
        write_list(listed_needed)

    if args.fix:
        print(f"Inserted {len(missing)} notices; {len(listed_needed)} files listed in {LIST_FILE}.")
        return 0
    for name in missing:
        print(f"missing notice: {name}")
    for name in unlisted:
        print(f"not listed in {LIST_FILE}: {name}")
    for name in stale:
        print(f"listed in {LIST_FILE} but no longer modified or now commentable: {name}")
    if missing or unlisted or stale:
        print("Run with --fix to update.", file=sys.stderr)
        return 1
    print("PASS: every file changed from upstream VeraCrypt carries or is listed with a modification notice")
    return 0


if __name__ == "__main__":
    sys.exit(main())
