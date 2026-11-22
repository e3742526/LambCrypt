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
| 3. Read-write | Verify write and sync, file operations, xattrs, advisory locks, busy dismount, dismount after release, read-only remount, and Finder eject. | Blocked on live dismount after release |
| 4. Lifecycle | Verify discovery, preferences, menu-bar state, and background exit from the signed bundle. | Pending |
| 5. Bugs and performance | Record regressions in [BUGLOG.md](BUGLOG.md) and profile FSKit, MacFUSE, and FUSE-T before claiming gains. | Pending |
| 6. Packaging | Verify FSKit package signing, notarization dry run, Finder smoke test, and rollback to MacFUSE. | Pending |
