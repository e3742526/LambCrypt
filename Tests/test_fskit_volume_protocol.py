#!/usr/bin/env python3
"""Exercise the production Swift and C++ FSKit protocol on a disposable volume.

Usage: python3 Tests/test_fskit_volume_protocol.py --build-dir /path/to/built/src
Requires a matching macOS build and Xcode. Uses no filesystem extension or mount.
"""

import argparse
import contextlib
import errno
import selectors
import shutil
import socket
import struct
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path

from test_volume_read import DIGESTS


ROOT = Path(__file__).resolve().parents[1]
FSKIT = ROOT / "src/Driver/FSKit"
FIXTURE = ROOT / "Tests/test.sha512.hc"
SIGNATURE = 0x3346434C

CLIENT = r"""
import CryptoKit
import Foundation

@main
struct Client {
    static func main() throws {
        let connection = try VolumeConnection(resource: URL(fileURLWithPath: CommandLine.arguments[1]))
        let metadata = try connection.inspect()
        let identifier = metadata.identifier
        precondition(metadata.imageSize == 262144 && metadata.controlSize > 0)
        var slice = Data(repeating: 0xa5, count: 5)
        var completed = 0
        let writable = CommandLine.arguments.last == "--write"
        precondition(metadata.readOnly != writable)
        if CommandLine.arguments.count == 4 && !writable {
            guard let stale = UUID(uuidString: CommandLine.arguments[3]) else { fatalError("invalid UUID") }
            precondition(stale != identifier)
            do {
                try slice.withUnsafeMutableBytes {
                    try connection.read(.readImage, expecting: stale, at: 0, into: $0, completed: &completed)
                }
                fatalError("replaced worker accepted an image read")
            } catch let error as POSIXError {
                precondition(error.code == .ESTALE && completed == 0 && slice.allSatisfy { $0 == 0 })
            }
            do {
                _ = try connection.inspect(expectedIdentifier: stale)
                fatalError("replaced worker accepted a bound metadata request")
            } catch let error as POSIXError {
                precondition(error.code == .ESTALE)
            }
        }

        var image = Data(count: Int(metadata.imageSize))
        try image.withUnsafeMutableBytes {
            try connection.read(.readImage, expecting: identifier, at: 0, into: $0, completed: &completed)
        }
        precondition(completed == image.count)
        let hash = SHA256.hash(data: image).map { String(format: "%02x", $0) }.joined()
        precondition(hash == CommandLine.arguments[2])

        var tail = Data(repeating: 0xa5, count: VolumeConnection.maximumTransfer + 1)
        try tail.withUnsafeMutableBytes {
            try connection.read(.readImage, expecting: identifier, at: metadata.imageSize - 3,
                                into: $0, completed: &completed)
        }
        precondition(completed == 3 && tail.prefix(3) == image.suffix(3))
        precondition(tail.dropFirst(3).allSatisfy { $0 == 0 })
        slice = Data(repeating: 0xa5, count: 5)
        try slice.withUnsafeMutableBytes {
            try connection.read(.readImage, expecting: identifier, at: UInt64.max, into: $0, completed: &completed)
        }
        precondition(completed == 0 && slice.allSatisfy { $0 == 0 })
        var control = Data(count: Int(metadata.controlSize))
        try control.withUnsafeMutableBytes {
            try connection.read(.readControl, expecting: identifier, at: 0, into: $0, completed: &completed)
        }
        precondition(completed == control.count)
        if writable {
            let bytes: [UInt8] = [0x5a, 0xc3, 0x13]
            try bytes.withUnsafeBytes { try connection.write($0, expecting: identifier, at: 511) }
            try connection.flush(expecting: identifier)
            try slice.withUnsafeMutableBytes {
                try connection.read(.readImage, expecting: identifier, at: 510, into: $0, completed: &completed)
            }
            precondition(completed == 5 && Array(slice) == [image[510]] + bytes + [image[514]])
            do {
                try bytes.withUnsafeBytes { try connection.write($0, expecting: identifier, at: metadata.imageSize - 1) }
                fatalError("write past end succeeded")
            } catch let error as POSIXError {
                precondition(error.code == .ENOSPC)
            }
        }
        print(identifier.uuidString)
    }
}
"""


def build(build_dir, work):
    source = ROOT / "src"
    subprocess.run([
        "clang++", "-std=c++11", "-O2", "-DTC_UNIX", "-DTC_BSD", "-DTC_MACOSX",
        "-DARGON2_NO_THREADS", "-D_FILE_OFFSET_BITS=64",
        "-I", source, "-I", source / "Crypto", "-I", source / "Crypto/Argon2/include",
        "-I", source / "PKCS11", ROOT / "Tests/fskit_volume_protocol_test.cpp",
        FSKIT / "VolumeProtocol.cpp", build_dir / "Volume/Volume.a",
        build_dir / "Platform/Platform.a", "-framework", "CoreFoundation",
        "-framework", "IOKit", "-o", work / "server",
    ], check=True)
    (work / "Client.swift").write_text(CLIENT)
    subprocess.run([
        "xcrun", "swiftc", "-parse-as-library", FSKIT / "VolumeConnection.swift",
        work / "Client.swift", "-o", work / "client",
    ], check=True)


@contextlib.contextmanager
def serve(work, count, writable=False):
    start = time.time_ns() // 1000
    with subprocess.Popen([
        work / "server", work / FIXTURE.name, work / "io", str(count),
        *(["write"] if writable else []),
    ], stdout=subprocess.PIPE, text=True) as process:
        try:
            with selectors.DefaultSelector() as selector:
                selector.register(process.stdout, selectors.EVENT_READ)
                if not selector.select(timeout=10):
                    raise TimeoutError("The fixture worker did not start")
                serial = int(process.stdout.readline())
            assert start <= serial <= time.time_ns() // 1000, "The mount serial is not a wall-clock timestamp"
            yield serial
            assert process.wait(timeout=10) == 0
        finally:
            if process.poll() is None:
                process.kill()


def exchange(work, packet):
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
        connection.settimeout(5)
        connection.connect(str(work / "io"))
        connection.sendall(packet)
        connection.shutdown(socket.SHUT_WR)
        with connection.makefile("rb") as response:
            return response.read()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build-dir", required=True, type=Path)
    args = parser.parse_args()
    if sys.platform != "darwin":
        parser.error("This test exercises the macOS protocol")
    with tempfile.TemporaryDirectory(prefix="lambcrypt-ipc-", dir="/private/tmp") as directory:
        work = Path(directory)
        shutil.copyfile(FIXTURE, work / FIXTURE.name)
        build(args.build_dir.resolve(), work)
        command = [work / "client", work, DIGESTS[FIXTURE.name]]
        with serve(work, 11) as first_serial:
            generation = uuid.UUID(subprocess.check_output(command, text=True, timeout=20).strip())
            for fields in (
                (0x3246434C, 2, 0, 32, 0),
                (SIGNATURE, 0xFFFFFFFF, 0, 32, 0),
                (SIGNATURE, 2, 0, 1024 * 1024 + 1, 0),
                (SIGNATURE, 2, 0, 32, 1),
            ):
                packet = struct.pack("<IIQII16s", *fields, generation.bytes)
                assert exchange(work, packet) == struct.pack("<II", errno.EINVAL, 0)
            assert exchange(work, b"short request") == b""
            read_only_write = struct.pack("<IIQII16s", SIGNATURE, 4, 0, 1, 0, generation.bytes) + b"x"
            assert exchange(work, read_only_write) == struct.pack("<II", errno.EROFS, 0)
        with serve(work, 7) as later_serial:
            assert later_serial > first_serial
            subprocess.run([*command, str(generation)], check=True, timeout=20)
        with serve(work, 9, writable=True):
            subprocess.run([*command, "--write"], check=True, timeout=20)
    print("PASS: VeraCrypt payload, control metadata, EOF, malformed input, worker identity, writes and sync")


if __name__ == "__main__":
    main()
