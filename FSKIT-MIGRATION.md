# LambCrypt FSKit migration

LambCrypt is a VeraCrypt derivative for Apple Silicon Macs running macOS 26
(Tahoe) or later. The FSKit experiment uses the existing VeraCrypt volume
format and LambCrypt crypto code. MacFUSE remains the default, FUSE-T remains
available, and the application ships in English.

## Integrator checklist

- [ ] Copy [signing.env.example](src/Setup/MacOSX/signing.env.example) to a private
  `signing.local.env` outside the checkout. Keep the real Apple Team ID, signing
  identity names or fingerprints, and profile paths there or in CI secrets.
  The build uses Make, so source the environment file before building.
- [ ] Sign in to Xcode with an enrolled Apple Developer Program team. For
  development, make the Apple Development certificate and private key available
  in the local Keychain and register the test Mac with that team.
- [ ] Register an explicit App ID for
  `io.github.e3742526.LambCrypt.fskit.module` and enable the FSKit Module
  capability. Obtain the matching macOS development provisioning profile for the
  registered device and certificate. Store the profile outside the checkout
  and set `VC_FSKIT_PROVISIONING_PROFILE` to its absolute path.
- [ ] Set `VC_APP_SIGN_IDENTITY` to the corresponding Keychain identity. In a
  separate build tree with the build dependencies configured, source the local
  environment file and run `LOCAL_DEVELOPMENT_BUILD=true make -C src WITHFSKIT=1 prepare`.
  The recipe reads the Team ID from the profile, builds matching App Group
  entitlements, and signs the extension before signing the app.
- [ ] Run `codesign --verify --deep --strict src/Main/LambCrypt-FSKit.app`.
  Verify the app and extension are signed by the same team and have matching
  App Group entitlements. The extension should have the provisioned application
  identifier and FSKit Module entitlement. Enable the test extension in System
  Settings and verify it on disposable internal-drive containers.
- [ ] At the release gate, set `VC_SIGN_TEAM_ID`, select the team's Developer ID
  Application and Developer ID Installer identities, and use a matching
  distribution profile that grants the extension's FSKit capability. Set
  `VC_NOTARY_PROFILE` to a Keychain credential profile created with
  `xcrun notarytool store-credentials`. Verify Hardened Runtime and secure
  timestamps on the release build. The current notarization script targets the
  MacFUSE and FUSE-T bundles. FSKit packaging and notarization belong to
  stage 6. [Apple capability matrix](https://developer.apple.com/help/account/reference/supported-capabilities-macos/),
  [Apple notarization requirements](https://developer.apple.com/documentation/security/notarizing-macos-software-before-distribution).
- [ ] Before committing, review the staged diff for team-specific values and
  files. Keep certificates, private keys, profiles, generated entitlements,
  signing logs, and signed bundles out of source control. The signed scratch
  extension contains an embedded copy of its provisioning profile.

## Stage gates

Work in a separate scratch tree on disposable internal-drive containers. Leave
installed apps alone and collect evidence before advancing each gate.

| Stage | Required evidence | Status |
| --- | --- | --- |
| 0. Baseline | Default MacFUSE build, discovery tests, and applicable FUSE-T checks pass. | Passed |
| 1. Build variant | MacFUSE remains default. The opt-in FSKit bundle builds separately. | Passed |
| 2. Read-only | Read a VeraCrypt payload and a fresh compatible container, then verify external dismount, background exit, and worker cleanup. | Passed on disposable containers |
| 3. Read-write | Verify write and sync, file operations, xattrs, advisory locks, busy dismount, dismount after release, read-only remount, and Finder eject. | HFS+ passed clean and busy-release dismount, read-only remount, and external Disk Arbitration eject with auxiliary cleanup. Plain FAT on APFS passed. Writable FAT on LambCrypt FSKit stalled during unmount with both Disk Images services. Finder eject and writable FAT parity remain open. |
| 4. Lifecycle | Verify discovery, preferences, menu-bar state, and background exit from the signed bundle. | Pending |
| 5. Bugs and performance | Record regressions in [BUGLOG.md](BUGLOG.md) and profile FSKit, MacFUSE, and FUSE-T before claiming gains. | Pending |
| 6. Packaging | Verify FSKit package signing, notarization dry run, Finder smoke test, and rollback to MacFUSE. | Pending |

## Work while writable FAT is blocked

The writable FAT stall reproduces during the first clean dismount, as well as
after a busy-volume retry. The last recorded FAT unmount step was a metadata
write. The older Disk Images helper was waiting in a backing-file `pwrite`,
and the LambCrypt volume worker was idle. The newer Disk Images service
reproduced the stall. These results narrow the failure to the layered
FAT and FSKit configuration. The exact kernel dependency remains unknown.

1. **Continue offline failure testing.** Run
   `python3 -B Tests/test_macos_discovery.py --platform-archive /path/to/Platform.a`
   and `python3 -B Tests/test_fskit_volume_protocol.py --build-dir /path/to/built/src`.
   These cover discovery, attach and detach deadlines, and the volume worker
   protocol without starting Disk Arbitration. Prioritize incomplete
   inventory, stale worker identity, startup rollback, and credential
   lifetime when reviewing adjacent failure paths. These checks passed for the
   attach deadline, one-time compatibility retry, native protocol fixture, and
   rollback by captured worker identity. Live startup rollback and
   attach-timeout recovery remain pending.
2. **Move the FAT investigation to an isolated Tahoe host.** Use a spare Mac
   or an existing Apple Silicon guest that can load the signed FSKit module.
   The isolated environment and extension support are unverified. Prepare a
   disposable raw FAT image, expose it through a minimal test FSKit filesystem,
   and attach it using the same Disk Images settings as LambCrypt. Run the same
   single write, file sync, and detach against the image directly on APFS and
   through the test filesystem. Add the encrypted LambCrypt worker as the next
   comparison only after the minimal run. Capture mount state, the command’s
   deadline result, and the available user-space stacks. Stop the live run
   on the first kernel stall.
3. **Choose the next change from the result.** A stall with the minimal FSKit
   backing file supports a platform-level report using the synthetic fixture.
   If that control passes and LambCrypt still stalls, compare the filesystem
   callbacks, backing-file open flags, and worker traffic across the two runs.
   The prepared Apple kernel FAT pilot is a diagnostic. Writable FAT parity
   still needs clean and busy-release dismount, read-only remount with a
   matching checksum, Finder eject, and confirmed worker exit. MacFUSE stays
   the default while this gate is open.
