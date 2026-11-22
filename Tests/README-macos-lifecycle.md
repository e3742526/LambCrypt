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
discovery before destructive operations. It also runs `macos_process_test.cpp`
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
when another volume fails or a forced-unmount prompt is declined. Finally, it
runs `macos_cleanup_state_test.cpp` against the real serialization code to
check that cleanup failure details survive IPC and that local display state
leaves the legacy `/control` bytes unchanged.

These tests exercise state and serialization contracts. They do not establish
real backend timing, GUI rendering, or filesystem behavior under forced unmount.

For an ordinary integration check with a FUSE-T GUI build, close other LambCrypt
processes and dismount their volumes first. In a logged-in macOS desktop session:

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
shutdown endpoint. The inactivity check takes about two minutes: it verifies
that automatically unmounting one idle volume does not restart another volume's
idle timer. The teardown check needs an unsigned local build and clang, and
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
