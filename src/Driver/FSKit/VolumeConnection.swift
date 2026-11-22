import Darwin
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
    private let endpoint: URL
    private let owner: uid_t

    init(resource: URL) throws {
        var info = stat()
        guard resource.isFileURL, lstat(resource.path, &info) == 0,
              info.st_mode & S_IFMT == S_IFDIR, info.st_uid == getuid(),
              info.st_mode & 0o077 == 0 else {
            throw POSIXError(.EACCES)
        }
        owner = info.st_uid
        endpoint = resource.appendingPathComponent("io")
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
        guard size > 0, control <= Self.maximumTransfer, readOnly <= 1 else { throw POSIXError(.EIO) }
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
        let fd = try connectToService()
        defer { Darwin.close(fd) }

        // The fixed-width fields are little-endian, followed by the generation UUID.
        var request = Data()
        append(Self.signature, to: &request)
        append(operation.rawValue, to: &request)
        append(offset, to: &request)
        append(UInt32(length), to: &request)
        append(UInt32(0), to: &request)
        if var bytes = identifier?.uuid {
            withUnsafeBytes(of: &bytes) { request.append(contentsOf: $0) }
        } else {
            request.append(Data(count: 16))
        }
        try request.withUnsafeBytes { bytes in
            try transfer(bytes.count) { start, remaining in
                Darwin.send(fd, bytes.baseAddress?.advanced(by: start), remaining, 0)
            }
        }
        try transfer(contents.count) { start, remaining in
            Darwin.send(fd, contents.baseAddress?.advanced(by: start), remaining, 0)
        }

        // The response starts with a POSIX error number and a payload length.
        var header = [UInt32](repeating: 0, count: 2)
        try header.withUnsafeMutableBytes { bytes in
            try transfer(bytes.count) { start, remaining in
                Darwin.recv(fd, bytes.baseAddress?.advanced(by: start), remaining, 0)
            }
        }
        let code = UInt32(littleEndian: header[0])
        let count = Int(UInt32(littleEndian: header[1]))
        if code != 0 {
            throw POSIXError(Int32(exactly: code).flatMap(POSIXError.Code.init(rawValue:)) ?? .EIO)
        }
        guard count <= buffer.count else { throw POSIXError(.EIO) }
        try transfer(count) { start, remaining in
            Darwin.recv(fd, buffer.baseAddress?.advanced(by: start), remaining, 0)
        }
        return count
    }

    private func connectToService() throws -> Int32 {
        var info = stat()
        guard lstat(endpoint.path, &info) == 0, info.st_mode & S_IFMT == S_IFSOCK,
              info.st_uid == owner, info.st_mode & 0o077 == 0 else {
            throw POSIXError(.EACCES)
        }
        let path = endpoint.path.utf8CString
        var address = sockaddr_un()
        let addressLength = socklen_t(MemoryLayout<sockaddr_un>.size)
        address.sun_family = sa_family_t(AF_UNIX)
        address.sun_len = UInt8(addressLength)
        guard path.count <= MemoryLayout.size(ofValue: address.sun_path) else {
            throw POSIXError(.ENAMETOOLONG)
        }
        withUnsafeMutableBytes(of: &address.sun_path) { destination in
            path.withUnsafeBytes { destination.copyBytes(from: $0) }
        }
        let fd = socket(AF_UNIX, SOCK_STREAM, 0)
        guard fd >= 0 else { throw currentError() }
        do {
            var timeout = timeval(tv_sec: 10, tv_usec: 0)
            var noSignal: Int32 = 1
            guard setsockopt(fd, SOL_SOCKET, SO_RCVTIMEO, &timeout, socklen_t(MemoryLayout<timeval>.size)) == 0,
                  setsockopt(fd, SOL_SOCKET, SO_SNDTIMEO, &timeout, socklen_t(MemoryLayout<timeval>.size)) == 0,
                  setsockopt(fd, SOL_SOCKET, SO_NOSIGPIPE, &noSignal, socklen_t(MemoryLayout<Int32>.size)) == 0 else {
                throw currentError()
            }
            let result = withUnsafePointer(to: &address) {
                $0.withMemoryRebound(to: sockaddr.self, capacity: 1) { Darwin.connect(fd, $0, addressLength) }
            }
            guard result == 0 else { throw currentError() }
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

    private func transfer(_ count: Int, _ operation: (Int, Int) -> Int) throws {
        var completed = 0
        while completed < count {
            let result = operation(completed, count - completed)
            if result < 0 && errno == EINTR { continue }
            guard result >= 0 else { throw currentError() }
            guard result > 0 else { throw POSIXError(.EIO) }
            completed += result
        }
    }

    private func append<T: FixedWidthInteger>(_ value: T, to data: inout Data) {
        var bytes = value.littleEndian
        withUnsafeBytes(of: &bytes) { data.append(contentsOf: $0) }
    }

    private func currentError() -> POSIXError {
        POSIXError(POSIXError.Code(rawValue: errno) ?? .EIO)
    }
}
