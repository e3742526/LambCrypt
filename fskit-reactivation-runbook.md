# Local FSKit maintenance and activation

Use the logged-in account on Apple Silicon macOS 26 or later. Keep the
canonical bundle at `/Applications/LambCrypt-FSKit.app`. The application ID
is `io.github.e3742526.LambCrypt.fskit` and its embedded extension appends
`.module`.

## Build, sign and install

1. Use Xcode with the macOS 26 SDK or later and Python 3.11 or later. Prepare
   a native static wxWidgets 3.2.10 build with built-in dependencies. The
   existing macOS makefile builds it with this command. Use absolute source
   and build paths without spaces.

   ```sh
   make -C src WXSTATIC=FULL WX_ROOT="$WX_SRC" WX_BUILD_DIR="$WX_BUILD" \
     WX_CONFIGURE_EXTRA_FLAGS=--with-regex=builtin wxbuild
   ```

2. Keep the Apple Development private key in Keychain. Copy
   [signing.env.example](src/Setup/MacOSX/signing.env.example) to a private
   file outside the repository. Set `VC_APP_SIGN_IDENTITY` to the Keychain
   identity or fingerprint and `VC_FSKIT_PROVISIONING_PROFILE` to the exact
   Apple-issued macOS development profile for this Mac. Source the private
   file before invoking the updater.

3. Dismount LambCrypt volumes normally and close LambCrypt and VeraCrypt.
   Keep them closed through the update. Run from the repository root.

   ```sh
   python3 -B src/Setup/MacOSX/local_fskit_update.py --wx-build-dir "$WX_BUILD"
   ```

   The updater builds the committed Git ref, verifies the profile and
   signatures, reserves an increasing build number, and checks the
   application and extension's linkage. It rechecks workers, active
   reservations, mount points and Disk Images inventory immediately before
   publishing the bundle. On an update it verifies a private ZIP of the
   previous bundle before atomically swapping the application. It reports
   Launch Services, PlugInKit and effective FSClient status.

   Add `--smoke` to run a disposable FAT12 lifecycle. Add `--build-only` to
   sign and verify in the private cache. For the first run after older
   experiments, use `--build-version` above every previous FSKit candidate.
   Subsequent runs use the saved counter and installed build number.

   A registration or smoke failure after publishing preserves the installed
   bundle and its rollback ZIP. The terminal prints the private evidence
   locations. Keep the test fixture and logs if a mount or cleanup failed.

## Renew provisioning

1. In Apple Developer, select the existing extension App ID and verify the
   FSKit Module capability. Register this Mac using the exact **Provisioning
   UDID** from System Information.
2. Choose a valid Apple Development signing identity with its private key in
   Keychain. Regenerate the extension's macOS development profile with that
   certificate and the physical Mac selected. Update the private environment.
3. Run the updater. It rejects an expired profile, an unauthorized
   certificate or Mac, a wrong team or bundle ID, and mismatched App Group
   metadata. The bundle verifier warns when the profile or certificate is
   within 30 days of expiry.

[Apple provisioning profile guidance](https://developer.apple.com/help/account/provisioning-profiles/create-a-development-provisioning-profile/)

## Roll back to a working FSKit revision

Run the updater with `--ref <last-known-good-commit> --smoke` and the current
development profile. This rebuilds the earlier source with a higher bundle
version and the same identities. Use the verified ZIP in
`~/Library/Application Support/LambCrypt-FSKit/Local Updates/` as recovery
evidence or for inspection. Keep it archived while the installed app is
registered.

## Diagnose or recover activation

1. Verify the bundle with
   `bash src/Setup/MacOSX/verify_fskit_bundle.sh --local /Applications/LambCrypt-FSKit.app`.
   Query only the LambCrypt extension in PlugInKit.

   ```sh
   pluginkit -m -A -D -v -i io.github.e3742526.LambCrypt.fskit.module
   ```

2. Compile and sign the probe with the same Apple Development identity.
   Use the normal login session and keep the probe out of the checkout.

   ```sh
   probe_dir="$(mktemp -d)"
   xcrun swiftc Tests/check_fskit_activation.swift -o "$probe_dir/check_fskit_activation"
   codesign --force --sign "$VC_APP_SIGN_IDENTITY" "$probe_dir/check_fskit_activation"
   "$probe_dir/check_fskit_activation" --register /Applications/LambCrypt-FSKit.app
   ```

   Probe codes 1, 2, 3, 4 and 5 mean disabled, absent, a different extension
   path, FSClient query failure, and Launch Services failure or duplicate
   app respectively. A positive PlugInKit election and FSClient code 0
   establish registration and effective enablement.

3. If disabled, enable LambCrypt in **System Settings → General → Login Items
   & Extensions → By Category → File System Extensions**, then run the
   signed probe again. Archive verified same-identifier scratch applications
   outside discoverable `.app` paths. If an obsolete path is still registered,
   target that exact old bundle in Launch Services or PlugInKit. Avoid
   global reset commands and leave the canonical path in place.
4. Run the [disposable FAT12 smoke](Tests/README-macos-lifecycle.md#ordinary-fskit-fat-routing).
   Check the extension log promptly after mounting to confirm the actual
   executable path. On Tahoe this records the launch for each mount.

   ```sh
   log show --last 10m --style compact --predicate \
     'process == "LambCryptFSKit" AND eventMessage CONTAINS[c] "launched"'
   ```

   The path must point inside the canonical app. If launchd reports a
   re-bootstrap conflict, inspect its exact read-only job record using the
   login-session `fskit_agent` PID.

   ```sh
   launchctl print "pid/<agent-pid>/io.github.e3742526.LambCrypt.fskit.module"
   ```

5. If launchd retains an old path and macOS denies removal of that inactive
   job, arrange a normal restart with the owner's authorization. Prepare
   the canonical app and archive the old bundle before restarting. Keep
   unrelated filesystem services and mounted drives under the owner's
   control. After restart, verify effective enablement, the actual binary
   launch path, two successful mounts and final cleanup before broader use.

   On November 23, launchd preferred an already bootstrapped scratch job at
   an obsolete path while both PlugInKit and FSClient selected the installed
   app. Before archiving the scratch bundle, the old executable ran and
   ExtensionFoundation rejected its bundle record. After archiving it,
   launchd still selected the old program and reported it missing. Scoped
   removal was denied. Registering the signed app and raising its build
   number left the live job in place.

[Apple's FSKit settings API](https://developer.apple.com/documentation/fskit/fsclient/openfilesystemextensionssettings())

## Recover an interrupted mount or teardown

Close open files and try ordinary dismount through LambCrypt. If the worker
still serves an attached image, keep it running. Inspect the mount table,
`hdiutil info -plist`, and the worker's private App Group directory. A
pending marker or unavailable inventory requires investigation even when the
volume has disappeared from Finder.

If the worker was killed and an image remains, stop using the mount and keep
the encrypted backing file closed in LambCrypt. Match the image path, whole
media and any APFS child volume to the failed session before requesting an
ordinary eject. Never select a device solely by its previous BSD number. If
ownership or detachment is uncertain, preserve the inventory and obtain a
controlled restart before reopening the container. Check the recovered
filesystem read-only first. Use filesystem verification on a disposable copy
or a verified backup with the filesystem offline.
