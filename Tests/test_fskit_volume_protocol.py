#!/usr/bin/env python3
"""Exercise the production FSKit provider and protocol on a disposable volume.

Usage: python3 Tests/test_fskit_volume_protocol.py --build-dir /path/to/built/src
Requires a matching macOS build and Xcode. Calls the Swift provider directly,
without launching a filesystem extension or creating a mount.
"""

import argparse
from concurrent.futures import ThreadPoolExecutor
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
import FSKit

final class TestDirectoryEntryPacker {
    struct Entry {
        let name: String
        let type: FSItem.ItemType
        let id: FSItem.Identifier
        let next: FSDirectoryCookie
        let attributes: FSItem.Attributes?
    }

    var entries: [Entry] = []
    let capacity: Int

    init(capacity: Int) { self.capacity = capacity }

    func packEntry(name: FSFileName, itemType: FSItem.ItemType, itemID: FSItem.Identifier,
                   nextCookie: FSDirectoryCookie, attributes: FSItem.Attributes?) -> Bool {
        guard entries.count < capacity else { return false }
        entries.append(Entry(name: name.string!, type: itemType, id: itemID, next: nextCookie, attributes: attributes))
        return true
    }
}

@main
struct Client {
    static func expect(_ code: POSIXError.Code, _ operation: () throws -> Void) throws {
        do {
            try operation()
            fatalError("expected \(code)")
        } catch let error as POSIXError {
            precondition(error.code == code, "expected \(code), got \(error.code)")
        }
    }

    static func checkVolumeCallbacks(_ connection: VolumeConnection, _ metadata: VolumeConnection.Metadata,
                                     taskOptions: [String], readOnly: Bool) {
        let volume = VolumeImage(connection: connection, metadata: metadata, taskOptions: taskOptions)
        var image: FSItem?
        volume.lookupItem(named: FSFileName(string: "volume.dmg"), inDirectory: volume.testRoot) { item, _, error in
            precondition(error == nil)
            image = item
        }
        guard let image else { fatalError("provider did not return the image item") }
        volume.getAttributes(FSItem.GetAttributesRequest(), of: image) { attributes, error in
            precondition(error == nil && attributes?.mode == (readOnly ? 0o400 : 0o600),
                         "incorrect image permissions for load options \(taskOptions)")
        }
        volume.openItem(image, modes: .read) { error in precondition(error == nil) }
        volume.openItem(image, modes: [.read, .write]) { error in
            if readOnly {
                precondition((error as? POSIXError)?.code == .EROFS)
            } else {
                precondition(error == nil)
            }
        }
        if readOnly {
            volume.write(contents: Data([0x82]), to: image, at: 0) { count, error in
                precondition(count == 0 && (error as? POSIXError)?.code == .EROFS)
            }
        }
    }

    static func checkDirectoryEnumeration(_ volume: VolumeImage) {
        func enumerate(at cookie: FSDirectoryCookie, verifier: FSDirectoryVerifier,
                       attributes: FSItem.GetAttributesRequest? = nil, capacity: Int = 10)
        -> (FSDirectoryVerifier, [TestDirectoryEntryPacker.Entry], Error?) {
            let packer = TestDirectoryEntryPacker(capacity: capacity)
            var response: (FSDirectoryVerifier, Error?)?
            volume.enumerateDirectory(volume.testRoot, startingAt: cookie, verifier: verifier,
                                      attributes: attributes, packer: packer) { currentVerifier, error in
                response = (currentVerifier, error)
            }
            guard let (currentVerifier, error) = response else { fatalError("missing enumeration reply") }
            return (currentVerifier, packer.entries, error)
        }

        let (version, first, firstError) = enumerate(at: .initial, verifier: .initial, capacity: 2)
        precondition(firstError == nil && version.rawValue != 0, "enumeration returned the initial verifier")
        precondition(first.map(\.name) == [".", ".."])
        precondition(first.allSatisfy { $0.type == .directory && $0.id == .rootDirectory && $0.attributes == nil })
        let (resumedVersion, rest, resumeError) = enumerate(at: first[1].next, verifier: version)
        precondition(resumeError == nil && resumedVersion == version)
        precondition(rest.map(\.name) == ["volume.dmg", "control"])
        precondition(rest.allSatisfy { $0.type == .file && $0.attributes == nil })
        let (eofVersion, end, eofError) = enumerate(at: rest[1].next, verifier: version)
        precondition(eofError == nil && eofVersion == version && end.isEmpty)

        let (attributeVersion, attributed, attributeError) = enumerate(at: first[0].next, verifier: version,
                                                                       attributes: FSItem.GetAttributesRequest())
        precondition(attributeError == nil && attributeVersion == version)
        precondition(attributed.map(\.name) == rest.map(\.name) && attributed.map(\.next) == rest.map(\.next))
        precondition(attributed.allSatisfy { $0.attributes?.fileID == $0.id }, "entry attributes are missing")

        for (cookie, verifier) in [(FSDirectoryCookie(UInt64.max), version), (first[1].next, .initial)] {
            let (_, invalidEntries, error) = enumerate(at: cookie, verifier: verifier)
            guard let error else { fatalError("invalid directory continuation was accepted") }
            let osError = error as NSError
            precondition(invalidEntries.isEmpty && osError.domain == NSPOSIXErrorDomain &&
                         osError.code == FSError.Code.invalidDirectoryCookie.rawValue, "wrong invalid directory cookie error")
        }
    }

    static func main() throws {
        let resource = URL(fileURLWithPath: CommandLine.arguments[1])
        if CommandLine.arguments.last == "--path-errors" {
            try expect(.ENOENT) {
                _ = try VolumeConnection(resource: resource.appendingPathComponent("missing"))
            }
            try expect(.EACCES) {
                _ = try VolumeConnection(resource: resource.appendingPathComponent("not-private"))
            }
            let connection = try VolumeConnection(resource: resource)
            try expect(.ENOENT) { _ = try connection.inspect() }
            var data = Data(repeating: 0xa5, count: 8)
            var completed = 0
            try expect(.ENOENT) {
                try data.withUnsafeMutableBytes {
                    try connection.read(.readImage, expecting: UUID(), at: 0, into: $0, completed: &completed)
                }
            }
            precondition(completed == 0 && data.allSatisfy { $0 == 0 })
            let endpoint = resource.appendingPathComponent("io")
            try Data().write(to: endpoint)
            defer { try? FileManager.default.removeItem(at: endpoint) }
            try expect(.EACCES) { _ = try connection.inspect() }
            print("PASS: missing resources and workers report ENOENT, rejected paths report EACCES")
            return
        }
        let connection = try VolumeConnection(resource: resource)
        let mode = CommandLine.arguments.last
        if mode == "--enumeration" {
            let volume = VolumeImage(connection: connection, metadata: try connection.inspect(), taskOptions: [])
            checkDirectoryEnumeration(volume)
            return
        }
        if mode == "--inspect-metadata" {
            let errorCode = Int32(CommandLine.arguments[2])!
            if errorCode == 0 {
                _ = try connection.inspect()
            } else {
                try expect(POSIXError.Code(rawValue: errorCode)!) { _ = try connection.inspect() }
            }
            return
        }
        if mode == "--interrupted-read" {
            let identifier = UUID(uuidString: CommandLine.arguments[2])!
            let chunk = VolumeConnection.maximumTransfer
            var data = Data(repeating: 0xa5, count: chunk + 19)
            var completed = 0
            try expect(.EIO) {
                try data.withUnsafeMutableBytes {
                    try connection.read(.readImage, expecting: identifier, at: 103, into: $0, completed: &completed)
                }
            }
            precondition(completed == chunk)
            precondition(data.prefix(completed).allSatisfy { $0 == 0x35 })
            precondition(data.dropFirst(completed).allSatisfy { $0 == 0 })
            return
        }
        if mode == "--reply-deadline" || mode == "--send-deadline" {
            let sending = mode == "--send-deadline"
            let size = sending ? VolumeConnection.maximumTransfer : 8
            var data = Data(repeating: 0xa5, count: size)
            var completed = 0
            do {
                if sending {
                    try data.withUnsafeBytes { try connection.write($0, expecting: UUID(), at: 0) }
                } else {
                    try data.withUnsafeMutableBytes {
                        try connection.read(.readImage, expecting: UUID(), at: 0, into: $0, completed: &completed)
                    }
                }
                print("The stalled transfer completed unexpectedly")
                exit(1)
            } catch {
                guard (error as? POSIXError)?.code == .ETIMEDOUT else {
                    print("Expected ETIMEDOUT, got \(error)")
                    exit(1)
                }
            }
            if !sending {
                precondition(completed == 0 && data.allSatisfy { $0 == 0 })
            }
            return
        }
        let metadata = try connection.inspect()
        let identifier = metadata.identifier
        precondition(metadata.imageSize == 262144 && metadata.controlSize > 0)
        var slice = Data(repeating: 0xa5, count: 5)
        var completed = 0
        let writable = CommandLine.arguments.last == "--write"
        precondition(metadata.readOnly != writable)
        checkVolumeCallbacks(connection, metadata, taskOptions: [], readOnly: !writable)
        checkVolumeCallbacks(connection, metadata, taskOptions: ["--rdonly"], readOnly: true)
        if writable {
            let stale = UUID(uuidString: CommandLine.arguments[3])!
            precondition(stale != identifier)
            // A maximum-size request exceeds the socket buffer, and the
            // smaller one would change the image if accepted.
            for count in [VolumeConnection.maximumTransfer, 32 * 1024] {
                let payload = Data(repeating: 0x82, count: count)
                try expect(.ESTALE) {
                    try payload.withUnsafeBytes { try connection.write($0, expecting: stale, at: 0) }
                }
            }
        }
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
            let bulk = Data(repeating: 0x71, count: 128 * 1024)
            try bulk.withUnsafeBytes { try connection.write($0, expecting: identifier, at: 4096) }
            try connection.flush(expecting: identifier)
            try slice.withUnsafeMutableBytes {
                try connection.read(.readImage, expecting: identifier, at: 510, into: $0, completed: &completed)
            }
            precondition(completed == 5 && Array(slice) == [image[510]] + bytes + [image[514]])
            var bulkRead = Data(count: bulk.count)
            try bulkRead.withUnsafeMutableBytes {
                try connection.read(.readImage, expecting: identifier, at: 4096, into: $0, completed: &completed)
            }
            precondition(completed == bulk.count && bulkRead == bulk)
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
    compiler = [
        "clang++", "-std=c++11", "-O2", "-DTC_UNIX", "-DTC_BSD", "-DTC_MACOSX",
        "-DARGON2_NO_THREADS", "-D_FILE_OFFSET_BITS=64",
        "-I", source, "-I", source / "Crypto", "-I", source / "Crypto/Argon2/include",
        "-I", source / "PKCS11",
    ]
    # Substitute positioned I/O only in the production file implementation.
    # Successful reads and writes still use real system calls.
    subprocess.run([
        *compiler, "-Dpread=TestPositionedRead", "-Dpwrite=TestPositionedWrite",
        "-c", source / "Platform/Unix/File.cpp", "-o", work / "file-io-test.o",
    ], check=True)
    subprocess.run([
        *compiler, ROOT / "Tests/fskit_volume_protocol_test.cpp", FSKIT / "VolumeProtocol.cpp",
        work / "file-io-test.o", build_dir / "Volume/Volume.a",
        build_dir / "Platform/Platform.a", "-framework", "CoreFoundation",
        "-framework", "IOKit", "-o", work / "server",
    ], check=True)
    (work / "Client.swift").write_text(CLIENT)
    provider = (FSKIT / "FileSystem.swift").read_text()
    entry = "@main\nstruct LambCryptFileSystemExtension"
    assert provider.count(entry) == 1
    # FSKit owns the packer's construction. Substitute only that parameter
    # and remove the protocol conformance that requires the system packer.
    assert provider.count("packer: FSDirectoryEntryPacker,") == 1
    assert provider.count("FSVolume.Operations, ") == 1
    provider = provider.replace("packer: FSDirectoryEntryPacker,", "packer: TestDirectoryEntryPacker,")
    provider = provider.replace("FSVolume.Operations, ", "")
    # Use the production provider without its system entry point. Swift makes
    # private members available to an extension in the same source file.
    (work / "FileSystem.swift").write_text(provider.replace(entry, "struct LambCryptFileSystemExtension") +
        "\nextension VolumeImage { var testRoot: FSItem { root } }\n")
    subprocess.run([
        "xcrun", "swiftc", "-parse-as-library", FSKIT / "VolumeConnection.swift",
        work / "FileSystem.swift", work / "Client.swift", "-o", work / "client",
    ], check=True)


@contextlib.contextmanager
def serve(work, count, mode=None):
    start = time.time_ns() // 1000
    with subprocess.Popen([
        work / "server", work / FIXTURE.name, work / "io", str(count),
        *([mode] if mode else []),
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


def read_control(work):
    line = subprocess.check_output([work / "server", "--control", work / "io"], text=True, timeout=4)
    return tuple(map(int, line.split()))


def inspect_worker(work):
    packet = struct.pack("<IIQII16s", SIGNATURE, 1, 0, 40, 0, bytes(16))
    reply = exchange(work, packet)
    assert struct.unpack_from("<II", reply) == (0, 40)
    return struct.unpack_from("<QQ16sQ", reply, 8)


def check_positioned_write_failures(work):
    failure_dir = work / "write-failures"
    failure_dir.mkdir(mode=0o700)
    (failure_dir / "server").symlink_to(work / "server")
    fixture = FIXTURE.read_bytes()
    backing = failure_dir / FIXTURE.name
    for mode, code in (("write-zero", errno.EIO), ("write-full", errno.ENOSPC)):
        backing.write_bytes(fixture)
        with serve(failure_dir, 2, mode=mode):
            _, _, generation, _ = inspect_worker(failure_dir)
            data = b"1" * 1024
            packet = struct.pack("<IIQII16s", SIGNATURE, 4, 4096, len(data), 0, generation) + data
            assert exchange(failure_dir, packet) == struct.pack("<II", code, 0), mode
        assert (backing.read_bytes() != fixture) == (mode == "write-full"), mode


def check_write_request_deadline(work, generation):
    header = struct.pack("<IIQII16s", SIGNATURE, 4, 0, 4, 0, generation)
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
        connection.settimeout(5)
        connection.connect(str(work / "io"))
        start = time.monotonic()
        connection.sendall(header[:-1])
        time.sleep(6)
        connection.sendall(header[-1:] + b"x")
        # Both fragments arrived less than ten seconds apart, but the
        # original request should still expire ten seconds after it began.
        connection.settimeout(max(0.1, 13 - (time.monotonic() - start)))
        try:
            assert connection.recv(8) == b"", "the incomplete write should close without a reply"
        except TimeoutError as error:
            raise AssertionError("a partial write extended the worker's request deadline") from error


def check_reply_deadline(work, generation, serial):
    length = 262144
    request = struct.pack("<IIQII16s", SIGNATURE, 2, 0, length, 0, generation)
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
        connection.settimeout(5)
        connection.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 4096)
        connection.connect(str(work / "io"))
        connection.sendall(request)
        with connection.makefile("rb", buffering=0) as response:
            assert struct.unpack("<II", response.read(8)) == (0, length)
            time.sleep(10.5)
            assert read_control(work)[0] == serial, "an unread reply blocked the next request"
            assert 0 < len(response.readall()) < length, "the unread reply did not reach its deadline"


def check_control_client_failures(work):
    endpoint = work / "io"
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as listener:
        listener.settimeout(4)
        listener.bind(str(endpoint))
        endpoint.chmod(0o600)
        listener.listen()
        command = [work / "server", "--control", endpoint]
        with subprocess.Popen(command) as client:
            connection, _ = listener.accept()
            with connection, connection.makefile("rb") as request:
                assert len(request.read(40)) == 40
                connection.sendall(b"\x00")
                assert client.wait(timeout=4) == 3, "partial reply did not time out"

        generation = uuid.uuid4().bytes
        with subprocess.Popen(command) as client:
            connection, _ = listener.accept()
            with connection, connection.makefile("rb") as request:
                assert len(request.read(40)) == 40
                metadata = struct.pack("<QQ16sQ", 262144, 256, generation, 1)
                connection.sendall(struct.pack("<II", 0, len(metadata)) + metadata)
            connection, _ = listener.accept()
            with connection, connection.makefile("rb") as request:
                assert request.read(40) == struct.pack("<IIQII16s", SIGNATURE, 3, 0, 256, 0, generation)
                connection.sendall(struct.pack("<II", errno.ESTALE, 0))
                assert client.wait(timeout=4) == 4, "a replaced worker was not rejected"
    endpoint.unlink()


def check_native_flush(work):
    endpoint = work / "io"
    fixture = work / FIXTURE.name
    inspect = struct.pack("<IIQII16s", SIGNATURE, 1, 0, 40, 0, bytes(16))
    with serve(work, 11, mode="write") as serial:
        command = [work / "server", "--flush", endpoint]
        for target in ((serial + 1, fixture, 1), (serial, work / "different.hc", 1), (serial, fixture, 2)):
            arguments = [str(value) for value in target]
            assert subprocess.run([*command, *arguments], timeout=4).returncode == 5
        command.extend((str(serial), fixture, "1"))
        subprocess.run(command, check=True, timeout=4)
        inspection = exchange(work, inspect)
        _, control_size, generation, _ = struct.unpack_from("<QQ16sQ", inspection, 8)
        read_control = struct.pack("<IIQII16s", SIGNATURE, 3, 0, control_size, 0, generation)
        control = exchange(work, read_control)
    flush = struct.pack("<IIQII16s", SIGNATURE, 5, 0, 0, 0, generation)
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as listener:
        listener.settimeout(4)
        listener.bind(str(endpoint))
        endpoint.chmod(0o600)
        listener.listen()
        with subprocess.Popen(command) as client:
            for expected_request, response in ((inspect, inspection), (read_control, control),
                                               (flush, struct.pack("<II", errno.ESTALE, 0))):
                connection, _ = listener.accept()
                with connection, connection.makefile("rb") as request:
                    assert request.read(40) == expected_request
                    connection.sendall(response)
            assert client.wait(timeout=4) == 4, "flush accepted a replacement worker"
    endpoint.unlink()


def check_extension_deadline(client, resource, sending=False):
    resource.mkdir(mode=0o700)
    endpoint = resource / "io"
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as listener:
        listener.settimeout(4)
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 4096)
        listener.bind(str(endpoint))
        endpoint.chmod(0o600)
        listener.listen()
        option = "--send-deadline" if sending else "--reply-deadline"
        with subprocess.Popen([client, resource, option], stdout=subprocess.PIPE, text=True) as process:
            try:
                connection, _ = listener.accept()
                with connection, connection.makefile("rb") as request:
                    connection.settimeout(4)
                    size = 1024 * 1024 if sending else 8
                    assert struct.unpack("<IIQII16s", request.read(40))[:5] == (SIGNATURE, 4 if sending else 2, 0, size, 0)
                    start = time.monotonic()
                    if not sending:
                        header = struct.pack("<II", 0, size)
                        connection.sendall(header[:4])
                        time.sleep(6)
                        connection.sendall(header[4:] + b"x")
                    timeout = max(0.1, 13 - (time.monotonic() - start))
                    try:
                        output, _ = process.communicate(timeout=timeout)
                    except subprocess.TimeoutExpired as error:
                        raise AssertionError(f"{option} extended past the 10-second deadline") from error
                    elapsed = time.monotonic() - start
                    assert process.returncode == 0, output.strip()
                    assert 8.5 <= elapsed < 13, elapsed
            finally:
                if process.poll() is None:
                    process.kill()


def check_extension_reply_bounds(client, resource):
    resource.mkdir(mode=0o700)
    endpoint = resource / "io"
    generation = uuid.UUID("8e482d51-ffb5-46fb-b60f-7cb2fa693222")
    chunk = 1024 * 1024
    inspect = struct.pack("<IIQII16s", SIGNATURE, 1, 0, 40, 0, bytes(16))

    def metadata(image=512, control=1, identifier=generation.bytes, read_only=0):
        return struct.pack("<QQ16sQ", image, control, identifier, read_only)

    def reply(data):
        return struct.pack("<II", 0, len(data)) + data

    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as listener:
        listener.settimeout(4)
        listener.bind(str(endpoint))
        endpoint.chmod(0o600)
        listener.listen()

        def check(label, options, exchanges):
            with subprocess.Popen([client, resource, *options], stdout=subprocess.PIPE,
                                  stderr=subprocess.STDOUT, text=True) as process:
                try:
                    for expected_request, response in exchanges:
                        connection, _ = listener.accept()
                        with connection, connection.makefile("rb") as packet:
                            connection.settimeout(4)
                            assert packet.read(40) == expected_request, label
                            connection.sendall(response)
                    output, _ = process.communicate(timeout=5)
                    assert process.returncode == 0, (label, output.strip())
                finally:
                    if process.poll() is None:
                        process.kill()

        valid = (
            ("valid metadata", reply(metadata())),
            ("maximum metadata bounds", reply(metadata(image=2**63 - 1, control=chunk, read_only=1))),
        )
        invalid = (
            ("zero image size", reply(metadata(image=0))),
            ("image size outside signed file offsets", reply(metadata(image=2**63))),
            ("empty control record", reply(metadata(control=0))),
            ("oversized control record", reply(metadata(control=chunk + 1))),
            ("zero generation", reply(metadata(identifier=bytes(16)))),
            ("invalid protection flag", reply(metadata(read_only=2))),
            ("truncated metadata", reply(metadata())[:-1]),
            ("empty metadata", reply(b"")),
        )
        for label, response in valid:
            check(label, ["0", "--inspect-metadata"], [(inspect, response)])
        for label, response in invalid:
            check(label, [str(errno.EIO), "--inspect-metadata"], [(inspect, response)])

        first = struct.pack("<IIQII16s", SIGNATURE, 2, 103, chunk, 0, generation.bytes)
        second = struct.pack("<IIQII16s", SIGNATURE, 2, 103 + chunk, 19, 0, generation.bytes)
        check("disconnect after a completed chunk", [str(generation), "--interrupted-read"], [
            (first, reply(b"5" * chunk)),
            (second, struct.pack("<II", 0, 19) + b"partial"),
        ])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build-dir", required=True, type=Path)
    args = parser.parse_args()
    if sys.platform != "darwin":
        parser.error("This test exercises the macOS protocol")
    # Exercise the same filesystem path through Swift's file URL and the native socket.
    with tempfile.TemporaryDirectory(prefix="lambcrypt #%-é-", dir="/private/tmp") as directory:
        work = Path(directory)
        shutil.copyfile(FIXTURE, work / FIXTURE.name)
        build(args.build_dir.resolve(), work)
        subprocess.run([work / "server", "--check-buffer-erase"], check=True, timeout=10)
        command = [work / "client", work, DIGESTS[FIXTURE.name]]
        with serve(work, 2):
            subprocess.run([work / "client", work, "--enumeration"], check=True, timeout=10)
        # Interrupt the first ciphertext read after the worker opens the volume.
        with serve(work, 19, mode="read-interrupted") as first_serial:
            assert read_control(work) == (first_serial, 0)
            generation = uuid.UUID(subprocess.check_output(command, text=True, timeout=20).strip())
            serial, activity = read_control(work)
            assert serial == first_serial and activity >= 262144
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
            empty_read_only_write = struct.pack("<IIQII16s", SIGNATURE, 4, 0, 0, 0, generation.bytes)
            assert exchange(work, empty_read_only_write) == struct.pack("<II", errno.EROFS, 0)
            check_reply_deadline(work, generation.bytes, first_serial)
        with serve(work, 7) as later_serial:
            assert later_serial > first_serial
            subprocess.run([*command, str(generation)], check=True, timeout=20)
        with serve(work, 19, mode="write-interrupted"):
            # Inspect the writable worker independently before the Swift client runs.
            image_size, _, writable_id, _ = inspect_worker(work)
            for offset, expected_error in ((0, 0), (image_size, 0), (image_size + 1, errno.ENOSPC)):
                empty_write = struct.pack("<IIQII16s", SIGNATURE, 4, offset, 0, 0, writable_id)
                assert exchange(work, empty_write) == struct.pack("<II", expected_error, 0), offset
            partial_write = struct.pack("<IIQII16s", SIGNATURE, 4, 0, 4, 0, writable_id) + b"x"
            assert exchange(work, partial_write) == b""
            check_write_request_deadline(work, writable_id)
            assert (work / FIXTURE.name).read_bytes() == FIXTURE.read_bytes()
            subprocess.run([*command, str(generation), "--write"], check=True, timeout=20)
        with serve(work, 3):
            _, _, reopened_id, read_only = inspect_worker(work)
            assert read_only == 1 and reopened_id != writable_id
            for offset, data in ((511, b"\x5a\xc3\x13"), (4096, b"\x71" * (128 * 1024))):
                packet = struct.pack("<IIQII16s", SIGNATURE, 2, offset, len(data), 0, reopened_id)
                assert exchange(work, packet) == struct.pack("<II", 0, len(data)) + data
        check_positioned_write_failures(work)
        not_private = work / "not-private"
        not_private.mkdir()
        not_private.chmod(0o755)
        subprocess.run([work / "client", work, "--path-errors"], check=True, timeout=10)
        check_control_client_failures(work)
        check_native_flush(work)
        check_extension_reply_bounds(work / "client", work / "reply-bounds")
        with ThreadPoolExecutor(max_workers=2) as executor:
            reply = executor.submit(check_extension_deadline, work / "client", work / "reply-deadline")
            send = executor.submit(check_extension_deadline, work / "client", work / "send-deadline", True)
            reply.result()
            send.result()
    print("PASS: fresh native activity snapshots, control deadline, and replaced worker rejection")
    print("PASS: native flush matches serial, path, and slot and rejects a replaced worker")
    print("PASS: extension deadlines for sending and receiving, including a fragmented reply and buffer clearing")
    print("PASS: inspection metadata bounds and buffer clearing after an interrupted multi-chunk read")
    print("PASS: FSKit provider honors worker protection and read-only load options")
    print("PASS: FSKit enumeration verifier, packing, resumption, attributes, EOF, and invalid cookies")
    print("PASS: secure erase clears the full allocation across small, odd, and bulk buffer sizes")
    print("PASS: the encrypted read retries EINTR and matches the VeraCrypt plaintext checksum")
    print("PASS: encrypted writes resume after interruption and short progress, preserve I/O errors, and survive reopen")
    print("PASS: VeraCrypt payload, control metadata, EOF, malformed input, worker identity, empty, partial and bulk writes, request and reply deadlines, sync")


if __name__ == "__main__":
    main()
