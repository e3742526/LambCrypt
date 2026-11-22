import Darwin
import Foundation
import FSKit

@main
struct LambCryptFileSystemExtension: UnaryFileSystemExtension {
    var fileSystem: LambCryptFileSystem { LambCryptFileSystem() }
}

final class LambCryptFileSystem: FSUnaryFileSystem, FSUnaryFileSystemOperations {
    private let resourceLock = NSLock()
    private var loadedURL: URL?

    func probeResource(resource: FSResource, replyHandler: @escaping (FSProbeResult?, Error?) -> Void) {
        do {
            let url = try access(resource)
            defer { url.stopAccessingSecurityScopedResource() }
            let metadata = try VolumeConnection(resource: url).inspect()
            let identifier = FSContainerIdentifier(uuid: metadata.identifier)
            replyHandler(.usable(name: "LambCrypt volume image", containerID: identifier), nil)
        } catch {
            replyHandler(nil, error)
        }
    }

    func loadResource(resource: FSResource, options: FSTaskOptions, replyHandler: @escaping (FSVolume?, Error?) -> Void) {
        do {
            let volume = try resourceLock.withLock {
                guard loadedURL == nil else { throw POSIXError(.EBUSY) }
                let taskOptions = options.taskOptions
                guard !taskOptions.contains("-f") else { throw POSIXError(.ENOTSUP) }
                let url = try access(resource)
                do {
                    let connection = try VolumeConnection(resource: url)
                    let metadata = try connection.inspect()
                    let volume = VolumeImage(connection: connection, metadata: metadata, taskOptions: taskOptions)
                    loadedURL = url
                    containerStatus = .ready
                    return volume
                } catch {
                    url.stopAccessingSecurityScopedResource()
                    throw error
                }
            }
            replyHandler(volume, nil)
        } catch {
            replyHandler(nil, error)
        }
    }

    func unloadResource(resource: FSResource, options: FSTaskOptions, replyHandler: @escaping (Error?) -> Void) {
        do {
            try resourceLock.withLock {
                guard let resource = resource as? FSPathURLResource,
                      let url = loadedURL, url == resource.url else { throw POSIXError(.EINVAL) }
                loadedURL = nil
                url.stopAccessingSecurityScopedResource()
            }
            replyHandler(nil)
        } catch {
            replyHandler(error)
        }
    }

    private func access(_ resource: FSResource) throws -> URL {
        guard let resource = resource as? FSPathURLResource else { throw POSIXError(.EINVAL) }
        let url = resource.url
        guard url.startAccessingSecurityScopedResource() else { throw POSIXError(.EACCES) }
        return url
    }
}

// This is the auxiliary filesystem that exposes an encrypted volume's data
// area. Disk Images mounts the filesystem inside volume.dmg using its own
// driver, so the extension does not need to parse FAT, APFS, or exFAT.
final class VolumeImage: FSVolume, FSVolume.Operations, FSVolume.OpenCloseOperations,
                         FSVolume.ReadWriteOperations, FSVolume.XattrOperations {
    private final class Item: FSItem {
        let name: FSFileName
        let id: FSItem.Identifier
        let operation: VolumeConnection.Operation?

        init(_ name: String, id: FSItem.Identifier, operation: VolumeConnection.Operation? = nil) {
            self.name = FSFileName(string: name)
            self.id = id
            self.operation = operation
        }
    }

    private let connection: VolumeConnection
    private let imageSize: UInt64
    private let identifier: UUID
    private let readOnly: Bool
    private static let directoryVerifier = FSDirectoryVerifier(1)
    private let root = Item(".", id: .rootDirectory)
    private let dotNames = [FSFileName(string: "."), FSFileName(string: "..")]
    private let files = [
        Item("volume.dmg", id: FSItem.Identifier(rawValue: 3)!, operation: .readImage),
        Item("control", id: FSItem.Identifier(rawValue: 4)!, operation: .readControl),
    ]

    let maximumLinkCount = 1
    let maximumNameLength = Int(NAME_MAX)
    let restrictsOwnershipChanges = true
    let truncatesLongNames = false

    init(connection: VolumeConnection, metadata: VolumeConnection.Metadata, taskOptions: [String]) {
        self.connection = connection
        imageSize = metadata.imageSize
        identifier = metadata.identifier
        readOnly = metadata.readOnly || taskOptions.contains("--rdonly")
        super.init(volumeID: FSVolume.Identifier(uuid: metadata.identifier),
                   volumeName: FSFileName(string: "LambCrypt volume image"))
    }

    var volumeStatistics: FSStatFSResult {
        let statistics = FSStatFSResult(fileSystemTypeName: "lambcryptfs")
        statistics.blockSize = 512
        statistics.ioSize = VolumeConnection.maximumTransfer
        statistics.totalBlocks = imageSize / 512
        statistics.usedBlocks = statistics.totalBlocks
        statistics.totalFiles = 3
        return statistics
    }

    var supportedVolumeCapabilities: FSVolume.SupportedCapabilities {
        let capabilities = FSVolume.SupportedCapabilities()
        capabilities.caseFormat = .sensitive
        capabilities.supports2TBFiles = true
        capabilities.supports64BitObjectIDs = true
        return capabilities
    }

    func activate(options: FSTaskOptions, replyHandler: @escaping (FSItem?, Error?) -> Void) {
        replyHandler(root, nil)
    }

    func deactivate(options: FSDeactivateOptions, replyHandler: @escaping (Error?) -> Void) {
        replyHandler(nil)
    }

    func mount(options: FSTaskOptions, replyHandler: @escaping (Error?) -> Void) {
        replyHandler(nil)
    }

    func unmount(replyHandler: @escaping () -> Void) {
        replyHandler()
    }

    func synchronize(flags: FSSyncFlags, replyHandler: @escaping (Error?) -> Void) {
        do {
            if !readOnly { try connection.flush(expecting: identifier) }
            replyHandler(nil)
        } catch {
            replyHandler(error)
        }
    }

    func getAttributes(_ desired: FSItem.GetAttributesRequest, of item: FSItem,
                       replyHandler: @escaping (FSItem.Attributes?, Error?) -> Void) {
        do { replyHandler(try attributes(of: checked(item)), nil) }
        catch { replyHandler(nil, error) }
    }

    func setAttributes(_ attributes: FSItem.SetAttributesRequest, on item: FSItem,
                       replyHandler: @escaping (FSItem.Attributes?, Error?) -> Void) {
        replyHandler(nil, POSIXError(.EROFS))
    }

    func lookupItem(named name: FSFileName, inDirectory directory: FSItem,
                    replyHandler: @escaping (FSItem?, FSFileName?, Error?) -> Void) {
        guard directory === root else { return replyHandler(nil, nil, POSIXError(.ENOTDIR)) }
        guard let name = name.string else { return replyHandler(nil, nil, POSIXError(.EINVAL)) }
        guard name.utf8.count <= maximumNameLength else { return replyHandler(nil, nil, POSIXError(.ENAMETOOLONG)) }
        if name == "." || name == ".." { return replyHandler(root, FSFileName(string: name), nil) }
        guard let item = files.first(where: { $0.name.string == name }) else {
            return replyHandler(nil, nil, POSIXError(.ENOENT))
        }
        replyHandler(item, item.name, nil)
    }

    func reclaimItem(_ item: FSItem, replyHandler: @escaping (Error?) -> Void) {
        do { _ = try checked(item); replyHandler(nil) }
        catch { replyHandler(error) }
    }

    func enumerateDirectory(_ directory: FSItem, startingAt cookie: FSDirectoryCookie,
                            verifier: FSDirectoryVerifier, attributes requested: FSItem.GetAttributesRequest?,
                            packer: FSDirectoryEntryPacker,
                            replyHandler: @escaping (FSDirectoryVerifier, Error?) -> Void) {
        guard directory === root else { return replyHandler(verifier, POSIXError(.ENOTDIR)) }
        let firstFile = dotNames.count
        let end = firstFile + files.count
        guard let start = Int(exactly: cookie.rawValue), start <= end,
              cookie == .initial || verifier == Self.directoryVerifier else {
            return replyHandler(verifier, fs_errorForPOSIXError(Int32(FSError.Code.invalidDirectoryCookie.rawValue)))
        }
        do {
            // Use the same positions even when FSKit requests attributes and
            // skips the two directory entries.
            let first = requested == nil ? start : max(start, firstFile)
            for index in first..<end {
                let isDot = index < firstFile
                let item = isDot ? root : files[index - firstFile]
                let name = isDot ? dotNames[index] : item.name
                let attributes = try requested == nil ? nil : attributes(of: item)
                if !packer.packEntry(name: name, itemType: isDot ? .directory : .file, itemID: item.id,
                                     nextCookie: FSDirectoryCookie(UInt64(index + 1)), attributes: attributes) {
                    break
                }
            }
            replyHandler(Self.directoryVerifier, nil)
        } catch {
            replyHandler(verifier, error)
        }
    }

    func openItem(_ item: FSItem, modes: FSVolume.OpenModes, replyHandler: @escaping (Error?) -> Void) {
        do {
            let item = try checked(item)
            let writable = item.operation == .readImage && !readOnly
            replyHandler(modes.contains(.write) && !writable ? POSIXError(.EROFS) : nil)
        } catch {
            replyHandler(error)
        }
    }

    func closeItem(_ item: FSItem, modes: FSVolume.OpenModes, replyHandler: @escaping (Error?) -> Void) {
        do {
            let item = try checked(item)
            // FSKit has no per-file fsync callback. Flush when the kernel
            // releases write access to the decrypted disk image.
            if item.operation == .readImage && !readOnly && !modes.contains(.write) {
                try connection.flush(expecting: identifier)
            }
            replyHandler(nil)
        } catch {
            replyHandler(error)
        }
    }

    func read(from item: FSItem, at offset: off_t, length: Int, into buffer: FSMutableFileDataBuffer,
              replyHandler: @escaping (Int, Error?) -> Void) {
        var completed = 0
        do {
            let item = try checked(item)
            guard let operation = item.operation else { throw POSIXError(.EISDIR) }
            guard offset >= 0, length >= 0 else { throw POSIXError(.EINVAL) }
            try buffer.withUnsafeMutableBytes { destination in
                guard length <= destination.count else { throw POSIXError(.EINVAL) }
                let requested = UnsafeMutableRawBufferPointer(rebasing: destination[..<length])
                try connection.read(operation, expecting: identifier, at: UInt64(offset),
                                    into: requested, completed: &completed)
            }
            replyHandler(completed, nil)
        } catch {
            replyHandler(completed, error)
        }
    }

    func write(contents: Data, to item: FSItem, at offset: off_t, replyHandler: @escaping (Int, Error?) -> Void) {
        var completed = 0
        do {
            let item = try checked(item)
            guard item.operation == .readImage, !readOnly else { throw POSIXError(.EROFS) }
            guard offset >= 0 else { throw POSIXError(.EINVAL) }
            let start = UInt64(offset)
            guard start <= imageSize, UInt64(contents.count) <= imageSize - start else { throw POSIXError(.ENOSPC) }
            try contents.withUnsafeBytes { source in
                while completed < source.count {
                    let count = min(source.count - completed, VolumeConnection.maximumTransfer)
                    let slice = UnsafeRawBufferPointer(rebasing: source[completed..<(completed + count)])
                    try connection.write(slice, expecting: identifier, at: start + UInt64(completed))
                    completed += count
                }
            }
            replyHandler(completed, nil)
        } catch {
            replyHandler(completed, error)
        }
    }

    func readSymbolicLink(_ item: FSItem, replyHandler: @escaping (FSFileName?, Error?) -> Void) {
        replyHandler(nil, POSIXError(.EINVAL))
    }

    func createItem(named name: FSFileName, type: FSItem.ItemType, inDirectory directory: FSItem,
                    attributes: FSItem.SetAttributesRequest,
                    replyHandler: @escaping (FSItem?, FSFileName?, Error?) -> Void) {
        replyHandler(nil, nil, POSIXError(.EROFS))
    }

    func createSymbolicLink(named name: FSFileName, inDirectory directory: FSItem,
                            attributes: FSItem.SetAttributesRequest, linkContents: FSFileName,
                            replyHandler: @escaping (FSItem?, FSFileName?, Error?) -> Void) {
        replyHandler(nil, nil, POSIXError(.EROFS))
    }

    func createLink(to item: FSItem, named name: FSFileName, inDirectory directory: FSItem,
                    replyHandler: @escaping (FSFileName?, Error?) -> Void) {
        replyHandler(nil, POSIXError(.EROFS))
    }

    func removeItem(_ item: FSItem, named name: FSFileName, fromDirectory directory: FSItem,
                    replyHandler: @escaping (Error?) -> Void) {
        replyHandler(POSIXError(.EROFS))
    }

    func renameItem(_ item: FSItem, inDirectory source: FSItem, named sourceName: FSFileName,
                    to destinationName: FSFileName, inDirectory destination: FSItem, overItem: FSItem?,
                    replyHandler: @escaping (FSFileName?, Error?) -> Void) {
        replyHandler(nil, POSIXError(.EROFS))
    }

    func getXattr(named name: FSFileName, of item: FSItem, replyHandler: @escaping (Data?, Error?) -> Void) {
        do { _ = try checked(item); replyHandler(nil, POSIXError(.ENOATTR)) }
        catch { replyHandler(nil, error) }
    }

    func setXattr(named name: FSFileName, to value: Data?, on item: FSItem, policy: FSVolume.SetXattrPolicy,
                  replyHandler: @escaping (Error?) -> Void) {
        replyHandler(POSIXError(.EROFS))
    }

    func listXattrs(of item: FSItem, replyHandler: @escaping ([FSFileName]?, Error?) -> Void) {
        do { _ = try checked(item); replyHandler([], nil) }
        catch { replyHandler(nil, error) }
    }

    private func checked(_ item: FSItem) throws -> Item {
        if item === root { return root }
        guard let match = files.first(where: { $0 === item }) else { throw POSIXError(.ESTALE) }
        return match
    }

    private func attributes(of item: Item) throws -> FSItem.Attributes {
        let attributes = FSItem.Attributes()
        attributes.fileID = item.id
        attributes.parentID = .rootDirectory
        attributes.uid = getuid()
        attributes.gid = getgid()
        attributes.type = item.operation == nil ? .directory : .file
        attributes.mode = item.operation == nil ? 0o500 : 0o400
        attributes.linkCount = item.operation == nil ? 2 : 1
        switch item.operation {
        case .readImage:
            attributes.size = imageSize
            if !readOnly { attributes.mode = 0o600 }
        case .readControl: attributes.size = try connection.inspect(expectedIdentifier: identifier).controlSize
        default: attributes.size = 0
        }
        attributes.allocSize = attributes.size
        return attributes
    }
}
