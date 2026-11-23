/*
 Copyright (c) 2026 LambCrypt contributors
 Governed by the Apache License 2.0, the full text of which is contained in
 the file License.txt included in LambCrypt binary and source code
 distribution packages.
*/

import Darwin
import Dispatch
import Foundation

// The core service owns the open Volume and its keys. The extension exchanges
// bounded byte ranges with that service through its private resource directory.
struct VolumeConnection {
    enum Operation: UInt32 {
        case inspect = 1
        case readImage = 2
        case readControl = 3
        case writeImage = 4
        case flushImage = 5
    }

    struct Metadata {
        let imageSize: UInt64
        let controlSize: UInt64
        let identifier: UUID
        let readOnly: Bool
    }

    static let maximumTransfer = 1024 * 1024
    private static let signature: UInt32 = 0x3346434c
    private static let unboundIdentifier = UUID(uuid: (0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0))
    private static let transferTimeout = DispatchTimeInterval.seconds(10)
    private let endpointPath: ContiguousArray<CChar>
    private let socketAddress: ContiguousArray<CChar>
    private let owner: uid_t

    init(resource: URL) throws {
        guard resource.isFileURL else { throw POSIXError(.EACCES) }
        var info = stat()
        guard lstat(resource.path, &info) == 0 else { throw Self.currentError() }
        guard info.st_mode & S_IFMT == S_IFDIR, info.st_uid == getuid(),
              info.st_mode & 0o077 == 0 else {
            throw POSIXError(.EACCES)
        }
        owner = info.st_uid
        let path = resource.appendingPathComponent("io").path.utf8CString
        endpointPath = path
        // Darwin reads a length byte, an address family byte, and the path
        // without its terminator. App group paths can outgrow sockaddr_un.
        let pathBytes = path.dropLast()
        let addressLength = 2 + pathBytes.count
        guard addressLength <= SOCK_MAXADDRLEN else { throw POSIXError(.ENAMETOOLONG) }
        socketAddress = ContiguousArray([CChar(bitPattern: UInt8(addressLength)), CChar(AF_UNIX)]) + pathBytes
    }

    func inspect(expectedIdentifier: UUID? = nil) throws -> Metadata {
        var bytes = Data(count: 40)
        let count = try bytes.withUnsafeMutableBytes { try request(.inspect, expecting: expectedIdentifier, at: 0, into: $0) }
        guard count == bytes.count else { throw POSIXError(.EIO) }
        let size = bytes.withUnsafeBytes { UInt64(littleEndian: $0.loadUnaligned(as: UInt64.self)) }
        let control = bytes.withUnsafeBytes {
            UInt64(littleEndian: $0.loadUnaligned(fromByteOffset: 8, as: UInt64.self))
        }
        let id = bytes.withUnsafeBytes { UUID(uuid: $0.loadUnaligned(fromByteOffset: 16, as: uuid_t.self)) }
        let readOnly = bytes.withUnsafeBytes { UInt64(littleEndian: $0.loadUnaligned(fromByteOffset: 32, as: UInt64.self)) }
        // FSKit addresses the image with signed file offsets. Only initial
        // inspection requests may omit a generation.
        guard size > 0, size <= UInt64(off_t.max),
              control > 0, control <= Self.maximumTransfer,
              id != Self.unboundIdentifier, readOnly <= 1 else {
            throw POSIXError(.EIO)
        }
        if let expectedIdentifier, id != expectedIdentifier { throw POSIXError(.ESTALE) }
        return Metadata(imageSize: size, controlSize: control, identifier: id, readOnly: readOnly == 1)
    }

    func read(_ operation: Operation, expecting identifier: UUID, at offset: UInt64,
              into buffer: UnsafeMutableRawBufferPointer, completed: inout Int) throws {
        completed = 0
        defer {
            // FSKit can consume the requested range even after a short or failed read.
            if completed < buffer.count {
                let unread = UnsafeMutableRawBufferPointer(rebasing: buffer[completed...])
                unread.initializeMemory(as: UInt8.self, repeating: 0)
            }
        }
        while completed < buffer.count {
            let count = min(buffer.count - completed, Self.maximumTransfer)
            let slice = UnsafeMutableRawBufferPointer(rebasing: buffer[completed..<(completed + count)])
            let (position, overflow) = offset.addingReportingOverflow(UInt64(completed))
            guard !overflow else { throw POSIXError(.EOVERFLOW) }
            let received = try request(operation, expecting: identifier, at: position, into: slice)
            completed += received
            if received < count { break }
        }
    }

    func write(_ buffer: UnsafeRawBufferPointer, expecting identifier: UUID, at offset: UInt64) throws {
        _ = try request(.writeImage, expecting: identifier, at: offset,
                        into: UnsafeMutableRawBufferPointer(start: nil, count: 0), sending: buffer)
    }

    func flush(expecting identifier: UUID) throws {
        _ = try request(.flushImage, expecting: identifier, at: 0,
                        into: UnsafeMutableRawBufferPointer(start: nil, count: 0))
    }

    private func request(_ operation: Operation, expecting identifier: UUID?, at offset: UInt64,
                         into buffer: UnsafeMutableRawBufferPointer,
                         sending contents: UnsafeRawBufferPointer = UnsafeRawBufferPointer(start: nil, count: 0)) throws -> Int {
        let length = max(buffer.count, contents.count)
        guard length <= Self.maximumTransfer else { throw POSIXError(.EINVAL) }
        let sendDeadline = DispatchTime.now() + Self.transferTimeout
        let fd = try connectToService(deadline: sendDeadline)
        defer { Darwin.close(fd) }
        // The default Unix stream buffer is small compared with a bulk image write.
        if contents.count > 8 * 1024 {
            var sendBufferSize: Int32 = 256 * 1024
            _ = setsockopt(fd, SOL_SOCKET, SO_SNDBUF, &sendBufferSize, socklen_t(MemoryLayout<Int32>.size))
        }

        // The fixed-width fields are little-endian, followed by the generation UUID.
        try withUnsafeTemporaryAllocation(byteCount: 40, alignment: MemoryLayout<UInt64>.alignment) { bytes in
            bytes.storeBytes(of: Self.signature.littleEndian, toByteOffset: 0, as: UInt32.self)
            bytes.storeBytes(of: operation.rawValue.littleEndian, toByteOffset: 4, as: UInt32.self)
            bytes.storeBytes(of: offset.littleEndian, toByteOffset: 8, as: UInt64.self)
            bytes.storeBytes(of: UInt32(length).littleEndian, toByteOffset: 16, as: UInt32.self)
            bytes.storeBytes(of: UInt32(0), toByteOffset: 20, as: UInt32.self) // Reserved.
            bytes.storeBytes(of: (identifier ?? Self.unboundIdentifier).uuid, toByteOffset: 24, as: uuid_t.self)
            try transfer(bytes.count, on: fd, events: Int16(POLLOUT), deadline: sendDeadline) { start, remaining in
                Darwin.send(fd, bytes.baseAddress?.advanced(by: start), remaining, 0)
            }
        }
        try transfer(contents.count, on: fd, events: Int16(POLLOUT), deadline: sendDeadline) { start, remaining in
            Darwin.send(fd, contents.baseAddress?.advanced(by: start), remaining, 0)
        }

        // The response starts with a POSIX error number and a payload length.
        // Keep the same deadline for the header and payload, including partial replies.
        let replyDeadline = DispatchTime.now() + Self.transferTimeout
        var header: UInt64 = 0
        try withUnsafeMutableBytes(of: &header) { bytes in
            try transfer(bytes.count, on: fd, events: Int16(POLLIN), deadline: replyDeadline) { start, remaining in
                Darwin.recv(fd, bytes.baseAddress?.advanced(by: start), remaining, 0)
            }
        }
        let reply = UInt64(littleEndian: header)
        let code = UInt32(truncatingIfNeeded: reply)
        let count = Int(reply >> 32)
        if code != 0 {
            throw POSIXError(Int32(exactly: code).flatMap(POSIXError.Code.init(rawValue:)) ?? .EIO)
        }
        guard count <= buffer.count else { throw POSIXError(.EIO) }
        try transfer(count, on: fd, events: Int16(POLLIN), deadline: replyDeadline) { start, remaining in
            Darwin.recv(fd, buffer.baseAddress?.advanced(by: start), remaining, 0)
        }
        return count
    }

    private func connectToService(deadline: DispatchTime) throws -> Int32 {
        var info = stat()
        // Recheck the endpoint on each connection. utf8CString always includes a terminator.
        let endpointStatus = endpointPath.withUnsafeBufferPointer { lstat($0.baseAddress!, &info) }
        guard endpointStatus == 0 else { throw Self.currentError() }
        guard info.st_mode & S_IFMT == S_IFSOCK,
              info.st_uid == owner, info.st_mode & 0o077 == 0 else {
            throw POSIXError(.EACCES)
        }
        let fd = socket(AF_UNIX, SOCK_STREAM, 0)
        guard fd >= 0 else { throw Self.currentError() }
        do {
            var noSignal: Int32 = 1
            guard fcntl(fd, F_SETFL, O_NONBLOCK) == 0,
                  fcntl(fd, F_SETFD, FD_CLOEXEC) == 0,
                  setsockopt(fd, SOL_SOCKET, SO_NOSIGPIPE, &noSignal, socklen_t(MemoryLayout<Int32>.size)) == 0 else {
                throw Self.currentError()
            }
            let result = socketAddress.withUnsafeBytes { address in
                Darwin.connect(fd, address.baseAddress!.assumingMemoryBound(to: sockaddr.self), socklen_t(address.count))
            }
            if result != 0 {
                guard errno == EINPROGRESS || errno == EINTR else { throw Self.currentError() }
                try waitForSocket(fd, events: Int16(POLLOUT), deadline: deadline)
                var socketError: Int32 = 0
                var size = socklen_t(MemoryLayout<Int32>.size)
                guard getsockopt(fd, SOL_SOCKET, SO_ERROR, &socketError, &size) == 0 else { throw Self.currentError() }
                if socketError != 0 {
                    throw POSIXError(POSIXError.Code(rawValue: socketError) ?? .EIO)
                }
            }
            var peer: uid_t = 0
            var group: gid_t = 0
            guard getpeereid(fd, &peer, &group) == 0, peer == owner else {
                throw POSIXError(.EACCES)
            }
            return fd
        } catch {
            Darwin.close(fd)
            throw error
        }
    }

    private func waitForSocket(_ fd: Int32, events: Int16, deadline: DispatchTime) throws {
        var descriptor = pollfd(fd: fd, events: events, revents: 0)
        while true {
            let now = DispatchTime.now()
            guard now < deadline else { throw POSIXError(.ETIMEDOUT) }
            let remaining = deadline.uptimeNanoseconds - now.uptimeNanoseconds
            let milliseconds = Int32((remaining + 999_999) / 1_000_000)
            let ready = Darwin.poll(&descriptor, 1, milliseconds)
            if ready > 0 { return }
            if ready == 0 { throw POSIXError(.ETIMEDOUT) }
            if errno != EINTR { throw Self.currentError() }
        }
    }

    private func transfer(_ count: Int, on fd: Int32, events: Int16, deadline: DispatchTime,
                          _ operation: (Int, Int) -> Int) throws {
        var completed = 0
        while completed < count {
            guard DispatchTime.now() < deadline else { throw POSIXError(.ETIMEDOUT) }
            let result = operation(completed, count - completed)
            if result < 0 && errno == EINTR { continue }
            if result < 0 && (errno == EAGAIN || errno == EWOULDBLOCK) {
                try waitForSocket(fd, events: events, deadline: deadline)
                continue
            }
            guard result >= 0 else { throw Self.currentError() }
            guard result > 0 else { throw POSIXError(.EIO) }
            completed += result
        }
    }

    private static func currentError() -> POSIXError {
        POSIXError(POSIXError.Code(rawValue: errno) ?? .EIO)
    }
}
