# VeraCrypt security findings — verification and repair plan

Baseline: `f38c8090` (master). I re-checked every finding against the source. I did not build or run anything, so all verdicts come from reading the code. Severity is re-rated against the real trust boundary, meaning who the attacker is and what they gain that they did not already have.

## 1. Verification verdicts

| ID | Verdict | Re-rated | Why it differs from the survey |
|---|---|---|---|
| SEC-ELEV-001 | **Confirmed, broader than reported** | Medium (defense in depth) | The same resolver (`Process::FindSystemBinary`, `Platform/Unix/Process.cpp:342-397`) is used by the **root service** for `mount`, `umount`, `losetup`, `dmsetup`, `modprobe` and `blkid` (`Core/Unix/CoreUnix.cpp:311,1003,1024,1212`, `Core/Unix/Linux/CoreLinux.cpp:546,633`). So a non-root-writable `/usr/local/{s,}bin` gives root code execution as well as sudo password capture. The precondition is a system misconfiguration that already affects root's `secure_path` on Debian and Ubuntu. |
| SEC-TMP-001 | **Mechanism confirmed, scope corrected** | Low–Medium | The vulnerable `#else` branch (`CoreUnix.cpp:1333-1371`) is the default for **Linux, FreeBSD, OpenBSD and macFUSE**, not only "classic macOS". It is not exploitable in a sticky, root-owned `/tmp`, because others cannot remove a root-owned directory there. It is reachable when the root service's temp dir is user-owned. Linux `pam_tmpdir` does this by design: `CoreUnix.cpp:845-857` maps root to `/tmp/user/<loginuid>`. A sudoers `env_keep` of `TMPDIR` does it too. The attacker is the requesting user, so this crosses a boundary only under restricted sudoers delegation. A side DoS also exists: pre-creating all 255 `GetFuseMountDirPrefix()<N>` names in `/tmp` blocks mounting. |
| SEC-DRV-001 | **Mechanism confirmed, impact refuted** | Low (policy integrity) | The flag only relaxes isolation of the **caller's own** volume, so the user who sets it only weakens their own volume. The "other accounts can read plaintext" claim is wrong. `IRP_MJ_CREATE`/`READ` on the volume device are not gated by `IsVolumeAccessibleByCurrentUser` (`Ntdriver.c:657-660`). That function only gates list, properties and dismount (`Ntdriver.c:2613,2649,2980,4606`). File access is governed by the device security descriptor and the filesystem's ACLs. The real defect is that the kernel trusts an unprivileged caller with a privileged-semantics flag, which misleads other users and admins. |
| SEC-VOL-001 | **Confirmed, also present in the Windows driver** | Low (robustness) | The C++ path (`Volume.cpp:209-211,391`, `VolumeLayout.cpp:129-137,178-186`) and `Driver/Ntvol.c:751-778` (which only checks `DiskLength != 0`) both lack a host-size check. The attack needs a header created and keyed by the attacker, and the victim must have its password. Writes stay inside the host object: a file grows, or the volume overwrites its own headers. A forged hidden-volume protection geometry comes from the same party that wrote both headers. |
| SEC-SCARD-001 | **Mechanism confirmed, downgraded** | Low | Keyfiles and tokens are resolved in the **application process**, not the root service (`Core/Unix/CoreServiceProxy.h:101-104` says so explicitly). Control of `PATH`/`LD_LIBRARY_PATH` already means same-user code execution. There is also a correctness bug: the first `ldconfig -p` line that matches may be the wrong-arch library on multiarch systems. |
| SEC-EMV-001 | **Confirmed (design property)** | Info / docs | Upstream feature. `doc/html/en/EMV Smart Cards.html` says it "will strengthen the security". It does not say the data is static and readable by any card reader or terminal. |
| SEC-MOUNT-001 | **Confirmed** | Low | The command line is burned only at exit (`Mount.c:813-819`). Reading another process's PEB needs `PROCESS_VM_READ`, so only the same user or an admin can read it. Process-creation auditing captures it at launch anyway. |
| SEC-MOUNT-002 | **Plausible** | Low (reliability) | The static pool is at `Keyfiles.c:233`. The main mount thread disables the window (`Mount.c:6223`), but hotkey and favorites threads (`Mount.c:10166,12553`) can still run alongside it. `FavoriteMountOnGoing` only serializes favorites against each other. A corrupted pool gives a wrong derived key, so header decryption fails with a spurious "incorrect password". It does not give a working wrong key. The global `VolumePassword`, `FirstKeyFile` and `mountOptions` are shared the same way, so the static buffer is the smallest part of the race. |
| SEC-TLV-001 | **Plausible** | Low | Recursion in `TLV_Parse_Sub` and `TLV_Find` (`TLVParser.cpp:189-231`) has no depth cap. Depth is bounded only by response size. |
| SEC-APDU-001 | **Confirmed, latent** | Nit | `success:` falls through into `clear()` (`CommandAPDU.cpp:112-116`). Nothing in the tree calls the vector constructor: every `EMVCard.cpp` call uses the field constructor. |
| SEC-VOL-002 | **Confirmed** | Nit | It is safe only because the pool sizes, 64 and 128, are multiples of 4 (`Volume/Keyfile.cpp:50-77`). |
| SEC-VOL-003 | **Confirmed** | Nit | Unaligned `*(uint64*)` read at `Volume.cpp:329` (system-encryption NTFS sniff only). |
| SEC-PROC-001 | **Confirmed mechanism, benign** | Info | `APPIMAGE` (`CoreService.cpp:1658-1666`) is read in the forked **user** child before sudo runs. sudo authenticates and enforces sudoers command rules on the path, and `ApplicationExecutablePath` is caller-supplied in any case. |
| SEC-SVC-001 | **Confirmed** | Low | Non-macOS `SetFileOwner` has no target restriction (`CoreService.cpp:1351-1363`). Its only legitimate caller is `VolumeCreator.cpp:241`, which sets a new container's owner to `getuid()`. Anyone able to talk to the root service already passed sudo. |
| SEC-DRV-002 | **Confirmed, worse than reported** | Low | `GetBootDriveVolumeProperties` (`DriveFilter.c:2478-2499`) also returns **`volumePim`** and the KDF iteration count to any local user. |
| SEC-DRV-003 | **Confirmed, do not "fix" as proposed** | Info | Any user can wipe the global cache (`Ntdriver.c:2564-2569`). Wiping helps security, and gating it would stop a non-admin from clearing cached secrets. Document it instead. |
| SEC-CMDLINE-001 | **Confirmed** | Low | The `_wcsdup` copies (`Cmdline.c:117`) are freed unwiped (`Mount.c:10958-10962`). The `CommandLineToArgvW` array is `LocalFree`d unwiped (`Cmdline.c:123`). |
| SEC-EMV-002 | **Confirmed** | Nit | `catch (...) {}` at `EMVCard.cpp:331-333` silently falls back to default AIDs. |
| SEC-KEY-004 | **Mechanism confirmed, impact refuted** | Info | `dat` is XORed into fresh ChaCha keystream (`chachaRng.c:44-52`). Uninitialized bytes XORed with a secret keystream are still unpredictable, and nothing leaks. The only real issue is reading uninitialized memory (UB, analyzer noise). |

**Not re-verified:** the survey's claims about commit `6c453627` and its §4 "non-findings". They are outside the scope of this pass.

**Survey statements to correct:** SEC-DRV-001's "read plaintext" claim; SEC-TMP-001's "classic-macOS only" claim; SEC-SCARD-001's "arbitrary code load" severity, which is same-privilege; SEC-KEY-004's "stack garbage into keystream" risk. Most findings are inherited from upstream VeraCrypt and are not regressions in this fork.

## 2. Repair plan

The fixes are grouped into broad mechanisms. Each one closes a class of bugs, not only the single line that was reported.

### Phase 1: trust boundaries (highest value)

**A. Trusted executable resolution.** Covers SEC-ELEV-001 and every root-service `Process::Execute("<relative>")`.
- In `Process::FindSystemBinary`, accept a candidate only if `ResolveTrustedSystemPath` passes and it is a regular file with an exec bit. That function is already at `Process.cpp:242`, but only under `TC_LINUX`; make it build on all Unix platforms.
- **Skip** untrusted candidates rather than failing on them, so a planted `/usr/local/bin/sudo` falls through to `/usr/bin/sudo`.
- On Linux, search system directories before `/usr/local` for privileged helpers (`sudo`, `doas`, `true`), matching the macOS ordering rationale in `Process.cpp:344-348`.
- Keep the NixOS branch as it is.
- Leave `IsExecutable` for non-security uses, or rename it so nobody reaches for it on privileged paths.
- *Tests:* a unit test with a temporary directory that is user-owned and group-writable, asserting it is rejected; a test that a root-owned `/usr/bin` candidate is accepted; a check that Linux, FreeBSD, OpenBSD and macOS still resolve `sudo`, `mount`, `losetup`, `dmsetup` and `hdiutil`.

**B. Root-owned, pinned mountpoints.** Covers SEC-TMP-001 and the 255-name DoS.
- Generalize the FUSE-T approach (`CreateFuseTAuxiliaryDirectory`, `CoreUnix.cpp:80-127`) into a cross-platform helper:
  - When `geteuid()==0`, ignore `TMPDIR` and `pam_tmpdir`. Use a trusted root-owned parent: `/run/veracrypt` on Linux (create it `0700`), `/var/run/veracrypt` on BSD, `/private/tmp` on macOS.
  - Create the directory with `mkdtemp`, `open(O_DIRECTORY|O_NOFOLLOW)`, and verify `st_uid==0` and the mode.
  - Record `st_dev`/`st_ino`. After `FuseService::Mount` returns, re-`lstat` the path and require that it is still not a symlink, that the parent's inode is unchanged, and that `st_dev` changed (the mount really landed there).
- Delete the `for (i = 1; …)` name-probing loop and its `fsPath.Delete()` of pre-existing directories.
- Check that the user-side code can still reach the auxiliary mount: it needs search access on the parent (FUSE-T grants an ACL; on Linux use `0711` or the user's gid).
- *Tests:* extend the existing lifecycle tests (`Tests/test_macos_gui_lifecycle.py`) with a Linux variant. Mount and unmount with `TMPDIR` set to a user-owned directory, and assert the auxiliary mount is under the trusted parent.

**C. Kernel IOCTL privilege table.** Covers SEC-DRV-001 and SEC-DRV-002, and prevents the next one.
- In `TC_IOCTL_MOUNT_VOLUME` (`Ntdriver.c:2934`), return `STATUS_ACCESS_DENIED` if `mount->SystemFavorite && !UserCanAccessDriveDevice()`. The only legitimate setter is ServiceMode (`Mount.c:11529`, `11996`), which runs as SYSTEM.
- In `GetBootDriveVolumeProperties`, zero `volumePim` and `pkcs5Iterations` unless `UserCanAccessDriveDevice()`. Keep the other fields, which the UI shows to non-admins.
- **Process:** add a comment table above `ProcessMainDeviceControlIrp` that classifies every IOCTL as *any user*, *owner-or-admin* or *admin-only*. Review the table on every new IOCTL, and review every caller-supplied struct field that changes access semantics.
- Leave `TC_IOCTL_WIPE_PASSWORD_CACHE` ungated (see SEC-DRV-003).
- *Tests:* in a VM, have a non-admin harness send `MOUNT_STRUCT` with `SystemFavorite=1` and expect a denial. A properties query as non-admin should return PIM 0.

### Phase 2: validation and secret hygiene

**D. One header-geometry validator.** Covers SEC-VOL-001 and future layout code.
- Add a `ValidateVolumeGeometry(hostSize, layout, header)` called right after a successful decrypt in `Volume::Open`, with the C equivalent in `ReadVolumeHeader` / `Ntvol.c` after line 778. For file- and device-hosted, non-drive-header layouts, check:
  - overflow-safe `offset + size <= hostSize - reservedTail`, where the tail is the backup header group for V2;
  - `offset >= TC_VOLUME_DATA_OFFSET` for V2 normal volumes;
  - `size % sectorSize == 0`;
  - `EncryptedAreaStart` and `EncryptedAreaLength` lie within the data area.
- Skip the check for `HasDriveHeader()` layouts, which `Volume.cpp:226-233` already covers, and when the platform reports `hostSize == 0`.
- *Compatibility risk:* a wrong rule here makes existing volumes unmountable. Test it against fixtures for legacy V1, V2 normal, hidden, outer with protection, device-hosted, sector sizes 512 and 4096, and volumes made by older versions (1.24, 1.25, 1.26).
- *Tests:* a C++ test that creates a volume, rewrites the header with `offset + size > host`, re-encrypts it, and expects a rejection.

**E. Windows command-line secret wipe.** Covers SEC-MOUNT-001 and SEC-CMDLINE-001.
- After `ExtractCommandLine` finishes, burn `GetCommandLineA()` and `GetCommandLineW()`. Burn each `lpszCommandLineArgs[i]` before `free` (`Mount.c:10958`). Burn `arguments[]` in `Win32CommandLine` before `LocalFree`.
- Apply the same change to `Format.c` / `Expand` if they accept `/password`.
- Add a docs line: `/password` is visible to same-user processes and to process-creation audit logs.

**F. Serialize mount operations.** Covers SEC-MOUNT-002 and the shared-global race.
- Make `keyPool` a local (stack) buffer. It is the cheap, local part of the fix.
- Add one process-wide mount lock (a `CRITICAL_SECTION` or `InterlockedCompareExchange` flag). Acquire it in `mountThreadFunction`, `mountFavoriteVolumeThreadFunction` and the command-line mount path. A second request waits or shows "a mount is already in progress". This covers the global `VolumePassword`, `FirstKeyFile` and `mountOptions` too.

**G. Root-service request allowlists.** Covers SEC-SVC-001.
- On all platforms in `SetFileOwnerRequest`:
  - require the target is not a symlink, using `lstat` and then `open(O_NOFOLLOW)` + `fchown`;
  - require it is a regular file or a block device;
  - require `Owner` equals the real uid (`GetRealUserId()`) of the requester.
- Keep the stricter macOS device-node rule.
- **Process:** every new `CoreServiceRequest` type gets an explicit validator next to its handler.

### Phase 3: hygiene (low cost, batch into one PR)

- **SEC-SCARD-001:** replace `popen("ldconfig")` with `dlopen("libpcsclite.so.1")`, the stable soname that the system loader resolves, falling back to `libpcsclite.so`. Remove the shell.
- **SEC-TLV-001:** add a depth parameter to `TLV_Parse_Sub` and `TLV_Find`, and throw `TLVException` above a fixed limit such as 32.
- **SEC-APDU-001:** `return;` after `m_parsedSuccessfully = true;`, or delete the unused vector constructor.
- **SEC-VOL-002:** add `static_assert` / `TC_ASSERT` that each pool size is a multiple of 4.
- **SEC-VOL-003:** `memcpy` into a `uint64`, as `VolumeHeader.cpp:385-387` does.
- **SEC-EMV-002:** catch `PCSCException` and `TLVException` explicitly and log them. Keep the default-AID fallback.
- **SEC-KEY-004:** `memset(dat, 0, sizeof dat)` before the callback.
- **SEC-EMV-001:** add a docs warning that EMV keyfile data is static and public to any reader/terminal, so it adds possession, not secrecy, and must not replace a strong password.
- **SEC-PROC-001, SEC-DRV-003:** no code change; add a comment recording why each is safe.

## 3. Order and effort

| Order | Item | Effort | Risk of regression |
|---|---|---|---|
| 1 | A: trusted binary resolution | S | Medium (distro paths); needs a per-OS smoke test |
| 2 | C: IOCTL gating + table | XS–S | Low; needs a signed test driver in a VM |
| 3 | B: pinned mountpoints | M | Medium–High (FUSE/permissions on every Unix); reuse the lifecycle harness |
| 4 | E + F: Windows secrets and mount lock | S | Low–Medium (UI responsiveness) |
| 5 | G: SetFileOwner allowlist | XS | Low |
| 6 | D: geometry validator | S code, M test | **High compatibility risk**; gate it on the fixture matrix |
| 7 | Phase 3 batch | XS each | Low |

Most findings are inherited from upstream VeraCrypt. Consider sending A, B, C and D upstream so the fork does not diverge on security-sensitive code.

## 4. Implementation status (2026-11-21, uncommitted working tree)

| Item | Status | Change |
|---|---|---|
| A: trusted binary lookup | **Done** | `Process::FindSystemBinary` accepts a candidate only if its whole path is root-owned and not group/world-writable, on every Unix platform; untrusted candidates are skipped. New `FindUserBinary` keeps the plain lookup for desktop helpers (terminals, `xdg-open`, file managers). |
| B: elevated FUSE mountpoint | **Done (contained form)** | Non-FUSE-T builds (Linux, BSD, macFUSE) allocate each auxiliary mountpoint atomically with `mkdtemp`. Elevated processes fall back to trusted `/tmp` when their temporary directory is user-controlled. Linux also reserves the slot and backing-file or device identity through the service lifetime and checks for surviving device-mapper mappings. |
| C: IOCTL gating | **Partly done** | `SystemFavorite` from non-admins is rejected. **SEC-DRV-002 was not changed:** the unelevated GUI reads the boot PIM and passes it to the elevated boot-sector writer (`Mount.c:13526-13551`), so masking it would corrupt boot configuration. It needs an elevated-read redesign first. |
| D: geometry | **Done (read-only fallback)** | C++ `Volume::Open` and `Ntvol.c`: a data area outside the host forces a read-only mount instead of refusing, so truncated containers stay recoverable. |
| E: Windows argv wipe | **Done** | `Win32CommandLine` wipes the `CommandLineToArgvW` copy. The new `FreeCommandLineArguments` wipes and frees the argument copies in VeraCrypt, Format and Expander. The process command line itself (PEB) is still wiped only at exit, because elevation relaunch reads it. |
| F: keyfile pool | **Done (pool only)** | `keyPool` is per call, locked and unlocked. The process-wide mount lock was not added (it needs GUI deadlock analysis). |
| G: SetFileOwner | **Done** | Non-macOS: the target is resolved once, must be a block/character device under `/dev`, and the resolved node is changed. |
| Phase 3 | **Done** | PC/SC loader tries `libpcsclite.so.1` first, then `/sbin/ldconfig` by absolute path (keeps OpenBSD working). TLV nesting capped at 32, and the `uint16` sub-length wrap fixed. APDU parse keeps its bytes and getters are bounds-checked. Keyfile pool size is checked. The NTFS sniff uses `memcpy`. EMV catch-all now lets reader errors through. RNG reseed buffer is zeroed. EMV docs warning added. |

Tests added or updated: `Tests/smartcard_parser_test.cpp` (new, in Linux CI), `Tests/macos_process_test.cpp`, `Tests/test_linux_privilege_helpers.py` (planted-helper cases), `Tests/linux_mount_read_only_test.cpp` (wrapper signature).
