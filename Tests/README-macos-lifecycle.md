<!-- Modified for LambCrypt by the LambCrypt contributors. Changes from VeraCrypt are in the git history; see UPSTREAM.md. -->
# macOS lifecycle regression checks

Run the standalone checks with Xcode Command Line Tools and Python 3. Use
the canonical development-signed app and the normal login account for
the installed FSKit tests.

LambCrypt asks each user to accept its license on first use. Tests that run the
`lambcrypt` binary need `export LAMBCRYPT_LICENSE_ACCEPTED=1` first, which
accepts the terms for those processes without recording anything.

Build the matching LambCrypt sources first. Use a clean build after changing
headers: the current makefiles do not track every header dependency. The archive
architecture must match the compiler's default architecture.

From the repository root, set `VC_TEST_BUILD_SRC` to the `src` directory of that
build, then run:

```sh
VC_TEST_BUILD_SRC=/absolute/path/to/build/src
python3 Tests/test_macos_discovery.py --platform-archive "$VC_TEST_BUILD_SRC/Platform/Platform.a"
python3 Tests/test_fuset_cleanup.py --build-dir "$VC_TEST_BUILD_SRC"
python3 Tests/test_fuset_aux_directory.py --build-dir "$VC_TEST_BUILD_SRC"
```

The password-cache check exercises concurrent reads, stores, and wipes under
ThreadSanitizer. It then opens a disposable VeraCrypt fixture using a password
snapshot retrieved before the wipe. Compile the cache implementation into the
test so its accesses are instrumented.

```sh
VC_CACHE_TEST_DIR=$(mktemp -d)
xcrun clang++ -std=c++11 -O1 -g -fsanitize=thread \
  -DTC_UNIX -DTC_BSD -DTC_MACOSX -DARGON2_NO_THREADS -D_FILE_OFFSET_BITS=64 \
  -I src -I src/Crypto -I src/Crypto/Argon2/include -I src/PKCS11 \
  Tests/volume_password_cache_test.cpp src/Volume/VolumePasswordCache.cpp \
  "$VC_TEST_BUILD_SRC/Volume/Volume.a" "$VC_TEST_BUILD_SRC/Platform/Platform.a" \
  -framework CoreFoundation -framework IOKit -o "$VC_CACHE_TEST_DIR/cache-test"
cp Tests/test.sha512.hc "$VC_CACHE_TEST_DIR/test.sha512.hc"
TSAN_OPTIONS=halt_on_error=1 "$VC_CACHE_TEST_DIR/cache-test" "$VC_CACHE_TEST_DIR/test.sha512.hc"
```

The auxiliary-directory check exercises the production FUSE-T private-parent
helpers against disposable local directories, including concurrent creation,
inherited ACL removal, setup failure cleanup, per-mount parent removal, and
discovery ownership. The temporary filesystem must support ownership and ACLs.
The helper check simulates disabled ownership without mounting a filesystem.
An optional elevated run also checks caller access, parent immutability, and
actual uid isolation using a harmless fixture:

```sh
sudo python3 Tests/test_fuset_aux_directory.py --build-dir "$VC_TEST_BUILD_SRC" --owner "$(id -u)"
```

The private parent protects auxiliary filesystem paths; these checks do not
assess FUSE-T transport authentication. Existing volumes must be dismounted and
remounted with the updated build to receive this protection.

The discovery runner compiles the production plist and batch-refresh methods
with an in-memory inventory provider. It checks exact and legacy alias matches,
unresolved inventory, stale-field invalidation, one query per refresh, and fresh
discovery before destructive operations. The auxiliary mount timeout check
verifies that a mount already visible in the kernel table retains its worker
for dismount. The teardown tests use a real directory lock and simulated
kernel snapshots to check transient mount disappearance and worker exit.
It also simulates macOS dropping an auxiliary mount while its disk image
is still attached. The worker must retain its endpoint through a retained
or incomplete Disk Images inventory and exit once the exact image is gone.
The startup rollback regression verifies the mounting caller hands over
attachment observation before waiting for worker exit. It also drives the
production worker loop through an attach timeout, empty and unavailable
inventories, late publication, and final release. One case never publishes
the auxiliary mount. These are simulated macOS events.
The runner also runs `macos_process_test.cpp`
against the real platform archive, checking subprocess deadlines, output limits,
descriptor isolation including detached workers with closed standard descriptors,
error reporting, and child reaping with its own helper processes.
`macos_volume_state_test.cpp` includes production headers directly to
check auxiliary mount owner/backend/basename filtering and initial, partial,
invalidated, and stale snapshot decisions.

The cleanup runner compiles production cleanup and rollback methods with mocked
mount, service, and device operations. It checks failure ordering, reporting of
unconfirmed service exits after auxiliary-mount removal, retryable busy
unmounts, per-volume hidden-protection refresh, and responsive probes during
busy startup rollback. It also runs the production multi-volume unmount loop
with scripted outcomes: every unconfirmed service exit must be reported, even
when another volume fails or a forced-unmount prompt is declined. It exercises
macOS automatic dismount with populated ordinary and favorite password caches,
a simulated unconfirmed service exit, and a second volume that remains busy.
It checks that both caches and the token-session close call honor the wipe
preference before teardown. Finally, it runs `macos_cleanup_state_test.cpp`
against the real serialization code to check that cleanup failure details
survive IPC and that local display state leaves the legacy `/control` bytes
unchanged.

These tests exercise state and serialization contracts. They do not establish
real backend timing, GUI rendering, or filesystem behavior under forced unmount.

### Native Disk Images worker drill

With a matching FSKit build, run this on Apple Silicon as a regular user.
The signed bundle only creates two disposable FAT containers in this drill.

```sh
python3 -B Tests/test_macos_fskit_worker_lifecycle.py --build-dir "$VC_TEST_BUILD_SRC"
```

The test compiles the production worker into a test executable and injects
its mount-table observation. Each worker decrypts a new container through
its normal socket protocol. Disk Images attaches the resulting APFS-backed
raw files read-only and without mounting their inner filesystems. The test
records the exact image paths, media identifiers and worker generations.
One worker sees the auxiliary mount disappear with its image already
attached. The other sees an authoritative empty inventory before its image
appears. Both must continue serving reads with their reservations held.
The late-publication fixture also checks the private `attachment-pending`
indicator and verifies its removal when teardown finishes.
The test detaches each verified fixture by its current device identity
and checks that only its worker, socket and reservations are released.

This exercises the production worker, socket, process runner and Disk Images
inventory on macOS. A signed module, real auxiliary filesystem loss and
Finder eject still require an enabled FSKit integration run. Add
`--keep-artifacts` to retain test fixtures and capture files on success.
A failed trial preserves its artifacts. Inspect the exact test records with
`hdiutil info -plist` and recover any retained fixture without forcing detach.

For an ordinary integration check with a FUSE-T GUI build, close other LambCrypt
and VeraCrypt processes and dismount their volumes first. Run the tests from a
logged-in macOS desktop session.

```sh
python3 Tests/test_macos_gui_lifecycle.py --binary "$VC_TEST_BUILD_SRC/Main/LambCrypt"
python3 Tests/test_macos_gui_inactivity.py --binary "$VC_TEST_BUILD_SRC/Main/LambCrypt"
python3 Tests/test_macos_gui_teardown.py --binary "$VC_TEST_BUILD_SRC/Main/LambCrypt"
```

These use isolated preferences and disposable file containers. When testing a
packaged app with the lifecycle check, pass its executable inside
`LambCrypt.app/Contents/MacOS/` so the check launches it in its original bundle.
A standalone executable still uses a minimal test bundle, which does not
reproduce all packaged-app behavior. The lifecycle check verifies
write/fsync/remount integrity, background startup with a mounted
volume, refresh after a CLI dismount, and automatic GUI exit. It checks service
exit, closed backing-file handles, and removal of the auxiliary mount and
shutdown endpoint. It also checks the backing-file reservation through a
hard-link alias before and after writable dismount. The default lifecycle
check uses FUSE-T and a FAT fixture.
With Python 3.11 or later and the signed FSKit scratch bundle, select
`--fskit-external-eject` to use HFS+. This path verifies the exact Disk Images
attachment and mount mode, busy refusal with the original worker intact,
binary extended attributes, and POSIX advisory locks across processes.
It verifies content and attributes after a read-only remount and checks
that the read-only pass preserves the encrypted checksum. It uses `diskutil`
to eject the image and checks worker cleanup and background exit. Add
`--cli-only` to check the filesystem and worker lifecycle without launching
the GUI. In the GUI trial, `--finder-eject` tests writable Finder eject after
the read-only verification pass.

```sh
python3 Tests/test_macos_gui_lifecycle.py --fskit-external-eject --keep-artifacts \
  --binary "$VC_FSKIT_BUILD_SRC/Main/LambCrypt-FSKit.app/Contents/MacOS/LambCrypt-FSKit"
```

### Signed exFAT and APFS integration

Use Python 3.11 or later on the Apple Silicon Mac with the canonical
development-signed app. Close LambCrypt and VeraCrypt and check for retained
mounts, images or workers. Run one trial at a time. The runner records the
FSClient URL, source commit, build and binary digest, then creates its own
private fixture. Test ordinary creation for exFAT and raw single-volume APFS,
and use fixture formatting to cover a GPT-backed import.

```sh
export LAMBCRYPT_LICENSE_ACCEPTED=1
VC_FSKIT_CLI=/Applications/LambCrypt-FSKit.app/Contents/MacOS/LambCrypt-FSKit
python3 -B Tests/test_macos_fskit_filesystems.py --fskit-exfat --cli-create \
  --isolated-host --binary "$VC_FSKIT_CLI" --activation-probe "$VC_PROBE_DIR/check_fskit_activation" \
  --build-commit "$VC_FSKIT_TESTED_COMMIT" --reader "$VC_UPSTREAM_READER" --finder-eject
python3 -B Tests/test_macos_fskit_filesystems.py --fskit-apfs --cli-create \
  --isolated-host --binary "$VC_FSKIT_CLI" --activation-probe "$VC_PROBE_DIR/check_fskit_activation" \
  --build-commit "$VC_FSKIT_TESTED_COMMIT" --reader "$VC_UPSTREAM_READER" --finder-eject
python3 -B Tests/test_macos_fskit_filesystems.py --fskit-apfs \
  --isolated-host --binary "$VC_FSKIT_CLI" --activation-probe "$VC_PROBE_DIR/check_fskit_activation" \
  --build-commit "$VC_FSKIT_TESTED_COMMIT" --reader "$VC_UPSTREAM_READER" --finder-eject
```

Set `VC_FSKIT_TESTED_COMMIT` to the commit used by the local updater, recorded
in its private build directory. The upstream VeraCrypt reader takes
`VOLUME PASSWORD PIM` and writes the AES/SHA-512 plaintext data area to stdout.
The runner compares the complete plaintext image and verifies that the
independent reader leaves the ciphertext unchanged.

Eject the named writable disposable volume in Finder when prompted. Use
`--fskit-apfs --apfs-multiple` separately to verify multi-volume rejection
and whole-image teardown. Omit `--cli-create`, `--reader` and
`--finder-eject` for that case. If a failure leaves an attachment, retain its
logs and inspect the exact image before using ordinary dismount.

[Local installation and activation procedure](../fskit-reactivation-runbook.md)

### Signed FSKit GUI preflight

Query FSKit directly from the login account before the first native test.
Sign the small probe with the test app's Apple Development identity. On
the physical Tahoe test host that signature exposed the LambCrypt module
to the probe. The ad hoc probe returned only system modules. Keep the
signed probe and the test bundle outside the checkout.

```sh
VC_FSKIT_APP=/Applications/LambCrypt-FSKit.app
VC_PROBE_DIR="$(mktemp -d)"
xcrun swiftc Tests/check_fskit_activation.swift -o "$VC_PROBE_DIR/check_fskit_activation"
codesign --force --sign "$VC_APP_SIGN_IDENTITY" "$VC_PROBE_DIR/check_fskit_activation"
date
pluginkit -m -A -D -v -i io.github.e3742526.LambCrypt.fskit.module
"$VC_PROBE_DIR/check_fskit_activation" --register "$VC_FSKIT_APP"
```

The probe returns 0 for the intended enabled module, 1 for the intended
disabled module, 2 for a missing module, 3 for a different registered copy,
4 for an unavailable FSKit query, and 5 for unsuccessful Launch Services
registration or duplicate app paths. PlugInKit's `+` records a user election.
FSKit supplies the effective state for its own module lookup. An enablement
change belongs in System Settings under General → Login Items & Extensions
→ By Category → File System Extensions. Open the intended signed app on an
empty session, then recheck the exact module URL. If the module remains
disabled, record both results with the time and stop the native trial.

After the probe returns 0, use the ordinary routed FAT12 trial below for a
disposable write, sync, dismount and read-only remount. Its two mounts
exercise the actual extension. Confirm the final mount table, Disk Images
inventory and worker cleanup before running the rest of the matrix.

Launch and close the canonical development-signed app before mounting
anything for the GUI trial. Use empty, isolated preferences so the app
cannot mount saved favorites or devices during this check. Leave `TMPDIR`
at its ordinary session value. The background app should exit on its own
with these preferences when there are no mounted volumes.

```sh
VC_FSKIT_CLI=/Applications/LambCrypt-FSKit.app/Contents/MacOS/LambCrypt-FSKit
VC_GUI_PREFS="$(mktemp -d)"
mkdir "$VC_GUI_PREFS/LambCrypt"
cat >"$VC_GUI_PREFS/LambCrypt/Configuration.xml" <<'EOF'
<VeraCrypt><configuration>
<config key="BackgroundTaskEnabled">1</config>
<config key="CloseBackgroundTaskOnNoVolumes">1</config>
</configuration></VeraCrypt>
EOF
XDG_CONFIG_HOME="$VC_GUI_PREFS" "$VC_FSKIT_CLI" --background-task
```

On macOS 26.6.2 (25G83), one initial GUI registration coincided with
termination of the scratch extension and left the disposable read-only
HFS+ image attached. The empty launch let later GUI trials pass. If the
runner reports a retained image, preserve its logs and identify it in
`hdiutil info -plist` before attempting ordinary cleanup. The HFS+ and FAT
preflights stop before creating a fixture when a prior diagnostic image is
still attached or the inventory is incomplete.

For a local update smoke test, use the
[canonical updater](../fskit-reactivation-runbook.md#build-sign-and-install)
with `--smoke`. Confirm the inner mount, image, auxiliary mount and
worker disappear before repeating. The updater keeps the previous
version archived outside the registration path.

### Historical macFUSE rollback check

For reproducing historical macFUSE trials, use a separate physical Mac with the
matching macFUSE driver already loaded. Dismount the FSKit fixture and
confirm its image and worker are gone. Keep the original disposable
container and use a copy for the rollback test. Verify the prior macFUSE
binary links macFUSE, then run this lifecycle smoke test.

```sh
otool -L "$VC_MACFUSE_CLI"
python3 -B Tests/test_macos_gui_lifecycle.py --cli-only --binary "$VC_MACFUSE_CLI"
```

Then mount the rollback copy read-only, verify the expected hash,
dismount, and confirm the Disk Images and mount inventories are clear
of the fixture. Use a second disposable copy to repeat the busy
dismount refusal with a file open and the successful retry after close.
Record the loaded driver version and both attachment inventories.

### Isolated production kernel FAT trial

After the direct-backing control passes with default Disk Images and the
kernel FAT driver, run the matching trial on isolated Apple Silicon Tahoe.
Use a provisioned, signed scratch FSKit app with its extension enabled.
The preflight checks both the mount table and the Disk Images inventory for
retained LambCrypt, VeraCrypt, or FAT diagnostic images before creating a container.

```sh
python3 -B Tests/test_macos_gui_lifecycle.py --fskit-kernel-fat --isolated-host --keep-artifacts \
  --binary "$VC_FSKIT_BUILD_SRC/Main/LambCrypt-FSKit.app/Contents/MacOS/LambCrypt-FSKit"
```

The CLI attaches the disposable FAT image through the production encrypted
worker. The test confirms the exact Disk Images record, then mounts its
device with Apple's `mount_msdos` and checks the kernel FAT and protection
flags. It checks file creation, rename and deletion, a synced payload, and
busy refusal with the original mount still listed. It then verifies ordinary
dismount, worker and image release, and payload integrity after a read-only
reopen. The teardown check reads the mount table and Disk Images inventory
with deadlines before probing the backing paths. The open-file check also
has a deadline. A failure leaves the disposable volume and evidence for diagnosis.
Native Finder eject has its own smoke check.

### Ordinary FSKit FAT routing

Use Python 3.11 or later and a dedicated, logged-in Apple Silicon Tahoe
test system with the canonical development-signed bundle. Run each case separately
so a retained image stops the next trial. This mode uses an ordinary
LambCrypt mount and checks that the app selected the kernel FAT driver.
It checks the exact device, expected FAT width and requested access mode.

```sh
VC_FSKIT_CLI=/Applications/LambCrypt-FSKit.app/Contents/MacOS/LambCrypt-FSKit
python3 -B Tests/test_macos_gui_lifecycle.py --isolated-host --fskit-routed-fat 12 --binary "$VC_FSKIT_CLI"
python3 -B Tests/test_macos_gui_lifecycle.py --isolated-host --fskit-routed-fat 16 --fat-default-directory --binary "$VC_FSKIT_CLI"
python3 -B Tests/test_macos_gui_lifecycle.py --isolated-host --fskit-routed-fat 32 --binary "$VC_FSKIT_CLI"
```

The writable and read-only passes exercise opposite directory choices.
The trials cover create, rename, deletion, directory changes, sequential
and unaligned random writes, truncation and extension, read-back, FAT
timestamps, sync, busy refusal, clean dismount, and a persisted payload
hash. The read-only pass checks the encrypted hash again after Disk
Arbitration eject. FAT16 also dismounts a second, keyfile-protected
backup-header mount while the first volume stays busy. The HFS+ trial
checks extended attributes and POSIX locks. FAT extended attributes and
locks are outside this test's assertions.

Add `--finder-eject` to each routed FAT run to exercise writable eject
from Finder. The existing `--fat-finder-eject` spelling is also accepted.
After the read-only pass the test remounts writable and prints the exact
directory. Eject that volume from Finder within 90 seconds. The runner
checks for the disappearance of the inner mount, backing image and worker.
A timeout or failed assertion preserves the scratch artifacts for diagnosis.
Use `--keep-artifacts` to keep the logs and container after a successful run.

The inactivity check takes about two minutes. It attaches two
disposable HFS+ containers read-only and verifies independent idle timers. Use
`--active-second` to read the second image and verify that only its deadline
moves. Use `--busy-first` to hold the first filesystem open through its idle
deadline with forced dismount disabled, then verify that it dismounts after
release. For FSKit, pass the executable inside the signed scratch bundle so
the test can reach the enabled extension.

```sh
python3 Tests/test_macos_gui_inactivity.py --active-second \
  --binary "$VC_FSKIT_BUILD_SRC/Main/LambCrypt-FSKit.app/Contents/MacOS/LambCrypt-FSKit"
```

The teardown check needs an unsigned local build and clang, and
takes about three minutes. It slows a service down with `fuset_startup_faults.c`
and verifies two automatic-unmount cases: a normal quit request that arrives
meanwhile is honored, including unmount on quit; and when service exit cannot be
confirmed, a warning keeps the background application from exiting silently.
That warning stays on screen until the test ends. Failed-run artifacts are
retained for diagnosis; use `--keep-artifacts` to retain successful runs as well.

## Menu-bar smoke check (manual)

Launch the candidate app in a logged-in session with isolated preferences and
only disposable containers. With **Background Task** enabled, click the
LambCrypt icon in the macOS menu bar. Check that it reports no mounted volumes
after discovery finishes. Mount a disposable volume read-only and reopen the
menu: the entry should match the main window, be labeled read-only, and its
**Open in Finder** action should open the mounted filesystem, not the container.
Unmount it from its submenu and verify that both views drop the entry. Repeat
with an external CLI unmount: reopen the menu after the list refreshes and verify
that it no longer offers actions for the old mount.

For an in-use test, keep a file on a disposable volume open in another process.
Use **Unmount** from the menu. If the filesystem reports it is busy, decline
any force prompt and verify the volume remains listed; close the file and retry.
Check that disabling **Background Task** removes the icon. These manual checks
exercise the native menu; the automated lifecycle test does not click it.

Use disposable containers for ordinary create/write/fsync/unmount/remount checks,
released-client compatibility, and user/root ownership combinations. Keep logs
private and verify service exit, closed backing-file handles, removed auxiliary
mounts and endpoints, and payload integrity after remounting.

To exercise release compatibility without launching the background GUI:

```sh
python3 Tests/test_macos_gui_lifecycle.py --cli-only \
  --binary "$VC_TEST_BUILD_SRC/Main/LambCrypt" \
  --release-binary /Applications/LambCrypt.app/Contents/MacOS/LambCrypt
```

Use FUSE-T builds for both binaries. The released client creates a fresh normal
container, the candidate writes and syncs data, and the released client remounts
it read-only and verifies the payload. Both dismounts are checked for cleanup.
Point both arguments at the installed release to check the test setup before
building a candidate. Do not use an existing container as test input.

## Full synchronization and interruption evidence

`test_fskit_volume_protocol.py` exercises the encrypted worker against real
backing files and injects interruption, unsupported full-sync and I/O errors.
It requires the worker to retry interruption and return the original failures.
The installed FSKit build requests full synchronization before publishing a
writable attachment, when receiving a sync, on last writer close and during
final writable teardown. A write acknowledgment follows encrypted backing
writes. It carries no device-flush result.

Run the native Disk Images worker drill separately. The disk attachments and
worker sockets in that drill are real. Auxiliary loss and publication timing
are injected. For installed native crash validation, create a disposable
container, record acknowledged file syncs, interrupt only the intended test
process, confirm attachment ownership and finally verify a read-only remount
and payload hashes. Verify the inner filesystem offline on a copy if needed.
Record each process and interruption point tested. The protocol and worker
drills cannot establish native filesystem crash or physical power-loss
recovery.
