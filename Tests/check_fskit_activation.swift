/*
 Copyright (c) 2026 LambCrypt contributors
 Governed by the Apache License 2.0, the full text of which is contained in
 the file License.txt included in LambCrypt binary and source code
 distribution packages.
*/

import FSKit
import Foundation

let identifier = "io.github.e3742526.LambCrypt.fskit.module"
guard CommandLine.arguments.count == 2 else {
    print("Usage: check_fskit_activation /path/to/LambCrypt-FSKit.app")
    exit(64)
}
let extensionURL = URL(fileURLWithPath: CommandLine.arguments[1], isDirectory: true)
    .appendingPathComponent("Contents/Extensions/LambCryptFSKit.appex", isDirectory: true)
    .resolvingSymlinksInPath()
guard Bundle(url: extensionURL)?.bundleIdentifier == identifier else {
    print("Expected \(identifier) at \(extensionURL.path)")
    exit(64)
}

DispatchQueue.global().asyncAfter(deadline: .now() + .seconds(5)) {
    print("FSKit module query timed out")
    exit(4)
}
FSClient.shared.fetchInstalledExtensions { modules, error in
    guard let modules, error == nil else {
        if let error = error as NSError? {
            print("FSKit module query failed with \(error.domain) code \(error.code)")
        } else {
            print("FSKit module query returned no inventory")
        }
        exit(4)
    }
    let matches = modules.filter { $0.bundleIdentifier == identifier }
    guard !matches.isEmpty else {
        print("FSKit did not list \(identifier)")
        exit(2)
    }
    for module in matches {
        print("\(module.bundleIdentifier) enabled=\(module.isEnabled) \(module.url.path)")
    }
    guard matches.allSatisfy({ $0.url.resolvingSymlinksInPath().path == extensionURL.path }) else {
        exit(3)
    }
    exit(matches.allSatisfy(\.isEnabled) ? 0 : 1)
}
dispatchMain()
