/*
 Copyright (c) 2026 LambCrypt contributors
 Governed by the Apache License 2.0, the full text of which is contained in
 the file License.txt included in LambCrypt binary and source code
 distribution packages.
*/

import AppKit
import CoreServices
import FSKit
import Foundation

let appIdentifier = "io.github.e3742526.LambCrypt.fskit"
let identifier = appIdentifier + ".module"
var arguments = Array(CommandLine.arguments.dropFirst())
let register = arguments.first == "--register"
if register { arguments.removeFirst() }
guard arguments.count == 1 else {
    print("Usage: check_fskit_activation [--register] /path/to/LambCrypt-FSKit.app")
    exit(64)
}
let appURL = URL(fileURLWithPath: arguments[0], isDirectory: true).resolvingSymlinksInPath()
let extensionURL = appURL
    .appendingPathComponent("Contents/Extensions/LambCryptFSKit.appex", isDirectory: true)
    .resolvingSymlinksInPath()
guard Bundle(url: extensionURL)?.bundleIdentifier == identifier else {
    print("Expected \(identifier) at \(extensionURL.path)")
    exit(64)
}
if register {
    guard Bundle(url: appURL)?.bundleIdentifier == appIdentifier else {
        print("Unexpected application identifier at \(appURL.path)")
        exit(64)
    }
    let status = LSRegisterURL(appURL as CFURL, true)
    guard status == noErr else {
        print("Launch Services registration failed with status \(status)")
        exit(5)
    }
    let copies = NSWorkspace.shared.urlsForApplications(withBundleIdentifier: appIdentifier)
        .map { $0.resolvingSymlinksInPath() }
        .filter { Bundle(url: $0)?.bundleIdentifier == appIdentifier }
    guard Set(copies) == [appURL] else {
        for copy in copies { print("Launch Services app: \(copy.path)") }
        print("Launch Services did not resolve the canonical app exclusively.")
        exit(5)
    }
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
