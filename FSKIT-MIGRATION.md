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
| 3. Read-write | Verify write and sync, file operations, xattrs, advisory locks, busy dismount, dismount after release, read-only remount, Finder eject, and independent inactivity timers. | HFS+ passed file operations, xattrs, advisory locks, permission errors, clean and busy-release dismount, read-only remount, independent timers, and automatic cleanup after an external Disk Arbitration eject. Finder eject through the UI is pending. Plain FAT on APFS passed. Writable FAT on LambCrypt FSKit stalled during unmount with both Disk Images services. |
| 4. Lifecycle | Verify discovery, preferences, menu-bar state, and background exit from the signed bundle. | Signed background exit and menu population checked. Native menu interaction is pending. |
| 5. Bugs and performance | Record regressions in [BUGLOG.md](BUGLOG.md) and profile FSKit, MacFUSE, and FUSE-T before claiming gains. | Pending |
| 6. Packaging | Verify FSKit package signing, notarization dry run, Finder smoke test, and rollback to MacFUSE. | Pending |

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

Finder's UI could not be exercised because the desktop tool could not obtain
a Finder window.

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
separate writes. MacFUSE runtime comparison and writable FAT verification
remain pending.

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
   still permits auxiliary cleanup. After an explicit detach reports success,
   the app rechecks the exact image under its teardown lock. A surviving
   attachment or incomplete inventory leaves the backing mount and worker
   available. The offline check covers ordinary and forced dismount and
   reuse of the old BSD device number by an unrelated image.
   When more than one record refers to the same backing image, the records
   must agree on its device and mount point. Conflicts leave discovery
   unconfirmed and stop teardown before invoking detach. The regression
   covers canonical paths, aliases, and conflicts after a successful detach.

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
   preserved the encrypted container hash. The worker now keeps serving
   startup requests for up to 10 seconds while checking for a late mount.
   In a separate signed trial, a delayed helper published the mount after the
   CLI reported the timeout. LambCrypt listed it, read the known VeraCrypt
   payload, and dismounted it. When the helper never mounted the image, the
   backing file was released after 10.1 seconds and the next mount succeeded.
   Recovery from a longer system stall remains unverified.
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
   The isolated environment and extension support are unverified. Prepare a
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
   failure-order checks passed offline. The live writable kernel-driver
   trials remain pending. Writable FAT parity requires clean and
   busy-release dismount, read-only remount with a matching checksum, Finder
   eject, and confirmed worker exit. MacFUSE stays the default while this
   gate is open.
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
   Images path remains unverified. The local virtualization inventory
   contains no configured Tahoe guest.

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
   Run the missing APFS control with automatic FAT and in-kernel Disk Images
   first on the isolated host. The runner saves a bounded kernel and Disk
   Arbitration trace for completed detaches after checking the mount and
   image inventories. Use the same read-only fixture and compare kernel
   and FAT deactivation events before repeating the stalled case.
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
   The new controls passed offline checks and await isolated Tahoe
   verification.
