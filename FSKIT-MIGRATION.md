# LambCrypt FSKit migration

LambCrypt is a VeraCrypt derivative for Apple Silicon Macs running macOS 26
(Tahoe) or later. The macOS build now uses Apple FSKit with the existing
VeraCrypt volume format and LambCrypt crypto code. The macFUSE and FUSE-T
trials below record earlier builds. An existing installation can stay in use
while its FSKit replacement is verified on the host.

## Integrator checklist

- [ ] Copy [signing.env.example](src/Setup/MacOSX/signing.env.example) to a private
  `signing.local.env` outside the checkout. Keep the real Apple Team ID, signing
  identity names or fingerprints, and profile paths there or in CI secrets.
  The build uses Make, so source the environment file before building.
- [ ] Sign in to Xcode with an enrolled Apple Developer Program team. For
  development, make the Apple Development certificate and private key available
  in the local Keychain and register the test Mac with that team. For a VM, use
  the guest's Provisioning UDID from System Information and preserve its case
  exactly as displayed.
- [ ] Register an explicit App ID for
  `io.github.e3742526.LambCrypt.fskit.module` and enable the FSKit Module
  capability. Obtain the matching macOS development provisioning profile for the
  registered device and certificate. Store the profile outside the checkout
  and set `VC_FSKIT_PROVISIONING_PROFILE` to its absolute path. Decode the
  profile with `security cms -D -i "$VC_FSKIT_PROVISIONING_PROFILE"` and verify
  that `ProvisionedDevices` contains the verbatim identifier reported by the
  running test Mac. An uppercase variant of a lowercase VM identifier can
  pass a case-insensitive check and fail at launch.
- [ ] Set `VC_APP_SIGN_IDENTITY` to the corresponding Keychain identity. In a
  separate build tree with the build dependencies configured, source the local
  environment file and run `LOCAL_DEVELOPMENT_BUILD=true make -C src WITHFSKIT=1 prepare`.
  The recipe reads the Team ID from the profile, builds matching App Group
  entitlements, and signs the extension before signing the app. For a different
  Mac or VM, set `VC_FSKIT_TARGET_UDID` to that device's exact Provisioning UDID
  in the private signing environment before preparing or verifying the app.
- [ ] When signing successive FSKit candidates with the same marketing
  version, export an increasing `VC_FSKIT_BUILD_VERSION` before building.
  Use one to three dot-separated integers. Make writes the value to both
  the app and extension before signing. The standard app has the preferred
  Finder handler rank for VeraCrypt containers when both apps are installed.
- [ ] Run `codesign --verify --deep --strict src/Main/LambCrypt-FSKit.app`.
  Run `bash src/Setup/MacOSX/verify_fskit_bundle.sh src/Main/LambCrypt-FSKit.app`
  to check arm64, deployment target, bundle versions, signature and embedded
  profile expiry, authorized signer and exact target device, App Group
  entitlements, and the document handler rank for side-by-side installs. The
  verifier uses the local Mac's Provisioning UDID by default and checks apps
  extracted from a development package.
  In System Settings, go to General
  → Login Items & Extensions → By Category → File System Extensions and
  enable LambCrypt FSKit. Verify it on disposable internal-drive containers.
- [ ] At the release gate, set `VC_SIGN_TEAM_ID`, select the team's Developer ID
  Application and Developer ID Installer identities, and use a matching
  distribution profile that grants the extension's FSKit capability. Set
  `VC_NOTARY_PROFILE` to a Keychain credential profile created with
  `xcrun notarytool store-credentials`. From the release build tree, run
  `LOCAL_DEVELOPMENT_BUILD=false make -C src WITHFSKIT=1 prepare`, then
  `bash src/Setup/MacOSX/notarize.sh --fskit --dry-run`. The dry run checks
  Hardened Runtime and secure timestamps on the app and extension, signs
  the package, and verifies its expanded payload before cleaning up the
  scratch installer. It skips the notarization service. Drop `--dry-run` for
  an authorized release submission. [Apple capability matrix](https://developer.apple.com/help/account/reference/supported-capabilities-macos/),
  [Apple notarization requirements](https://developer.apple.com/documentation/security/notarizing-macos-software-before-distribution).
- [ ] Before committing, review the staged diff for team-specific values and
  files. Keep certificates, private keys, profiles, generated entitlements,
  signing logs, and signed bundles out of source control. The signed scratch
  extension contains an embedded copy of its provisioning profile.

## Stage gates

These gates record the original opt-in rollout. For new trials, use a separate
scratch tree and disposable internal-drive containers.

| Stage | Required evidence | Status |
| --- | --- | --- |
| 0. Baseline | Default MacFUSE build, discovery tests, and applicable FUSE-T checks pass. | Passed |
| 1. Build variant | MacFUSE remains default. The opt-in FSKit bundle builds separately. | Passed |
| 2. Read-only | Read a VeraCrypt payload and a fresh compatible container, then verify external dismount, background exit, and worker cleanup. | Passed on disposable containers |
| 3. Read-write | Verify write and sync, file operations, xattrs, advisory locks, busy dismount, dismount after release, read-only remount, Finder eject, and independent inactivity timers. | Signed native HFS+ and FAT12/16/32 read-write trials passed on Tahoe arm64, including read-only remount and writable Finder eject. Independent inactivity timers passed in earlier signed trials. |
| 4. Lifecycle | Verify discovery, preferences, menu-bar state, and background exit from the signed bundle. | Passed on the signed development bundle. Native menu checks covered Open in Finder, busy refusal, unmount after release, empty state, and opening Preferences. |
| 5. Bugs and performance | Record regressions in [BUGLOG.md](BUGLOG.md) and profile FSKit, MacFUSE, and FUSE-T before claiming gains. | FSKit and FUSE-T HFS+ measurements are recorded. The MacFUSE runtime comparison is pending on a Mac with the driver enabled. |
| 6. Packaging | Verify FSKit package signing, notarization dry run, Finder smoke test, and rollback to MacFUSE. | Local payload verification passed. The release dry run requires Developer ID Application and Installer identities and the FSKit distribution profile. Notarization and a MacFUSE rollback trial are also pending. |

## Read-write MVP starting point

At `954a10b9a76960195ec5ecf552c89ea0d3e968d6`, the mount worker
exposes a decrypted raw image through a sandboxed Swift FSKit module.
The wxWidgets Cocoa GUI and the CLI share the C++ mount lifecycle. The
provider writes existing image bytes and syncs through the worker. The
inner filesystem implements file and directory operations. Existing
protocol regressions cover interrupted and short writes, partial requests
and replies, stale generations, read-only enforcement, and failed sync.

The original attach path delegates filesystem selection to Disk Images.
The existing filesystem-permissions check recognizes some FAT and exFAT
signatures but does not select a driver. Ordinary FSKit startup and
teardown already use exact image-path inventory, worker serial, slot and
container validation, bounded process calls, and a shared teardown lock.
The worker tracks an IOKit media identity for external eject. Startup
rollback retains the worker when cleanup cannot be confirmed. Multiple
volumes have separate mount paths and slot and backing-file reservations.

The previous signed Tahoe arm64 checks covered the five VeraCrypt read
fixtures, HFS+ read-write, native HFS+ Finder eject, and an explicit FAT
kernel-driver trial. Ordinary writable FAT auto-selection and native
Finder eject on the FAT route were open. Release packaging has a local
dry run. Real Developer ID packaging and a loaded macFUSE runtime
comparison require their respective credentials and driver.

## Current macOS build variants

Fresh Apple Silicon scratch builds with Xcode 27.2 produced the default
MacFUSE bundle and the opt-in FUSE-T bundle. The default linked the macFUSE
5.5.0 package libraries extracted into scratch. The FUSE-T build linked
`libfuse-t` 1.2.9 and passed an HFS+ lifecycle check with write, sync,
read-only remount, and background exit. Both builds passed crypto self-tests.
The default build's volume library also matched all five VeraCrypt fixtures.
MacFUSE live mounts and runtime measurements still require an enabled driver.

The macOS build wrapper and Make now default to a 26.0 deployment target for
all three backends, independent of the selected Xcode SDK. The refreshed
arm64 scratch bundles include the recent teardown and write fixes. All three
linked with SDK 27.2, recorded 26.0 in their Mach-O and bundle metadata, and
passed their crypto self-tests on Tahoe. The MacFUSE volume library verified
all five VeraCrypt fixtures. FUSE-T and FSKit verified the SHA-512 fixture.
The current FSKit CLI also created a disposable FAT volume whose full
plaintext matched an independent upstream VeraCrypt reader. These checks
used unsigned bundles and exercised no live mounts.

Both FUSE bundles contain the English guide and have no FSKit extension. The
signed FSKit scratch bundle contains the same English guide and its own
extension, with no linked FUSE library. The checkout and staged diff
contained no active Apple Team ID, embedded profile, or matching signing
certificate. The repository's signing environment template contains empty
placeholders.

## VeraCrypt format verification

The signed arm64 FSKit build opened the five checked-in VeraCrypt containers
using read-only mounts. BLAKE2s-256, SHA-256, SHA-512, Streebog, and Whirlpool
all matched their existing decrypted-image checksums. A SHA-512 fixture from
the 2015 VeraCrypt history also matched the full image read by a separate
build of the [upstream VeraCrypt volume library](UPSTREAM.md).

On a disposable SHA-512 copy with a damaged primary header, ordinary mount
failed and `--mount-options=ro,headerbak` recovered the complete payload.
The read-only mounts preserved the encrypted file hashes and released their
workers. The same upstream build opened a fresh LambCrypt AES/SHA-512
container and matched the entire decrypted image after an unaligned FSKit
write and read-only remount. These checks used raw images with no inner
filesystem mounted.

A separate AES-Twofish-Serpent and SHA-512 container used a nondefault PIM,
a Unicode password, and two keyfiles. One filename contained Unicode and an
escaped comma. The signed app rejected a missing or wrong keyfile without
mounting the container or changing it. The independent VeraCrypt library
matched the full payload after an unaligned LambCrypt write, then wrote and
flushed its own sector. LambCrypt recovered the entire updated payload with
the keyfiles in reverse order on a read-only remount, which preserved the
encrypted container checksum.

## HFS+ file operations and errors

The signed FSKit bundle created a file in a disposable writable HFS+ volume,
synced it, renamed it, and removed a separate file. Opening a file with no
access permissions returned `EACCES`. Opening a missing file returned
`ENOENT`. Copies of the resulting container passed a read-only remount
with FSKit and FUSE-T. Both retained the renamed contents, reported the old
and deleted names as absent, and rejected creation with `EROFS`.

The signed FSKit lifecycle check created, replaced, read, and deleted HFS+
extended attributes. The binary value survived dismount and read-only remount,
and a read-only mutation returned `EROFS`. A second process was denied an
overlapping POSIX byte-range lock, acquired a lock on the adjacent byte, and
acquired the original range after release. The same run verified the payload,
background exit after a Disk Arbitration eject, and worker cleanup.

On both backends the CLI reported “No such file or directory” for a missing
container and “Permission denied” for an existing container with mode
`0000`. With mode `0400`, an ordinary mount fell back to read-only. The CLI
and kernel mount table agreed, the encrypted hashes matched after dismount,
and no test mount or backing file holder remained. The signed FSKit CLI
also retained the English missing-container diagnostic and full Unicode path
with French and Japanese process locales.

The FSKit provider also honors the `--rdonly` load option when the worker
itself is writable. The offline callback test verifies read access, `0400`
image permissions, and `EROFS` for write opens and write callbacks against
a disposable VeraCrypt fixture.

## External disk eject

Before the fix, Disk Arbitration refused to eject a busy read-only HFS+ image.
A full eject after the file closed removed the inner volume and disk image,
while the auxiliary mount and worker stayed active until a separate LambCrypt
dismount.

FSKit now watches the IOKit media identity after a successful attach and
matching discovery result. When that identity disappears, it confirms the
image is absent from Disk Images and revalidates the auxiliary filesystem
under the same lock used for ordinary teardown. The worker keeps serving I/O
while a bounded unmount helper runs. Incomplete inventory and a competing
dismount defer automatic cleanup.

The signed build preserved the volume through a filesystem-only unmount and
remount, then released the worker and auxiliary mount after full eject.
Tests also covered a held teardown lock, an attach-only image, and a
writable HFS+ image whose synced payload survived a read-only remount.
With two disposable HFS+ volumes, the background app kept running after
the first eject and exited after the last. The two workers and auxiliary
directories cleared, and both encrypted hashes matched. The
[macOS lifecycle check](Tests/README-macos-lifecycle.md)
includes an explicit signed FSKit mode using HFS+.

If Disk Images times out during attach, the worker starts a short follow-up
observation while it continues to serve the auxiliary filesystem. A separate
helper starts exact-image probes within a ten-second retry window, with
a deadline on each inventory request. In a signed test, macOS attached the
read-only HFS+ disk after the mount command returned its timeout. The payload
matched and a later external eject released the worker automatically. When
the disk never appeared, the observation helper exited and LambCrypt still
listed the worker for explicit dismount.

If attachment starts and rollback cannot confirm teardown, LambCrypt also
requests this observation before closing the activation channel. The
offline startup regression checks that the worker receives exactly one
handoff and that the caller retains the original cleanup warning.

A successful attach also requests this lookup when the first inventory and
attach result do not identify the same disk or the first IOKit lookup returns
no media identity. A signed read-only HFS+ test forced the first identity
lookup to fail. The original build retained the worker after eject, and the
patched build released the worker once the disk was fully ejected. Both
builds preserved the encrypted fixture checksum.

On a signed macOS 26.6.2 guest, a disposable read-only HFS+ container appeared
in the native status menu with its backing path and read-only label. Open in
Finder showed the verified payload. Finder's Eject command removed the
volume and released the disk image and worker. On a second mount, the
menu's Unmount command reported the busy volume while a file was open.
Declining force kept the volume mounted. After closing the file, Unmount
released the image, mount, and worker handle, and the menu showed no mounted
volumes. Preferences opened from the menu. Quitting the scratch app removed
its menu icon.

## HFS+ copy measurements

On Apple Silicon with macOS 26.6.2, separate arm64 release builds mounted copies
of the same disposable VeraCrypt-format HFS+ container read-only. A 256 KiB Unix
socket send buffer reduced FSKit's median 256 MiB copy time from 0.700 s to
0.372 s. Restoring the default buffer returned the median to 0.699 s. Each
run used seven measured copies after a warm-up. Copies matched the source
hashes, and each container's checksum matched after dismount. FUSE-T over SMB
took 0.234 s on the same workload. The benchmark used a warm cache and measured
read-only copies to APFS.

A separate write benchmark copied 256 MiB from APFS to a disposable HFS+
container, then synced and closed the file. FSKit baselines took 0.796 s and
0.828 s. Applying the 256 KiB send buffer to write requests larger than 8 KiB
brought the median to 0.350 s. FUSE-T took 0.240 s. Each run used seven measured
copies after a warm-up, and the final payload hash matched after read-only
remount. The FSKit extension was profiled with Instruments and sampled during
separate writes. The MacFUSE runtime comparison remains pending.

A follow-up trace split the same workload into copy, caller `fsync`, and
close. In each of two runs, backing-file flushes overlapped six of seven
measured copies, with 38–78 ms of overlap in those copies. No worker flush
overlapped caller `fsync` or close. In the trace that counted sector writes,
every worker flush over 1 ms followed new writes. The ten flushes after no
new writes took 33 µs in total across the full mount and dismount cycle.
This measurement did not support skipping flushes as a copy optimization.
Each copy matched its payload checksum and the final copy in each run matched
again after read-only remount.

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
   attach and auxiliary mount deadlines, one-time compatibility retry, native
   protocol fixture, and rollback by captured worker identity. Live read-only
   tests exercised rollback on an unformatted container and verified normal
   startup through the bounded helper on HFS+. The [password-cache regression](Tests/README-macos-lifecycle.md)
   verifies that concurrent cache access is synchronized and a wipe clears the
   cache. The protocol suite also verifies missing and disallowed socket paths,
   empty writes, and rejection of truncated writes before changing the fixture.
   Volume events and partial discovery compare the serial, slot, container
   path, and auxiliary mount path. The offline regression gives two entries
   the same serial and verifies that dismount, partial discovery, and logout
   preserve the other entry. Finder checks the same identity before opening.
   One deadline now covers a worker's entire incoming request, including a
   write payload. A signed read-only HFS+ test recovered discovery and
   dismounted after the worker dropped an interrupted request at 10 seconds.
   The extension also uses a 10-second deadline for connecting and sending a
   complete request, and a separate 10-second deadline for the complete
   reply. The protocol checks exercise a fragmented reply, a worker that
   stops reading a write, and clearing the incomplete read buffer.
   A replacement worker receives a well-formed stale write within the same
   request deadline, then returns `ESTALE` before touching the volume. The
   protocol test checks a 1 MiB write and a 32 KiB write and compares the
   decrypted image with the known hash before sending any valid writes.
   The auxiliary directory returns a stable nonzero verifier and supports
   resuming after the packer fills. The callback test covers dot entries in
   name-only listings, file attributes, end-of-directory, and invalid resume
   cookies. [Apple's FSKit enumeration contract](https://developer.apple.com/documentation/fskit/fsvolume/operations/enumeratedirectory%28_%3Astartingat%3Averifier%3Aattributes%3Apacker%3Areplyhandler%3A%29)
   The extension rejects a successful-looking inspection with an empty control
   record, an all-zero generation, or an image size outside signed file offsets.
   Socket fixtures cover valid limits, empty and malformed metadata, and a
   worker disconnect after one full read chunk. The interrupted read preserves
   the completed chunk and clears the rest of the requested buffer.

   The auxiliary mount helper's nonzero exit keeps the worker available when
   macOS already published the filesystem or the mount table is unavailable.
   The worker rechecks on cancellation. Confirmed absence still lets it exit
   immediately. Focused discovery tests verified these startup races offline.
   The dismount tests also verify that a matching image with an unusable
   device record preserves the FSKit backing mount. Verified image absence
   still permits auxiliary cleanup. A valid empty Disk Images inventory
   confirms absence without resolving the backing path, which may already
   have disappeared. After an explicit detach reports success,
   the app rechecks the exact image under its teardown lock. A surviving
   attachment or incomplete inventory leaves the backing mount and worker
   available. The offline check covers ordinary and forced dismount and
   reuse of the old BSD device number by an unrelated image.
   When more than one record refers to the same backing image, the records
   must agree on its device and mount point. Conflicts leave discovery
   unconfirmed and stop teardown before invoking detach. The regression
   covers canonical paths, aliases, and conflicts after a successful detach.
   After detach, ordinary and forced FSKit dismount both recheck the worker
   identity under the teardown lock before each auxiliary unmount attempt.
   The offline regression verifies that a changed identity stops the initial
   attempt or a retry after a busy response.

   In a separate socket-only read benchmark against the same worker, the
   deadlines reduced median 16 KiB throughput from 631 to 590 MiB/s after
   preallocating the request header. Median throughput at 128 KiB and
   1 MiB was within 0.2% of the original client.
   Preparing the Unix socket address once per volume raised median 16 KiB
   throughput from 590 to 615 MiB/s (4.2%) in seven interleaved, warmed runs
   per client. A repeat with 11 runs per client measured 594 to 614 MiB/s
   (3.5%). Median throughput at 128 KiB and 1 MiB changed by less than 0.4%
   in the first comparison. Receiving the reply header and payload with a
   single scatter read measured 589 MiB/s at 16 KiB. The extension still
   checks the endpoint and peer on every connection and uses the same
   request deadlines.
   A follow-up used nine interleaved runs per variant to test sending both
   reply fields with `writev`. The 16 KiB median fell from 616 to 583 MiB/s
   with the worker change alone, and from 617 to 598 MiB/s when combined with
   a scatter read in the extension. The worker still sends the header and
   payload separately.

   The Swift client now encodes the fixed 40-byte request header directly
   into a temporary buffer. On Apple Silicon with macOS 26.6.2, nine
   interleaved, warmed runs per build measured a 16 KiB median of 605.4
   MiB/s before and 610.2 MiB/s after. Two earlier comparisons measured
   595.7 to 607.3 MiB/s and 601.5 to 603.8 MiB/s. Median throughput changed
   by less than 0.2% at 128 KiB and 1 MiB in the nine-run comparison.
   Each timed run read 128 MiB through the same Unix socket worker and
   disposable VeraCrypt-format fixture. The existing protocol test checks
   exact header bytes and verifies the VeraCrypt payload checksum.
   These measurements cover the socket path.

   A 4-second sample of the worker during 128 KiB encrypted socket writes
   found 568 of 998 main-thread stacks in `Buffer::Erase`. The macOS build
   now clears buffers with `memset_s` and uses the existing volatile wipe if
   the system call reports an error. On an Apple M5 with macOS 26.6.2, the
   median for 128 KiB writes rose from 1,120 to 1,830 MiB/s. At 1 MiB it
   rose from 1,240 to 2,838 MiB/s. Both measurements used seven interleaved
   pairs, with one warm-up and three timed 128 MiB passes per build in each
   pair. Each writable run used a disposable container and verified its
   written data after a flush. The suite also checks that the full buffer
   is erased at small, odd, and bulk allocation sizes. Mounted copy speeds
   for this change remain unmeasured.

   The encrypted worker now completes short positioned writes and retries
   interruptions before reporting success. Protocol tests injected both
   faults while writing a disposable VeraCrypt fixture, then synchronized and
   reopened it read-only to verify the payload. A follow-up storage error
   still returns its original error code.

   FSKit discovery reads the worker's current counters directly. With two
   disposable HFS+ images attached read-only, activity on the second moved
   only its own dismount deadline.
   The macOS timer measures inactivity through the latest discovery sample.
   Reusing that sample cannot cross the deadline. A replaced auxiliary mount
   starts its own timer even if the container path and serial are reused.
   The offline test also covers unreadable counters and delayed observations.
   FSKit reserves each opened container in its local app group until its
   worker closes the file. On the signed Tahoe build, simultaneous mounts
   through aliases started one worker, a distinct container could still mount,
   and the refused alias mounted after release. These trials used raw images
   with no inner filesystem and preserved the encrypted container hashes.
   FSKit also holds a slot reservation for each worker. The signed build
   rejected a second explicit request for slot 1 and assigned different slots
   to two simultaneous automatic mounts.
   The live GUI honored the force-dismount preference on a busy read-only
   HFS+ mount and cleared a populated password cache while the file stayed open.
   Startup command processing also released its parsed password references.
   On the signed Tahoe scratch build, each real mount or unmount helper
   completed before its reply was deliberately delayed beyond the test
   deadline. After an auxiliary mount timeout, LambCrypt kept the worker
   discoverable and could unmount it. An attach timeout left a readable HFS+
   volume that LambCrypt could unmount. A detach timeout could be retried to
   remove the auxiliary mount. After an auxiliary unmount timeout, the
   backing file was already closed. Each case cleared the test mounts and
   preserved the encrypted container hash. The worker keeps serving startup
   requests while checking for a late mount. After the 10-second deadline,
   it releases the backing file only when a usable mount table confirms
   absence. While the table is unavailable, it retains the worker and its
   reservations until it can confirm the mount or its absence.
   In a separate signed trial, a delayed helper published the mount after the
   CLI reported the timeout. LambCrypt listed it, read the known VeraCrypt
   payload, and dismounted it. When the helper never mounted the image, the
   backing file was released after 10.1 seconds and the next mount succeeded.
   The offline check simulates the inventory failing past the deadline, then
   verifies that the worker serves a late mount or releases the backing file
   once absence is confirmed. Recovery from a longer live stall remains
   unverified.
   A disposable nested VeraCrypt-format container verified that the FSKit
   worker rejects an overlapping write and blocks later writes to the outer
   volume. Discovery reported that damage was prevented and the hidden
   payload survived a read-only remount. Direct POSIX writes to the
   auxiliary image exposed a separate Tahoe issue. After a rejected write,
   the mounted image returned those bytes from cache, while the worker and
   encrypted file still returned the original sector. That trial detached
   the disk image and closed the backing file, but the auxiliary mount
   originally required exact-path forced cleanup. Tracing showed that the
   worker exited when macOS temporarily omitted the mount during unmount.
   The worker now rechecks disappearance using a lock on the existing
   private mount parent. Three live reproductions of the rejected writes
   then completed ordinary unmount and released the backing file. A busy
   read-only HFS+ volume still refused ordinary unmount and detached when
   explicitly forced. External unmount also released the worker. The lock
   now covers disk-image discovery and detach. A competing dismount left
   the exact test image attached until the lock was released. When
   refreshing protection state after detach, LambCrypt now flushes the
   matched worker on a bounded socket request. A failed flush leaves the
   worker available for retry.
   The rejected-byte readback still occurs before unmount. Requesting a
   synchronous mount did not change the mount flags or readback.
   Independent file descriptors read the rejected 512-byte write even
   after Disk Images detached. Both the default and in-kernel Disk Images
   attachments exposed the stale bytes on the raw device. The worker and
   encrypted file retained the committed bytes. Setting
   `F_NOCACHE_EXT` on the writer or using page-aligned 16 KiB writes
   prevented the reproduction. The vnode-wide `F_GLOBAL_NOCACHE` flag
   did not. The public Disk Images commands expose no verified way to
   apply the extended flag to their own writer. The current SDK declares
   `FSVolume.DataCacheHandler` for macOS 27 onward. The public mount option
   introduced in macOS 26.4 only requests read-only operation. Behavior
   through a mounted inner filesystem remains pending.
   [Apple FSKit cache handler](https://developer.apple.com/documentation/fskit/fsvolume/datacachehandler)
2. **Move the FAT investigation to an isolated Tahoe host.** Use a spare Mac
   or an existing Apple Silicon guest that can load the signed FSKit module.
   Use a guest with a verified development profile. Prepare a
   disposable raw FAT image, expose it through a minimal test FSKit filesystem,
   and attach it using the same raw Disk Images settings as LambCrypt. The
   diagnostic compares two backing paths (APFS and the test FSKit filesystem)
   and two FAT drivers (the automatic macOS path and Apple's kernel `msdos`
   driver). Start with the two APFS controls, then run the kernel-driver
   FSKit case and the automatic FSKit case. Use a fresh fixture for each case.
   On the kernel path, attach with `hdiutil -nomount`, then run
   `/sbin/mount_msdos` and confirm the kernel FAT mount. Both Apple FAT
   drivers report `msdos`. The diagnostic uses the `fskit` mount flag
   to distinguish automatic FSKit FAT from kernel FAT before permitting
   payload writes. Capture the FAT driver, the command’s deadline result,
   and any available stacks.
   Each successful trial verifies payload persistence after a read-only
   remount and confirms both detaches. Stop on the first stall and preserve
   the lab state. The diagnostic runner timestamps each command, attempts
   bounded samples and matching unified logs on timeout, and records whether
   the extension entered and completed write and teardown callbacks. It also
   captures the kernel's FSKit unmount events and FAT deactivation events. Its
   offline checks passed. The prepared Apple Feedback draft includes the
   production traces, the synthetic reproduction, and the pending live
   comparisons. [Apple's FAT mount utility](https://github.com/apple-oss-distributions/msdosfs/blob/main/mount_msdos.tproj/mount_msdos.c#L298-L306)
3. **Choose the next change from the result.** A stall with the minimal FSKit
   backing file supports a platform-level report using the synthetic fixture.
   If only the automatic driver stalls with the same backing file, repeat the
   kernel-driver trial with the production encrypted worker before considering
   a FAT-specific mount route. If both diagnostic cases pass and the production
   worker still stalls, compare the callbacks, backing-file open flags, and
   worker traffic. Apple's kernel FAT driver passed unprivileged read-only
   mounting on a plain image and an FSKit-backed VeraCrypt fixture. The new
   diagnostic runner passed offline checks. The
   [production kernel FAT trial](Tests/README-macos-lifecycle.md#isolated-production-kernel-fat-trial)
   checks verified attachment, busy refusal, payload persistence, and worker
   and image release with the signed LambCrypt CLI. Its command and
   failure-order checks passed offline. The live writable trial with the
   signed LambCrypt worker also passed using explicit kernel FAT and the
   default Disk Images service. This makes the kernel FAT route a candidate
   for production integration. That route still needs normal GUI and CLI
   mount integration and native Finder eject verification. MacFUSE stays
   the default while this gate is open.
4. **Compare in-kernel Disk Images attachment on the isolated host.**
   A disposable read-only probe honored `hdiutil attach -kernel` on Tahoe.
   The default attachment started `diskimages-helper`. The in-kernel
   attachment started no helper and was recorded without a helper PID.
   It read the same raw-device checksum and detached cleanly. This is a
   separate variable from selecting the kernel FAT filesystem driver.
   The updated lab runner can request in-kernel attachment and stops on
   user-space fallback before writing. Compare matching APFS and FSKit
   cases using a fresh fixture for each. The signed production build used
   both FAT drivers read-only with each Disk Images path. All four trials
   matched the raw VeraCrypt checksum and FAT payload, refused busy eject,
   and released the worker after eject. Writable FAT on the in-kernel Disk
   Images path remains unverified. The isolated LambCrypt Tahoe Lab guest
   runs the same macOS 26.6.2 build (25G83) as the physical Mac.

   A separate signed preflight with the diagnostic module passed read-only
   with both FAT drivers on default Disk Images and with kernel FAT on the
   in-kernel path. With automatic FAT and in-kernel Disk Images, the inner
   read-only FAT mount disappeared from the mount table while Disk Arbitration
   was still waiting for unmount. The kernel logged `lifs_unmount` starting
   at 14:18:46.784 UTC on November 22, 2026. The recovered log covers the detach
   deadline and a later ordinary eject deadline. It shows no matching kernel
   completion, Disk Arbitration unmount result, or eject request from the
   detach caller. The default Disk Images control logged kernel completion
   about 5 ms after starting and then ejected the disk. Apple's published
   Disk Arbitration source places the “ongoing” event before `unmount(2)` and
   the success event in the completion callback.
   [Apple Disk Arbitration source](https://github.com/apple-oss-distributions/DiskArbitration/blob/a542bda934211dc3c301bfdcc7f21349c4164a85/diskarbitrationd/DARequest.c#L1345-L1475)

   The exported image refused writable opens, the exact attached image was
   read-only, and the diagnostic had no encrypted worker. A later sample
   of the retained FAT process located the read-only wait in
   `FSVolumeConnector unmount:` and `FSBlockDeviceResource metadataReadInto`
   through an IOKit call. The direct backing extension was idle in its
   concurrent sample. The writable trace used the same initial FAT unmount
   frames and blocked in the metadata write. Resolving the sampled call
   sites against the installed Apple FAT binary identifies both waits in
   the forced rewrite of the FAT clean flag. The read-only trial stalled
   while reading the FAT block. The writable trial stalled during the
   subsequent write. Apple's published implementation skips this rewrite
   for FAT12. [Apple FAT unmount code](https://github.com/apple-oss-distributions/msdosfs/blob/8aac438d87dc696cf424f0c0f46e874e7d85b9f0/msdos_appex/FATVolume.m#L1905-L1938),
   [Apple FAT flag update](https://github.com/apple-oss-distributions/msdosfs/blob/8aac438d87dc696cf424f0c0f46e874e7d85b9f0/msdos_appex/FATManager.m#L1153-L1214)

   A read-only `fsck_msdos` scan of the diagnostic FAT16 fixture, the APFS
   control, and the captured writable-stall image reported no structural
   errors. Both FAT copies in the diagnostic and APFS images were marked
   clean. The writable image retained its dirty flag in both copies. The
   kernel dependency behind the wait remains unverified. The diagnostic
   allows up to 12 seconds for the two-second process sample.
   On November 22, 2026 the isolated Tahoe guest passed the APFS-backed,
   read-only FAT16 control with in-kernel Disk Images and automatic FAT.
   The runner verified the fixture checksum and FAT root, confirmed Apple's
   FSKit FAT driver, and verified the image and mount were gone after detach.
   `hdiutil detach` took 10.47 s end to end. Disk Arbitration spent about
   10.39 s between the unmount request and the start of unmount. The kernel
   logged `lifs_unmount` start at 20:40:42.587 UTC and completion at
   20:40:42.590 UTC, then Disk Arbitration reported the eject. The 27 runner
   checks also passed in the guest. The matched FSKit-backed test remains
   pending guest provisioning.
   Repeat it with the same read-only fixture and mount sequence to compare
   kernel and FAT deactivation events on the same VM.
   The runner holds a per-user lock and checks macOS's mount table and Disk
   Images inventory before preparing each new fixture. It refused to start
   another case while the affected auxiliary mount remained present.

   The four successful production read-only trials used a 256 KiB FAT12
   VeraCrypt fixture and mounted FAT separately after attachment. The stalled
   direct FSKit trial mounted its FAT16 fixture during attachment. The FAT16
   diagnostic image matches the earlier successful APFS control byte for byte
   and has the same geometry as the captured production writable-stall image.
   The diagnostic now offers the verified VeraCrypt FAT12 plaintext and a
   separate automatic read-only mount as independent controls. Once the
   original APFS control passes, keep the original mount sequence when
   comparing FAT12 with FAT16. FAT12 exercises unmount without the forced
   flag rewrite. Vary the mount sequence in a separate comparison with a
   fixed fixture. Run the matching APFS control before each FSKit case.
   Both APFS-backed controls passed in the Tahoe guest. The VeraCrypt FAT12
   fixture mounted during attachment, and FAT16 mounted separately after
   attachment. Both used in-kernel Disk Images and Apple's automatic FSKit
   FAT driver. The runner verified the image checksums and both ejects.
   The kernel logged `lifs_unmount` completion in both cases, and the final
   inventory found neither image nor mount. The matched FSKit-backed trials
   are pending.

   The first FAT12 run stopped at fixture verification because macOS
   exposed `Dummy.txt` and the runner expected the uppercase FAT alias.
   The corrected runner compares the name case-insensitively and verifies
   the file's five bytes. Its offline regression covers both FAT spellings,
   lowercase, and invalid payloads. The corrected run verified and ejected
   the retained guest image before using fresh copies for the two controls.

   An additional read-only control placed the same FAT16 image on a FAT16
   volume mounted by Apple's own FSKit driver in the guest. The inner image
   rejected a writable open, matched the original checksum, and mounted via
   in-kernel Disk Images and Apple's automatic FAT driver during attach.
   The inner and outer detaches each took 40 ms end to end. The kernel
   reported `lifs_unmount` completion for both, and the final mount and
   image inventories were clear. The prior stall did not reproduce with
   Apple's FAT driver serving the backing file. The matched test using the
   LambCrypt diagnostic extension is needed to compare those backing paths
   on the same VM.

   The writable comparison used the same FAT16 fixture, in-kernel Disk
   Images attachment and automatic FAT driver on the same VM. On APFS it
   wrote and synced the payload, detached, and matched the payload checksum
   after a read-only remount. With Apple's writable FSKit FAT volume serving
   the backing file, write, sync and read-back passed, then inner detach hit
   the 30-second deadline. Disk Arbitration reported unmount in progress and
   the kernel logged `lifs_unmount` start without a matching completion in
   the capture. The inner mount entry disappeared while the outer FAT mount
   remained. The trial stopped before remounting or detaching the outer image.

   The guest sample and earlier writable LambCrypt sample have the same FAT
   binary UUID and frames at the same binary offsets down to
   `FSBlockDeviceResource metadataWriteFrom` and its synchronous IOKit call.
   This reproduces the writable symptom using Apple's filesystem and image
   layers alone. The read-only stall with LambCrypt backing remains a
   separate comparison. The retained guest images and trace are available for
   investigation. A later inventory confirmed that both disk images still
   had I/O Registry media objects and only the outer image still appeared
   in the mount table. A single ordinary `diskutil eject` on the verified
   inner image timed out after 15 seconds. Both images remained attached.

   The guest also passed the writable APFS-backed FAT16 control with
   in-kernel Disk Images and Apple's kernel FAT driver. The runner
   confirmed both selections on the writable and read-only attachments.
   It wrote and synced the payload, matched its SHA-256 after a read-only
   remount, confirmed both ejects, and found no residual diagnostic mount.
   A fresh guest run passed both that APFS control and the matched trial
   with Apple FSKit FAT serving the backing file. The nested case wrote and
   synced the FAT16 payload, matched its checksum after a read-only remount,
   verified the outer image again after remount, and released both images.
   The writable inner detach took about 0.25 seconds. Final mount and Disk
   Images inventories were clear. The comparison uses explicit kernel FAT
   mounting after in-kernel Disk Images attachment, so it verifies that
   combined route on Apple backing. A second matched pair kept the kernel
   FAT mount and selected default Disk Images. All four inner attachments
   reported a Disk Images helper. Direct and nested writes synced, kept
   the same payload checksum after read-only remount, and detached cleanly.
   The nested writable inner detach took about 0.19 seconds. These two
   controls cover both attachment services while holding the explicit kernel
   FAT mount route constant.

   A follow-up held a writable file open in each default-service kernel FAT
   case. Disk Images refused both detaches with status `EBUSY` (16). The
   original writable image remained attached and the held file still matched
   its payload. Both detaches succeeded after close, and the read-only
   remounts verified the payload again. Final inventories were clear.
   LambCrypt now recognizes this exit status when reporting a busy volume,
   including when the system diagnostic is missing or localized.

   The diagnostic bundle for the guest builds from the reproducer's recorded
   revision with Xcode 27.2, targeting macOS 26.0 on arm64. The wxWidgets
   dependency's PCRE2 library was linked statically for this separate lab
   build. The executable and extension link only macOS libraries. The crypto
   self-test and raw backing I/O test passed. The original development profile
   listed only the physical Mac.

   A separate production FAT trial bundle was rebuilt from the current
   worktree with the same static PCRE2 selection. Its app and extension are
   arm64, target macOS 26.0, and link only macOS dynamic libraries. The
   launcher carries the production lifecycle test and refuses to start on a
   physical Mac or with an unprovisioned bundle. The signing step uses the
   private environment and checks the profile's device list before embedding
   it. In the guest, the production CLI passed its
   crypto self-tests. A read-only test executable linked to the same volume
   code recovered all five VeraCrypt fixtures and verified their plaintext
   checksums and unchanged encrypted bytes. These tests require no mount.

   The first guest-profile run found a separate IPC bug. The guest's longer
   home path exceeded the fixed `sockaddr_un` path field. The worker and both
   clients now use Darwin's variable-length Unix socket addresses and keep
   the socket in the app group. The [protocol regression](Tests/test_fskit_volume_protocol.py)
   verified a 253-byte endpoint through both clients. The rebuilt app and
   extension passed strict signature verification.

   After enabling LambCrypt under File System Extensions, Tahoe attempted
   to launch it. The guest log reports code `-212`, “Provisioning profile
   does not allow this device.” Both the profile plist and its signed DER
   payload carry an uppercase device ID. The running guest reports those
   digits with lowercase letters. The earlier signing check ignored case.
   The mount stopped before any image attached, and both inventories were
   clear. A new development profile matched the running guest's identifier
   exactly in both the decoded plist and signed DER payload. The re-signed
   bundle loaded the module and passed the writable production trial with
   Apple's kernel FAT driver and the default Disk Images service. It wrote
   and synced data, exercised create, rename and delete, confirmed that a
   busy unmount preserved the image and worker, then dismounted cleanly after
   closing the open file. A read-only remount matched the payload checksum.
   The final inventory contained no test image, mount, or worker handle.
   This run used an explicit kernel FAT mount. The automatic mount route
   still selects Apple's FSKit FAT driver on the affected configuration.

## FSKit installer payload check

FSKit builds use the same native architecture for the app, extension and
wxWidgets in both signing modes. On Apple Silicon the distribution
preparation built both executables as arm64 and passed the CLI crypto
self-tests before rejecting the device-scoped development profile.
Development preparation with that profile still passed strict signature
verification.

A local `productbuild --component` run packaged the development-signed
`LambCrypt-FSKit.app`. After expansion with `pkgutil --expand-full`, the
payload contained one app with the FSKit bundle identifier. Its executable,
Info.plist, and embedded profile matched the source app byte for byte, and
the expanded app passed `codesign --verify --deep --strict`. The installer
itself was unsigned. A dry-run check simulated the distribution credentials
and exercised actual package creation, expansion and payload verification
with no notarization call. Developer ID signing and notarization require the
release signing identities and the matching FSKit distribution profile.

## External USB container check

On the physical Mac, the volume reader opened a disposable copy of the
VeraCrypt AES/SHA-512 fixture directly from a USB drive formatted as exFAT.
The encrypted file was written and synced, both encrypted checksums matched
the source, and the decrypted FAT payload matched the known checksum. The
test removed the copy. This check exercises a file-backed volume on external
storage without mounting the encrypted filesystem or accessing the raw disk.

## Kernel FAT routing and verification

The opt-in FSKit build reads the opened volume's boot sector. A
structurally plausible, unpartitioned FAT12, FAT16, or FAT32 volume
uses Disk Images attach-only and Apple's kernel `mount_msdos`. The
same route honors read-only protection. Its default mount directory is
`volume` in the FSKit worker's private mount parent. An explicit
directory must already exist. LambCrypt reports the actual path in its
volume list. Attach-only requests still suppress filesystem mounting.
Unrecognized geometry, partitioned images, HFS+, exFAT and APFS retain
system selection.

The mount uses the existing teardown lock and confirms the exact backing
image and IOKit media identity before and after the kernel mount. LambCrypt
checks the kernel mount table for the expected driver, directory and access
mode. A mount timeout or inconclusive attachment identity leaves the
worker available for cleanup. The existing rollback handles a confirmed
mount failure. Before a normal detach the app rechecks the selected worker,
image and IOKit media. Writable teardown verifies the worker's encrypted
file sync after the image detaches. The same check runs before worker
cleanup after an external eject. A failed sync leaves the worker available.

If macOS removes a published auxiliary mount before releasing the disk
image, the worker keeps its reservations and socket. After the mounting
caller hands off attachment observation, a bounded helper checks the exact
image path in Disk Images, even though the backing file no longer
resolves. The worker can exit when both inventories confirm absence. A
retained image or failed inventory query keeps it running and backs off before
retrying. Startup rollback releases its attachment handoff before waiting
for worker exit. The discovery regression simulates a retained image with a
missing auxiliary path, an incomplete inventory, and eventual image release.

Validation used macOS 26.6.2 (25G83), arm64, and Xcode SDK 27.2.
The integrated native trials ran on the physical Apple Silicon Mac using
the signed development app built from `c5d9e1f3` and the normal Disk Images
service. All writable fixtures were newly created file-backed containers.

| Check | Result |
| --- | --- |
| FSKit build and crypto | PASS. Clean signed development build, strict app and extension signature verification, crypto self-tests and all five VeraCrypt fixture hashes through the linked volume reader. |
| Offline mount and write lifecycle | PASS. Discovery, FAT routing, media reuse checks, busy retry, failed sync, stale worker generation, interrupted and partial I/O, and auxiliary startup and teardown fault cases. |
| Native kernel FAT controls | PASS. Freshly generated encrypted FAT12, FAT16 and FAT32 containers were decrypted by the standalone reader. Plain APFS-backed copies passed explicit Apple kernel mount, write, fsync, busy refusal, clean detach, read-only remount and payload hashes. These controls exercise Disk Images and the FAT driver. |
| Signed FAT12, FAT16 and FAT32 read-write | PASS. Ordinary LambCrypt mounts used Apple's kernel FAT driver and honored explicit and default directories in both access modes across the matrix. File and directory operations, timestamps, sync, busy refusal and retry, and SHA-256 verification after read-only remount passed. FAT16 also dismounted a separate keyfile-protected backup-header mount while the first volume stayed busy. |
| Signed HFS+ read-write | PASS. Automatic Apple filesystem selection, sync, binary extended attributes, cross-process POSIX advisory locks, busy refusal and retry, and read-only content and metadata verification passed. The background GUI also discovered the volume and exited after eject when registered before mounting. |
| Read-only exFAT control | PASS. A fresh encrypted exFAT container used automatic Apple filesystem selection, mounted read-only and dismounted cleanly. Writable exFAT and APFS were not tested. |
| Native Finder eject | PASS. Finder ejected writable HFS+, FAT12, FAT16 and FAT32. Each trial verified the backing image, mounted filesystem and worker were gone. Disk Arbitration eject also passed in read-only trials. |
| Native FUSE-T | PASS. The arm64 FUSE-T 1.2.9 build passed crypto and an HFS+ lifecycle with persisted payload, background exit, and cleanup. |
| macFUSE | PARTIAL. The default arm64 build linked the extracted macFUSE 5.5.0 libraries and passed crypto self-tests. The driver was unavailable for live mounts, comparison or rollback. |
| Release package | PARTIAL. The expanded local installer preserved the signed development bundle. The release preflight rejected the development-only signature. Developer ID signing and notarization remain unverified. |

A separate build of the upstream VeraCrypt volume library decrypted all
four written HFS+ and FAT containers. Read-only mounts of the resulting
disposable images matched the independently generated payload SHA-256 and
expected timestamps. HFS+ also preserved the binary extended attribute.
Each test detached the plaintext image and verified that the encrypted
container's checksum was unchanged by the independent read.

The initial physical-host attempt reported `EINVAL` at the auxiliary
probe. The signed matrix passed after the current scratch app used a
distinct bundle build version, a host-matched profile, and an exclusive
per-account test registration. The previous registration was restored
after testing. These steps were applied together, so the earlier probe
failure has no confirmed single cause.

In the first HFS+ GUI run, Launch Services registered the app after
the CLI had mounted the read-only volume. The FSKit extension received
`SIGTERM` and the inner image remained attached after the auxiliary mount
disappeared. An ordinary detach recovered the exact disposable image.
Two later attempts to use a freshly re-registered extension immediately
also failed before image attachment with ExtensionKit error 2. Launching
the signed scratch GUI once on an empty session before mounting allowed
the full HFS+ GUI and Finder trials and the resumed CLI trials to pass. The
[lifecycle test notes](Tests/README-macos-lifecycle.md#signed-fskit-gui-preflight)
record the preflight. The automatic FAT driver stall still has an
independent Apple-only reproducer in the writable FAT investigation above.

### Signed Tahoe guest installation and replacement

The independently provisioned UTM guest ran macOS 26.6.2 (25G83), arm64.
The exact running device matched the embedded development profile. The
guest first opened the signed scratch app with an empty session, then
passed an ordinary FAT12 write, busy dismount retry and read-only remount.
After confirmed teardown, the trial replaced the scratch app at the same
path. Both bundles retained the same marketing version and application
identifiers. The app and extension build numbers increased together from
`1.28.10` to `1.28.11`.

The replacement passed its first GUI launch and the ordinary FAT12,
FAT16, FAT32 and HFS+ read-write matrix, including read-only verification.
FAT16 dismounted an independent keyfile/backup-header fixture while the
first volume stayed busy. HFS+ passed background discovery, Disk
Arbitration eject, and automatic GUI exit. The runner verified the final
mount and Disk Images inventories and restored the prior per-account
test registration. This was a development bundle install and replacement
with all volumes already dismounted. Notarized package installation,
in-use replacement and native Finder UI eject in the guest remain
unverified. Native Finder eject passed on the physical Mac.

The updated bundle recipe builds matching app and extension build numbers
and gives the FSKit app the Alternate document handler rank. On the
physical Mac, Launch Services offered the FSKit build as an opener for
a disposable `.hc` file and kept the existing default. A development
installer preserved the signed binaries, property lists and embedded
profile. Its Distribution recorded the application build number and
used the marketing version for the package version. The release dry
run rejected the development signature before packaging for notarization.

### FUSE-T rollback check

FUSE-T 1.2.9 on the physical Mac mounted a disposable copy of the
encrypted HFS+ container previously written by signed FSKit. It verified
the persisted payload, timestamp and binary extended attribute read-only,
then wrote and synced a new file in a writable mount of the copy.
After read-only remount both payloads matched their expected SHA-256
hashes, the source container's encrypted checksum remained unchanged,
and no image, mount or open backing file remained.

The host reported the FSKit module disabled on later scratch registration
attempts despite an enabled PlugInKit record. Those mounts failed before
Disk Images attached. The guest matrix independently passed with the same
runtime code. The host registration discrepancy remains open.

The worker-retention change passed the offline discovery and worker
protocol suites and compiled into a signed arm64 Tahoe development build
with passing crypto self-tests. Its development installer preserved the
signed payload. The rebuilt FUSE-T 1.2.9 client passed its FAT write,
sync, read-only remount and cleanup trial. The rebuilt default macFUSE
client linked and passed its crypto self-tests using the extracted vendor
libraries and framework. The kernel driver remains unavailable for live
mounts. The physical host reproduced the same enablement failure
before the new build reached Disk Images. The host inventory and prior
registration were checked after the attempt. The earlier signed matrix
remains evidence for the filesystem routes. Live teardown after auxiliary
loss still requires a signed runtime trial on the updated build.

### Physical Tahoe activation and attachment handoff, November 23, 2026

The physical Apple Silicon host ran macOS 26.6.2 (25G83). At 02:50 EST,
PlugInKit listed the `io.github.e3742526.LambCrypt.fskit.module` extension
with a `+` user election, and a development-signed FSClient probe reported
the same older scratch path disabled. At 02:52 EST, a host-provisioned
`1.28.13` build was the path returned by FSClient. The isolated GUI
launch exited 0. An ordinary disposable HFS+ trial exited 1 during
formatting when `mount -F` reported the module disabled. Disk Images
never attached the decrypted image. The nominally correct registration
therefore reproduced the disabled state. The earlier path mismatch was
also real and could select a different bundle independently of enablement.

The signed app and extension used the bundle IDs
`io.github.e3742526.LambCrypt.fskit` and
`io.github.e3742526.LambCrypt.fskit.module`. Both passed strict signature
verification. The signing teams and App Groups matched, the embedded
development profile authorized the exact host provisioning identifier and
FSKit Module entitlement, and the module declared `lambcryptfs` path URL
resources. The short filtered unified log window provided no matching
FSKit launch or provisioning diagnostic for the failed mount. The
effective disabled state is confirmed. The reason for the disagreement
with PlugInKit remains open. The test left File System Extensions policy
as found. See the [signed probe and native reproduction](Tests/README-macos-lifecycle.md#signed-fskit-gui-preflight).

The mount service now uses a five-second FSClient query before opening
the worker endpoint. It checks the signed bundle's exact module path and
reports missing, conflicting and disabled registrations separately. The
signed `1.28.14` CLI rejected the older registered path. At 03:03 EST
the same build's empty GUI launch exited 0 and FSClient returned the
intended path disabled. The native CLI exited 1 with the disabled
diagnostic on a newly generated FAT12 container. Both attempts stopped
before worker startup or image attachment. The test registration was
removed afterward, leaving the original PlugInKit record. The final
census found no test mounts, images, processes or newly created sockets.
Four socket nodes from earlier trials remained. Their creation dates
preceded this session, and none had a live socket owner or corresponding
auxiliary directory. They were preserved. The development bundle
preparation verifies the signed team against the embedded profile and
checks the full signature after signing both bundles.

The attachment review found a second startup window. Disk Images can
still publish an attachment after the attach command times out, and the
worker can lose the auxiliary mount before that image reaches the
inventory. The mounting caller now marks the request pending before it
can start the attach. If it exits without a completion report, an empty
inventory preserves the worker. When the worker observes the exact
attachment, it resumes normal cleanup once absence is confirmed.
Production-loop simulations exercised empty and unavailable inventory,
late publication, and final release with and without an auxiliary mount
observed. Explicit and concurrent teardown still use the per-auxiliary
lock and refresh the disk and worker identifiers before detach. Finder
and Disk Arbitration eject rely on I/O Registry media disappearance and
an exact Disk Images check before auxiliary unmount. The worker's
separate session can outlive the background app. An unresolved attach
that never appears can leave its worker, keys and reservations held.
If the auxiliary mount disappears, the
ordinary mounted-volume list may also lose the entry. Preserve that
state for exact-image diagnosis instead of starting a different backend.

The `1.28.14` development build linked for arm64 and macOS 26.0. Its
crypto self-tests, five offline VeraCrypt fixture hashes, focused
discovery, protocol, preflight, credential retry and build metadata
checks passed. The default macFUSE arm64 bundle linked against isolated
copies of the vendor libraries, had no FSKit framework dependency, and
passed crypto self-tests. The host had no loaded macFUSE driver.
A native FUSE-T 1.2.9 FAT trial passed write, sync, read-only remount,
hash verification and cleanup. The development installer expanded to a
byte-matching app and extension with valid signatures and the embedded
profile. Developer ID Application and Installer identities and an FSKit
distribution profile were unavailable for signing a release; notarization,
clean release installation, upgrade and rollback remain unverified.
Native FSKit worker retention, busy and multi-volume teardown, Finder
eject, filesystem integrity and performance remain unverified on the
updated revision.

### Detached worker inventory and offline package verification

The native Disk Images drill exposed a failure in the bounded process
runner. The worker closes stdin, stdout and stderr at startup. Its
inventory helper could then allocate a pipe at one of those descriptor
numbers, where the spawn file actions also redirect child I/O. The
standalone subprocess regression failed against the original platform
archive with those descriptors closed. Moving the pipe ends above the
standard descriptors before spawning preserved stdout, stderr, the child
exit status and the existing isolation and time limits.

On the physical arm64 macOS 26.6.2 host, the fixed build passed the
[native Disk Images worker drill](Tests/README-macos-lifecycle.md#native-disk-images-worker-drill).
Two independent workers served new 4 MiB FAT containers. With the
mount-table observation injected, one retained its generation, reads and
locks while its exact image was attached. The second retained those
resources across an empty inventory and subsequent image publication.
Detaching the first image left the second worker and image active.
Each worker released its socket and reservations after its own detach.
The upstream VeraCrypt reader matched every decrypted byte for both
fixtures and left both encrypted inputs unchanged. The rebuilt default
macFUSE client passed crypto self-tests against isolated vendor libraries.
The rebuilt FUSE-T client passed its native FAT write, sync, read-only
remount and cleanup again.

Disk Images used APFS-backed read-only raw files in this drill. The
signed FSKit extension, live disappearance of its auxiliary filesystem,
and native Finder and writable filesystem tests still require an
enabled FSKit integration host.

The `1.28.15` development bundle and its expanded installer payload
passed the offline bundle verifier. The verifier rejected a mismatched
extension build number and rejected the development profile in
distribution mode. The FSKit release script checks this same contract
before packaging and on the expanded payload, while retaining its
Developer ID, Hardened Runtime and secure timestamp requirements.
It now compares the packaged extension executable and Info.plist as well
as its provisioning profile. No notarization request was submitted.

### Warm-cache HFS+ comparison on the MVP revision

On the same physical Tahoe host, FSKit and FUSE-T 1.2.9 each tested a copy
of the same 128 MiB encrypted HFS+ fixture. Each backend ran one warm-up and
five measured passes. Sequential I/O used 1 MiB blocks and a 64 MiB
payload. Random I/O used 256 discrete 4 KiB operations at identical
offsets. The metadata workload created, queried, and deleted 64 files.
Both backends verified the final payload SHA-256 after read-only remount
and completed cleanup. These timings describe a single warm-cache
workload. The read measurements include the system cache.

| Operation | FSKit | FUSE-T |
| --- | ---: | ---: |
| Sequential write, median | 58.5 ms | 62.4 ms |
| Sequential read, median | 7.5 ms | 8.9 ms |
| Sequential write `fsync`, median | 33.5 ms | 46.2 ms |
| Random write, median | 85.5 ms | 77.4 ms |
| Random read, median | 0.38 ms | 0.36 ms |
| Random write `fsync`, median | 25.5 ms | 24.7 ms |
| Close after sync, median | 0.012 ms | 0.015 ms |
| Metadata workload, median | 4.44 ms | 3.53 ms |
| Writable mount / dismount, one observation | 0.86 s / 2.45 s | 0.54 s / 2.38 s |
| Worker CPU time / final RSS across six passes | 0.39 s / 6.58 MiB | 0.89 s / 6.61 MiB |

CPU time and RSS cover only the process that held the encrypted backing
file. Whole-backend resource usage, cold-cache runs and the live macFUSE
comparison remain unmeasured.

### November 23 audit follow-up

The worker keeps its backing file and reservations through polling errors.
It checks attachment ownership on the ordinary teardown path and retries
inconclusive media lookups at five-second intervals. Detach requires an
inventory that resolves ownership of the exact image. An incomplete
inventory can still supply a positive result for the volume list.

When an attach times out and its publication remains unresolved, the
worker records `attachment-pending` in the private parent of the
auxiliary mount and reports the exact image path. Use
`hdiutil info -plist` to look up that path. Leave the worker and
reservations in place while ownership is uncertain. The marker clears
after the worker observes the matching attachment. A timed-out request
that never publishes can leave its worker retained because an empty
inventory cannot establish cancellation.

The FSKit, FUSE-T and macFUSE builds now share a backing-file reservation
for local regular-file containers. It also covers read-only opens and
hard-link aliases. Remote files, raw devices and already-running older
binaries fall outside this shared reservation.

On macOS 26.6.2 (25G83), the injected discovery and native two-attachment
drills passed. The native drill used real Disk Images attachments with
injected auxiliary disappearance. The production FUSE-T service held
the reservation across mount and released it on dismount. Its FAT
write, sync and read-only remount passed. The three builds passed crypto
self-tests. The FSKit development bundle passed offline verification.
The native signed-module integration and release gates below remain open.

### Follow-up on unconfirmed attach and BSD media reuse

The bounded runner reports whether `hdiutil attach` started and lost a
confirmed exit or output. A timeout before launch takes ordinary startup
rollback. A timeout, signal, or incomplete output after launch keeps
attachment monitoring active and prevents a second attach attempt. A
normal exit still permits the existing retry for an unsupported
`-noautofsck` option. If an interrupted request never publishes, the
worker still needs conclusive OS evidence to release its resources.

On the kernel FAT route, LambCrypt holds a read-only, close-on-exec raw
device descriptor across `mount_msdos`. It verifies the image path and
I/O Registry media again after opening the descriptor. The hold covers
the command's lookup of the BSD name. Explicit detach still uses a fresh
image and media check before the name-based Disk Images command. Apple's
Disk Arbitration implementation also derives a BSD name when a client
constructs a disk object from I/O Registry media.
[Apple storage driver](https://github.com/apple-oss-distributions/IOStorageFamily/blob/main/IOMediaBSDClient.cpp#L3609-L3624)
[Apple Disk Arbitration implementation](https://github.com/apple-oss-distributions/DiskArbitration/blob/main/DiskArbitration/DADisk.c#L349-L373)

The focused discovery, process, protocol and native worker checks passed
on macOS 26.6.2 (25G83). Native Disk Images FAT12, FAT16 and FAT32 fixtures
with the same held-descriptor flags passed write, sync and checksum
verification after a read-only remount. These raw fixtures tested the OS
mount behavior independently of the FSKit extension. The development
installer payload passed offline verification. All three builds passed
crypto self-tests, and FUSE-T passed the disposable FAT lifecycle trial.
A read-only signed
FSClient probe still found a different registered bundle with effective
enablement false and exited 3. PlugInKit still reported a positive
election for the module identifier. Host policy was left as found.

## Writable exFAT and APFS integration gate

Disk Images selects Apple's filesystem driver for both formats. For APFS,
LambCrypt displays the mounted APFS volume and uses the whole-image media for
teardown and external eject observation. Ordinary mounts accept one GPT-backed
APFS container with a single volume. The attach-only mode can inspect layouts
with more than one APFS volume. A rejected ordinary mount goes through the
existing Disk Images rollback. If macOS cannot confirm detach, the worker
retains the backing volume and reservations.

### November 23, 2026 verification

The physical test host was an arm64 Mac17,2 running macOS 26.6.2 (25G83).
The signed baseline was build `1.29.2` from
`ce521cefb91dc6e68125d17166b9323ff36e54fd`. The signed physical candidate,
build `1.29.3`, used that commit plus production patch SHA-256
`e2c8e77988a8829f5076c0806f1731b477f17f371945d2ebb894affab0e7e550`.
Its executable SHA-256 was
`3994dada78f1e2671767bef3cc7a57d80a15112f98ea61af5ac961027db816dd`.

| Case | Fixture, driver, and observed result |
| --- | --- |
| exFAT on the physical Mac | **PASS** on the baseline, including Finder eject. The candidate passed the same write, busy retry, read-only remount, independent plaintext verification, and Disk Arbitration eject checks. The fixture was 96 MiB, with 100,401,152 decrypted bytes and unpartitioned exFAT. Apple used its FSKit exFAT driver. The writable candidate used `/dev/disk7` at the scratch mount directory. The read-only mount used `/Volumes/LCEXFAT`. |
| Single-volume APFS on the physical Mac | **PASS** on the baseline, including Finder eject. The candidate passed write, busy retry, read-only remount, binary extended attributes, independent plaintext verification, and Disk Arbitration eject. The candidate's Finder operation was pending when the UI tool lost access. Ordinary teardown then cleared that attachment. The 256 MiB fixture had 268,173,312 decrypted bytes. Its GPT store started at byte 20,480 and occupied 268,132,352 bytes. Apple's APFS driver mounted `/dev/disk8s1` from container `/dev/disk8`. The physical store was `/dev/disk7s1` on `/dev/disk7`. The read-only mount used `/Volumes/LCAPFS`. |
| Two-volume APFS on the physical Mac | **PASS** for rejection and cleanup. On a fresh 1 GiB fixture, Apple reported `/dev/disk7`, store `/dev/disk7s1`, container `/dev/disk8`, and volumes `/dev/disk8s1` and `/dev/disk8s2`. LambCrypt reported the single-volume restriction and released the image, media, worker, and backing-file reservation. |
| FAT12, FAT16, FAT32 and HFS+ | **PASS** for the native CLI lifecycle matrix on the physical candidate. FAT16 also dismounted an independent keyfile-backed fixture while its first mount stayed busy. |
| Tahoe lab guest | **FAIL** at the attach-only mount on macOS 26.6.2 (25G83), arm64. The statically linked signed build `1.29.5` passed strict bundle verification, matched the guest's development profile, and the signed FSClient probe reported the exact scratch module enabled. The APFS fixture was created, but macOS reported “Couldn’t communicate with a helper application” before Disk Images attached. No guest fixture was formatted in that attempt. |
| Distribution | **NOT TESTED**. Distribution signing, notarization and installation remain separate release gates. |

Both successful physical fixture runs exercised unaligned random writes,
overwrite, truncate, rename, deletion, timestamps, and fsync. The first
dismount with an open handle refused and kept the original worker. The
read-only remount preserved the expected payload SHA-256
`bc9942a59b08fcd584615a2261b042f1af633c4e762ea3b99651f1b2329f47d6`.
An independent upstream VeraCrypt reader matched the full decrypted image
and left ciphertext unchanged. The candidate's exFAT plaintext SHA-256 was
`35a788ef8cfba7875681756b2eb63670315159ad26a24b707122c44550ea45de`.
The APFS plaintext, including GPT and container metadata, matched
`64ede44eda859c484d57f15fcdbff5e8189421662b97d2bb8be34ba8038cb193`.

The candidate evidence is in the private trial directories
`/private/tmp/lambcrypt-exfat-trial-g48vu4hb`,
`/private/tmp/lambcrypt-apfs-trial-gqbfmuta`, and
`/private/tmp/lambcrypt-apfs-trial-xj21_dvm`. The baseline Finder-eject
inventories are in `/private/tmp/lambcrypt-exfat-trial-v2t55kes` and
`/private/tmp/lambcrypt-apfs-trial-3nzqsvj_`. The writable exFAT image used
auxiliary mount parent `lambcrypt-fskit.TqOJOAVw` and registry media
`0x100003d51`. The writable APFS image used parent
`lambcrypt-fskit.xm3goxPE`, whole media `0x10000389b`, and volume media
`0x1000038af`. Each evidence directory contains the exact image path,
media identities, mount paths, worker identity, backing inode and final
inventories. No trial attachment or backing holder remained on the Mac.

The standalone protocol harness caught a build-flag mismatch in the new
`VolumeInfo` field. Declaring the field consistently for macOS fixed the
harness. The clean signed build `1.29.4` used the same base commit plus
production patch SHA-256
`ec29f682ff5dcf3ade6c5ebbf770b6067590c731246406f16cd8cb4e3216ac6c`.
Its executable SHA-256 was
`b33562a7b9b3900c4f9791d9d05d5dccddb807868b746b7457faf475b2279a63`.
The focused protocol, discovery, formatting guard and native worker lifecycle
tests passed, along with the cryptographic self-tests. After
the scratch registration was restored to the installed app, the signed
probe found that app with effective `enabled=false` despite a positive
PlugInKit election.

The first guest app linked to a Homebrew PCRE2 library that the clean guest
lacked. The retry linked PCRE2 statically for the scratch build and produced
executable SHA-256
`b7b7e8128e05b74088dc3c6c66ad82542cfbd637ed0f32bc23b934634d2bde47`.
That run reached the FSKit helper error with no trial mount or Disk Images
attachment in the final guest inventory. Its log archive is
`guest-result-b1fac6447e60571c.tar.gz` under
`~/Library/Caches/LambCrypt-FSKit/filesystems-guest.d6XFtzPF`.

See the [reproducible lifecycle commands](Tests/README-macos-lifecycle.md#signed-exfat-and-apfs-integration-gate).

## Remaining migration gates

The FSKit-only macOS build and local installer passed on the physical arm64
macOS 26.6.2 host. The build ran with a package-config guard that rejects FUSE
lookups. The signed app and extension passed linkage and signature checks both
before and after installer extraction.

At 15:39 EST on November 23, 2026, PlugInKit listed the newly installed app
with a positive election. FSClient found the exact installed module at
`/Applications/LambCrypt-FSKit.app` and reported `enabled=false`. A fresh
disposable container opened far enough to reject the mount with the disabled
module diagnostic. Disk Images inventory and the fixture's open file handles
were clear afterward. The earlier local app remains available while activation
is resolved.

A follow-up removed the two obsolete Launch Services registrations and
verified that the installed app was the sole registration for its bundle ID.
A version-only trial re-signed the same binaries and profile with matching
app and extension build numbers bumped from `1.27.1` to `1.29.1`. The isolated
launch succeeded and FSClient still reported the module disabled. The
original bundle was restored after the trial.

1. Verify that FSClient sees the intended signed FSKit module as enabled.
   Complete a disposable mount, write, sync, dismount and read-only remount
   before replacing an existing local installation.
2. With the signed FSKit bundle enabled, run the two-mount FAT12 smoke
   trial and the physical Finder matrix. Run an isolated auxiliary-loss
   drill with a test build that can inject the observer's missing-mount
   result without forcibly unmounting the backing filesystem. Record the
   exact image path, media identity, worker generation, socket and
   reservations through retained attachment and ordinary detach. Also
   test a timed-out attachment that publishes after startup reports
   incomplete cleanup.

The macOS build uses FSKit. To return to an earlier app, confirm teardown of
any active worker and decrypted image before opening the same container again.
