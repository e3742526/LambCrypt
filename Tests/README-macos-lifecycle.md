# macOS lifecycle regression checks

Run these checks on macOS with Xcode Command Line Tools and Python 3. They do not
require administrator privileges, mounted containers, or an installed test app.

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
The runner also runs `macos_process_test.cpp`
against the real platform archive, checking subprocess deadlines, output limits,
descriptor isolation, error reporting, and child reaping with its own helper
processes. `macos_volume_state_test.cpp` includes production headers directly to
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
shutdown endpoint. The default lifecycle check uses FUSE-T and a FAT fixture.
For the signed FSKit scratch bundle, select `--fskit-external-eject` to use
HFS+. This path verifies the exact Disk Images attachment and mount mode,
checks binary extended attributes and POSIX advisory locks across processes,
and verifies the attributes after a read-only remount. It then uses `diskutil`
to eject the image and checks worker cleanup and background exit.

```sh
python3 Tests/test_macos_gui_lifecycle.py --fskit-external-eject --keep-artifacts \
  --binary "$VC_FSKIT_BUILD_SRC/Main/LambCrypt-FSKit.app/Contents/MacOS/LambCrypt-FSKit"
```

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
