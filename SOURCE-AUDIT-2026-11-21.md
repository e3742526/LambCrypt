# VeraCrypt source audit, 2026-11-21

> Historical LambCrypt fork record from before the rebrand. Commit, path and upstream references reflect that snapshot.

Report only: no source files were changed. Tree audited: `master` at `cb20f79e`, plus the uncommitted `Tests/test_fuset_dismount.py`.

This picks up the Codex session "Audit VeraCrypt codebase" (`01a1feae-aa77-7493-9399-2b57ab69e64e`), which OpenAI's filter stopped at 10:21. Codex left two unconfirmed leads. Both are confirmed below as F-01 and F-03. A separate write-up of those same two leads was supplied afterwards. Its details agreed with this report, and the one thing it added (the GUI wizard's overflow check, see F-01) has been checked against the source and merged in. Everything else was found by reading the code. Earlier reports in the repo (`SECURITY-REPAIR-PLAN.md` and the survey it answers) were not used as sources.

## Summary

| ID | Severity | Area | Finding |
|----|----------|------|---------|
| F-01 | Medium | Unix CLI / text UI | `--size` and the interactive size prompt wrap at 2^64, so a typo can create a volume of the wrong size |
| F-02 | Medium | Format SDK (Windows) | No PIM range check. A negative PIM produces a header protected by a single PBKDF2 round, and that volume cannot be opened with any valid PIM |
| F-03 | Low | Format SDK (Windows) | `dynamicFormat`/`fastCreateFile` with `quickFormat = FALSE` is rejected, although the header says these flags imply quick format |
| F-04 | Medium | Format SDK (Windows) | A password longer than 128 bytes crashes the calling process instead of returning `VCF_ERROR_PASSWORD_POLICY` |
| F-05 | Medium | Format SDK (Windows) | The SDK overwrites an existing file and formats an in-use device with no confirmation; the header does not say so |
| F-06 | Low | Format SDK (Windows) | `DllMain(DLL_PROCESS_DETACH)` waits for a thread to exit while holding the loader lock, so `FreeLibrary` without `Shutdown` can hang |
| F-07 | Low | Unix CLI | Integer options accept trailing characters (`--pim=1O00` becomes PIM 1) |
| F-08 | Low | Build scripts | When wxWidgets isn't next to the checkout, every build script falls back to `/tmp`, so another local user can supply the wxWidgets that gets linked in |
| F-09 | Low | CI | The wxWidgets tarball is downloaded without a checksum; `build-linux.yml` has no `permissions:` block |
| F-10 | Low | Linux `mount.veracrypt` | A `password=` fstab option ends up on the `veracrypt` command line, where any local user can read it |
| F-11 | Low (documented) | Windows driver | The password cache is shared by all users; any user can wipe it or read-and-clear the warning flags |
| F-12 | Nit | Unix text UI | The size prompt says `sizeG.sizeT` instead of `sizeG/sizeT` |

Severity is rated for VeraCrypt's threat model: a local attacker, data integrity and key strength. No finding allows remote code execution or bypasses volume encryption.

---

## F-01: Volume size wraps at 2^64 (Medium)

**Where:**
- [src/Main/CommandLineInterface.cpp:683](src/Main/CommandLineInterface.cpp#L683): `ArgSize = multiplier * StringConverter::ToUInt64 (...)`
- [src/Main/TextUserInterface.cpp:880](src/Main/TextUserInterface.cpp#L880): `options->Size *= multiplier;`
- Sector round-up at [TextUserInterface.cpp:817-819](src/Main/TextUserInterface.cpp#L817-L819) and [882-884](src/Main/TextUserInterface.cpp#L882-L884)

**What happens:** the number is parsed as a `uint64` and then multiplied by the unit (K/M/G/T) with no overflow check, so the result is taken mod 2^64. The min/max checks at lines 886-901 run after the wrap, so the wrapped value passes as long as it is in range.

Rounding up to the sector size can also wrap. `ToUInt64` rejects only `UINT64_MAX` itself, so `--size=18446744073709551614` (`UINT64_MAX - 1`) parses. Rounding it up to a multiple of the sector size then gives 0, just before the `while (options->Size == 0)` loop.

**The GUI already does this correctly.** The GUI wizard checks `val <= 0x7fffFFFFffffFFFFull / prefixMult` before it multiplies ([VolumeSizeWizardPage.cpp:119](src/Main/Forms/VolumeSizeWizardPage.cpp#L119)). That caps the size at 2^63-1, so its sector round-up can't wrap either. Only the console paths skip the check.

**Effect:**
- `--size=16777217T` creates a **1 TiB** volume.
- `--size=17592186044417M` creates a **1 MiB** volume.
- If the result is exactly 0, it is treated as "no size given": non-interactive mode fails with "missing argument", and interactive mode asks again.

The user gets a volume of a size they never asked for, with no error. A script that computes sizes and gets one wrong ends up with a silently tiny or huge container.

**Reproduce (harness on the real `StringConverter`):** the harness is `/private/tmp/claude-501/-Users-eric-Work-vscode-VeraCrypt/fd951dc9-9af3-42a1-bdce-5402af6882f8/scratchpad/audit/h/size_parse.cpp`. It copies the CLI suffix logic line for line and links the real `src/Platform` sources:

```sh
FILES=($(find src/Platform -maxdepth 2 -name '*.cpp' ! -name RequesterAccess.cpp))
clang++ -std=c++17 -w -DTC_UNIX -DTC_BSD -DTC_MACOSX -D_FILE_OFFSET_BITS=64 -Isrc -Isrc/Crypto \
  size_parse.cpp "${FILES[@]}" -framework CoreFoundation -o size_parse && ./size_parse
```

Observed output:

```
--size=10M -> 10485760 bytes (10 MiB)
--size=16777216T -> 0 bytes (0 MiB)
--size=16777217T -> 1099511627776 bytes (1048576 MiB)
--size=17592186044416M -> 0 bytes (0 MiB)
--size=17592186044417M -> 1048576 bytes (1 MiB)
--size=18014398509481985K -> 1024 bytes (0 MiB)
```

**Reproduce (real binary, Linux):**

```sh
veracrypt --text --non-interactive --create /tmp/t.hc --size=17592186044417M \
  --password=xxxxxxxxxxxxxxxxxxxx --encryption=AES --hash=SHA-512 --filesystem=none \
  --random-source=/dev/urandom
ls -l /tmp/t.hc     # about 1 MiB plus headers, not the 16 EiB that was typed
```

**Fix direction:** use the GUI's check (`value <= 0x7fffFFFFffffFFFF / multiplier`, otherwise reject) in both console paths, before both the multiply and the sector round-up. That keeps all three entry points to the same limit.

## F-02: Format SDK accepts any PIM (Medium)

**Where:** [src/FormatDLL/VeraCryptFormatSDK.cpp:201](src/FormatDLL/VeraCryptFormatSDK.cpp#L201) copies `options->pim` without a check. [VeraCryptFormatSDK.h:35](src/FormatDLL/VeraCryptFormatSDK.h#L35) defines `VC_MAX_PIM_VALUE`, but no code uses it. Every other entry point rejects `pim < 0 || pim > MAX_PIM_VALUE`, for example [Tcformat.c:9356](src/Format/Tcformat.c#L9356) and [CommandLineInterface.cpp:558](src/Main/CommandLineInterface.cpp#L558).

**What happens:** [get_pkcs5_iteration_count](src/Common/Pkcs5.c#L1285) only computes an iteration count for `pim >= 0` and returns **0** otherwise. [CreateVolumeHeaderInMemory](src/Common/Volumes.c#L1125) passes that 0 to `derive_key_*`, whose loop `for (c = 1; c < iterations; c++)` then does nothing. The header key comes from **one PBKDF2-HMAC round**. PIMs above 2,147,468 overflow `15000 + pim*1000` in signed arithmetic, which is undefined behavior. For Argon2, a large PIM makes `(pim-1)*32` overflow, the memory cost goes negative, and the cap is skipped.

**Effect:**
1. A volume created with `pim = -1` has its header protected by one PBKDF2 round instead of 500,000, which makes password guessing hundreds of thousands of times faster.
2. That volume cannot be mounted. Every VeraCrypt UI rejects negative PIMs, and PIM 0 means 500,000 rounds, so the header never decrypts. Data written by the integrator is effectively lost.
3. `pim = 4294968` wraps to **15,704** iterations, far fewer than the caller expects.

**Reproduce (the real function, compiled from `Pkcs5.c`):** the harness is `/private/tmp/claude-501/-Users-eric-Work-vscode-VeraCrypt/fd951dc9-9af3-42a1-bdce-5402af6882f8/scratchpad/audit/h/pim_iterations.c`. It extracts `get_argon2_params` and `get_pkcs5_iteration_count` verbatim with `awk` and compiles them with `-fwrapv`:

```
SHA-512  pim=0         iterations(int)=500000       as uint32=500000
SHA-512  pim=-1        iterations(int)=0            as uint32=0
SHA-512  pim=2147469   iterations(int)=-2147483296  as uint32=2147484000
SHA-512  pim=4294968   iterations(int)=15704        as uint32=15704
Argon2   pim=100000000 t_cost=99999982 m_cost_KiB=-260014080
```

**Reproduce (Windows, SDK):** call `VeraCryptFormat` with `pim = -1`, `hashAlgorithm = L"SHA-512"`, a file container and a 20-character password. The call returns `VCF_SUCCESS`. Then try mounting the container with `VeraCrypt.exe /v file.hc /p <password> /q`. It fails with "incorrect password", and no PIM value works.

**Fix direction:** in `CreateVolumeInternal`, return `VCF_ERROR_INVALID_PARAMETER` unless `0 <= pim <= VC_MAX_PIM_VALUE`. As defense in depth, `get_pkcs5_iteration_count` should treat `pim < 0` as fatal rather than returning 0.

## F-03: Format SDK rejects the flag combination its header documents (Low)

**Where:** the header comments at [VeraCryptFormatSDK.h:81-85](src/FormatDLL/VeraCryptFormatSDK.h#L81-L85) say "Implies quickFormat=TRUE". [VeraCryptFormatSDK.cpp:161](src/FormatDLL/VeraCryptFormatSDK.cpp#L161) returns `VCF_ERROR_INVALID_PARAMETER` when `dynamicFormat || fastCreateFile` is set and `quickFormat == FALSE`. Because of that early return, the code that implements the implication at line 207 (`if(dynamicFormat || fastCreateFile) quickFormat = TRUE;`) can never change anything.

**Reproduce:** call `VeraCryptFormat` with `isDevice=FALSE`, `dynamicFormat=TRUE` and `quickFormat=FALSE`. It returns `2` (`VCF_ERROR_INVALID_PARAMETER`) instead of creating a sparse container.

**Fix direction:** decide on one contract. Either delete line 161, or change the header comments to "requires quickFormat=TRUE" and delete line 207.

## F-04: Format SDK crashes on a long password (Medium)

**Where:** [VeraCryptFormatSDK.cpp:211-216](src/FormatDLL/VeraCryptFormatSDK.cpp#L211-L216). [CheckPasswordLength](src/Common/Password.c#L137) checks only the lower bound and PIM warnings, never the maximum. The next statement is `strcpy_s(volumePassword.Text, sizeof(volumePassword.Text) /* 129 */, options->password)`.

**What happens:** if the password is 129 bytes or longer, `strcpy_s` calls the CRT invalid-parameter handler. By default that terminates the process (`STATUS_INVALID_CRT_PARAMETER`). The header promises `VCF_ERROR_PASSWORD_POLICY` for "Password is too long". Since a DLL can't install a handler on the host's behalf, the host process dies.

**Reproduce (Windows):** call `VeraCryptFormat_Initialize()`, then `VeraCryptFormat(&o)` with `o.password` set to 200 bytes of `'a'` and an otherwise valid file container. The host process exits immediately with code `0xC0000417` instead of the call returning `7`.

**Fix direction:** `if (strlen(options->password) > MAX_PASSWORD) return VCF_ERROR_PASSWORD_POLICY;` before the copy.

## F-05: Format SDK overwrites existing files and formats in-use devices (Medium)

**Where:**
- [VeraCryptFormatSDK.cpp:302](src/FormatDLL/VeraCryptFormatSDK.cpp#L302) sets `volParams.bForceOperation = TRUE`.
- [Format.c:298](src/Common/Format.c#L298): with that flag set, the "device in use" confirmation is skipped.
- [Format.c:377-379](src/Common/Format.c#L377-L379) opens file containers with `CREATE_ALWAYS`.
- [Format.c:779-784](src/Common/Format.c#L779-L784): if formatting then fails, the file is truncated to 0.

**What happens:** if `path` names an existing file, it is truncated and replaced. If `isDevice` is set and the device can't be opened exclusively (it has a mounted filesystem), it is reopened in shared mode and formatted anyway. The header ([VeraCryptFormatSDK.h:47-51](src/FormatDLL/VeraCryptFormatSDK.h#L47-L51)) mentions neither behavior, and the SDK has no "fail if exists" option. A wrong path from an integrator silently destroys data. If the format fails partway, even the original file is gone.

**Reproduce (Windows):** create `C:\t\keep.txt` with content. Call `VeraCryptFormat` with `path=L"C:\\t\\keep.txt"`, `size=10 MiB`, a valid password and `filesystem=L"None"`. It returns success, and `keep.txt` is now a 10 MiB VeraCrypt container. To see the failure case, put the content back and repeat with `quickFormat=FALSE` and a `progressCallback` that returns `FALSE` on its first call. Format.c treats that as a failure and truncates the file, so `keep.txt` ends up 0 bytes and the original content is gone.

**Fix direction:** document the behavior and add a `failIfExists`/`allowInUseDevice` option, or default to `CREATE_NEW` and drop `bForceOperation`.

## F-06: SDK `DllMain` shuts down under the loader lock (Low)

**Where:** [VeraCryptFormatSDK.cpp:396-400](src/FormatDLL/VeraCryptFormatSDK.cpp#L396-L400) calls `VeraCryptFormat_Shutdown()`. That takes a `std::mutex` and calls `RandStop(TRUE)`, which runs `WaitForSingleObject(PeriodicFastPollThreadHandle, INFINITE)` ([Random.c:194-195](src/Common/Random.c#L194-L195)).

**What happens:** on `FreeLibrary` (`lpvReserved == NULL`), the poll thread still has to exit, and thread exit needs the loader lock that `DllMain` is holding. The two wait on each other forever. At process exit the other threads are already gone, so the wait returns and nothing hangs.

**Reproduce (Windows):** `LoadLibrary("VeraCryptFormat.dll")`, then `VeraCryptFormat_Initialize()`, then `FreeLibrary(h)` without calling `VeraCryptFormat_Shutdown`. Expected result: `FreeLibrary` never returns, with the main thread in `WaitForSingleObject` inside the loader's `DllMain` call and the poll thread blocked waiting for the loader lock as it exits. This follows from the code and the documented loader-lock rules but has not been run.

**Fix direction:** don't do cleanup work in `DLL_PROCESS_DETACH`. Document that callers must call `Shutdown`, and at most signal the thread without waiting for it.

## F-07: Integer options ignore trailing characters (Low)

**Where:** `StringConverter::ToInt32` / `ToUInt32` / `ToUInt64` in [src/Platform/StringConverter.cpp:274-332](src/Platform/StringConverter.cpp#L274-L332) parse with `ss >> n` and check only `fail()`, never whether all input was consumed. `--pim`, `--new-pim`, `--protection-pim`, `--slot` and the interactive PIM and selection prompts all go through these functions.

**Effect:** the harness from F-01 shows that `"12abc"`, `"1 2"` and `"485;rm"` parse as 12, 1 and 485. A typed `--pim=1O00` (letter O) creates or opens with **PIM 1** (16,000 iterations) instead of failing. The only safeguard is the "short password with small PIM" rule at [TextUserInterface.cpp:45-48](src/Main/TextUserInterface.cpp#L45-L48), which doesn't apply to passwords of 20 characters or more.

**Reproduce:**

```sh
veracrypt -t --non-interactive --create /tmp/p.hc --size=5M --pim=1O00 \
  --password=aaaaaaaaaaaaaaaaaaaaaaaa --encryption=AES --hash=SHA-512 \
  --filesystem=none --random-source=/dev/urandom
veracrypt -t --non-interactive --pim=1 --password=aaaaaaaaaaaaaaaaaaaaaaaa \
  --filesystem=none /tmp/p.hc   # mounts with PIM 1
```

**Fix direction:** after `ss >> n`, require `(ss >> std::ws).eof()`.

## F-08: Build scripts fall back to wxWidgets in `/tmp` (Low)

**Where:** `export PARENTDIR="/tmp"` appears in seven scripts:
- [build_veracrypt_macosx.sh:128](https://github.com/e3742526/LambCrypt/blob/e708993988fd7bba2f7b36cac93a6e399d08e006/src/Build/build_veracrypt_macosx.sh#L128)
- [build_veracrypt_linux.sh:30](https://github.com/e3742526/LambCrypt/blob/e708993988fd7bba2f7b36cac93a6e399d08e006/src/Build/build_veracrypt_linux.sh#L30)
- [build_veracrypt_linux_no_sse2.sh:30](https://github.com/e3742526/LambCrypt/blob/e708993988fd7bba2f7b36cac93a6e399d08e006/src/Build/build_veracrypt_linux_no_sse2.sh#L30)
- [build_veracrypt_freebsd.sh:25](https://github.com/e3742526/LambCrypt/blob/e708993988fd7bba2f7b36cac93a6e399d08e006/src/Build/build_veracrypt_freebsd.sh#L25)
- [build_cmake_deb.sh:51](src/Build/build_cmake_deb.sh#L51)
- [build_cmake_rpm.sh:47](src/Build/build_cmake_rpm.sh#L47)
- [build_cmake_opensuse.sh:47](src/Build/build_cmake_opensuse.sh#L47)

Related: [build_cmake_deb.sh:179](src/Build/build_cmake_deb.sh#L179) runs `rm -rf $PARENTDIR/VeraCrypt_Packaging` unquoted, and packaging output then goes to `/tmp/VeraCrypt_*`.

**What happens:** if `wxBuildConsole` or `wxWidgets-<ver>` isn't next to the checkout, the scripts use `/tmp/wxBuildConsole` or `/tmp/wxWidgets-<ver>` if either exists. Any local user can create those. On a shared build host, the planted wxWidgets is compiled into and statically linked with the released binary. The packaging staging directory in `/tmp` is open to the same race.

**Reproduce:** as user B, `mkdir /tmp/wxBuildConsole` and plant a modified static library. As user A, run `src/Build/build_veracrypt_linux.sh` from a checkout with no sibling wx directory. The script prints `Switched to PARENTDIR: /tmp, wxBuildConsole is present in /tmp.` and links B's code.

**Fix direction:** require an explicit `WX_ROOT`/`WX_BUILD_DIR`, or use a private `mktemp -d`, and verify the wx tarball's SHA-256 (the OpenWrt script already does this).

## F-09: CI integrity and least privilege (Low)

- [build-linux.yml:151](.github/workflows/build-linux.yml#L151) and [build-linux-big-endian.yml:111](.github/workflows/build-linux-big-endian.yml#L111) download the wxWidgets release tarball with `wget` and don't check a checksum. A tampered release asset, or a poisoned `actions/cache` entry restored on a later run, would be built into the test binaries.
- `build-linux.yml` has no top-level `permissions:` block, so the `GITHUB_TOKEN` gets the repository default. That can be read-write on older repos. The other workflows declare `contents: read`. The cache-cleanup step needs only `actions: write`.
- Actions are pinned to tags (`@v4`, `@v8`), not commit SHAs.

**Reproduce:** read the workflows. To demonstrate, swap the tarball URL for a modified archive in a fork. The job builds it without complaint.

## F-10: An fstab `password=` option is visible to other users (Low)

**Where:** [src/Setup/Linux/mount.veracrypt:66](src/Setup/Linux/mount.veracrypt#L66) turns `password=` into `--password=...` on the `exec /usr/bin/veracrypt` command line.

**What happens:** while that `veracrypt` process runs, the password is in its argv, which other local users can read through `ps -ef` or `/proc/<pid>/cmdline` (unless `/proc` is mounted with `hidepid=`). `/etc/fstab` itself is normally world-readable (0644), so the option exposes the password at rest as well.

**Reproduce (Linux):** add `/dev/sdX1 /mnt/v veracrypt password=secret123,fs=none,noauto 0 0` to fstab. Run `sudo mount /mnt/v` and, in another shell as an unprivileged user, `while :; do ps -eo args | grep -- --password; done`. The output shows `--password=secret123`.

**Fix direction:** pass the password on stdin (`--stdin`) or read it from a root-only file. Document that `password=` is unsafe.

## F-11: The Windows password cache is shared by all users (Low, documented)

**Where:**
- The cache is a single global array (`CachedPasswords`) in [src/Common/Cache.c](src/Common/Cache.c), with no owner SID. `ReadVolumeHeaderWCacheWithAbort` tries every cached entry whenever the supplied password is empty.
- [Ntdriver.c:2564-2569](src/Driver/Ntdriver.c#L2564-L2569): `TC_IOCTL_WIPE_PASSWORD_CACHE` has no access check.
- [Ntdriver.c:3096-3107](src/Driver/Ntdriver.c#L3096-L3107): `TC_IOCTL_GET_WARNING_FLAGS` reads and then clears the flags, also with no access check.

**Effect:**
- User B can mount any container B can read, such as one on a shared or FAT-formatted USB drive, using passwords that user A cached.
- User B can wipe A's cache, which is a nuisance.
- User B can consume the "system favorite dirty" and "paging file prevented" warnings before an administrator's GUI sees them.

The first point is documented in [doc/html/en/Issues and Limitations.html](doc/html/en/Issues%20and%20Limitations.html) ("the password cache is shared by all logged on users"). The other two aren't.

**Reproduce (Windows, two accounts):** as A, mount `E:\shared.hc` with "Cache passwords in driver memory" on, then dismount. As B, run `VeraCrypt.exe /v E:\shared.hc /l X /q`; no password is given, and it mounts from the cache. Next, as B, call `DeviceIoControl(\\.\VeraCrypt, TC_IOCTL_GET_WARNING_FLAGS)` twice. The second call returns zeros.

## F-12: Typo in the size prompt (Nit)

[TextUserInterface.cpp:827](src/Main/TextUserInterface.cpp#L827) says `sizeK/size[M]/sizeG.sizeT/max`; it should be `sizeG/sizeT`.

---

## Checked and found sound

- **Unix header parsing** ([VolumeHeader.cpp:266-382](src/Volume/VolumeHeader.cpp#L266-L382)): every read is bounds-checked, the sector size is range-checked, and the CRC is checked before the key area is used.
- **Windows driver root-device IOCTLs** ([Ntdriver.c:2196-3110](src/Driver/Ntdriver.c#L2196-L3110)):
  - Every buffer-carrying IOCTL calls `ValidateIOBufferSize`.
  - Mount, unmount and list respect `IsVolumeAccessibleByCurrentUser`.
  - `SystemFavorite` mounts, portable mode, boot-encryption setup and abort, decoy wipe, the boot-sector write and emergency key clear all require `UserCanAccessDriveDevice` or a system thread.
  - Aborting a pending mount is limited to the user who started it.
  - F-11 lists the two exceptions.
- **Unix mount path** ([CoreUnix.cpp:1277-1370](src/Core/Unix/CoreUnix.cpp#L1277-L1370)): mount points are validated, a read-only fallback runs on `EROFS`/`EACCES`/`EPERM`, a device/volume sector-size mismatch is refused, and the FUSE-T/legacy auxiliary mountpoints are created privately.
- **Unix argument parsing:** PIM range checks are in the right order relative to `--system`. `--stdin` passwords are read into a fixed, wiped buffer, and an overlong password is rejected rather than truncated ([UserInterface.cpp:1255-1295](src/Main/UserInterface.cpp#L1255-L1295)).
- **Text-UI mount failures:** a missing path or an abort sets exit code 1 ([UserInterface.cpp:1380-1384](src/Main/UserInterface.cpp#L1380-L1384)).
- **Unix keyfiles:** processing is capped at `MaxProcessedLength`, so `/dev/zero` or a huge file can't hang it.
- **Linux `mount.veracrypt`:** apart from F-10, arguments are positional-safe, `set -f` stops glob expansion, and namespaces (`-N`) are refused.
- **Volume expansion** (`ExpandVolume.c`): the backup header is written before the primary, so an interruption leaves the old primary header valid.

## Coverage and limits

**Reviewed:**
- Unix CLI and text UI: size, PIM, password, mount and create paths
- `StringConverter`
- `VolumeHeader`
- The `CoreUnix` mount path
- Unix keyfiles
- The whole Format SDK (`.h`/`.cpp`), plus the `Format.c` file/device open and error paths it reaches
- `ExpandVolume.c`, from the header rewrite onward
- `Pkcs5.c` iteration and Argon2 parameter derivation
- `Volumes.c` header creation
- Windows driver root IOCTL dispatch, the cache and the boot-filter access checks
- `Random.c` `RandStop`
- `mount.veracrypt`
- All `src/Build/*.sh` wx fallbacks and the macOS build script
- All GitHub workflows

**Not reviewed (candidates for a next pass):**
- Boot loader (`src/Boot`, DCS)
- Setup and installer code (`src/Setup`, `SetupDLL`)
- PKCS#11 and the EMV token code paths beyond the interfaces
- The volume filter and encrypted I/O queue internals
- `DriveFilter.c` beyond its access checks
- The wxWidgets GUI forms
- Crypto primitive implementations
- Language and translation files

**Not run:**
- **Full Unix build.** wxWidgets 3.2.10's base library fails to compile against the installed macOS SDK (`NSWorkspaceLaunchAsync` is undeclared in `utils_base.mm`); Codex hit the same wall. F-01, F-02 and F-07 were reproduced with harnesses built from the real source instead. The CLI command lines above are what a Linux build would run, but they were not executed.
- **Windows.** Nothing was compiled or run on Windows. F-03 through F-06 and F-11 come from reading the code, and their Windows procedures are untested.

---

## Repair status (2026-11-21, uncommitted)

| ID | Status | Change |
|----|--------|--------|
| F-01 | Fixed | [CommandLineInterface.cpp](src/Main/CommandLineInterface.cpp) and [TextUserInterface.cpp](src/Main/TextUserInterface.cpp) reject a size above `TC_MAX_VOLUME_SIZE_GENERAL / multiplier`, the same limit the GUI wizard uses. The text UI also refuses to round up a size above that limit. Sizes of 2^63 bytes or more are now refused instead of wrapping. |
| F-02 | Fixed | The SDK returns `VCF_ERROR_INVALID_PARAMETER` unless `0 <= pim <= VC_MAX_PIM_VALUE`. Defense in depth: [Pkcs5.c](src/Common/Pkcs5.c) `get_argon2_params` caps the memory cost before multiplying. It gives identical results for every PIM from -5 to 2,147,468 (checked exhaustively against the old code). |
| F-03 | Fixed | The SDK now does what its header says: `dynamicFormat`/`fastCreateFile` imply `quickFormat` instead of being rejected without it. |
| F-04 | Fixed | A password longer than `MAX_PASSWORD` (128) bytes returns `VCF_ERROR_PASSWORD_POLICY` before `strcpy_s`. |
| F-05 | Fixed (**behavior change**) | The SDK refuses a container path that already exists, returning the new code `VCF_ERROR_ALREADY_EXISTS` (24). It deletes the new file if formatting fails, and no longer formats a device it can't open exclusively (`bForceOperation = FALSE`, so it fails with `VCF_ERROR_GENERIC`). The header documents all three. Integrators that relied on overwriting must delete the file first. |
| F-06 | Fixed | While initialized, the SDK holds a reference to its own DLL, so `FreeLibrary` without `Shutdown` no longer reaches `DllMain` cleanup. `DllMain` cleans up only at process exit and only if it can take the mutex without blocking. `Shutdown` releases the reference. |
| F-07 | Fixed | New `StringConverter::IsDecimalNumber`, now required by `--pim`, `--new-pim`, `--protection-pim`, the interactive PIM, selection and size prompts. Config-file parsing still uses the lenient conversions. |
| F-08 | Fixed | New [src/Build/Tools/private_tmp_dir.sh](src/Build/Tools/private_tmp_dir.sh), sourced by all seven build scripts. When `PARENTDIR` falls back to `/tmp`, wx sources must be owned by the build user and not group- or world-writable, and the build and packaging directories are created by the script (or must already be owned that way). The `rm -rf` of `VeraCrypt_Packaging` is quoted, and the directory is re-secured afterwards. |
| F-09 | Fixed (partly) | Both Linux workflows check the wxWidgets tarball against a pinned SHA-256, `0ad86a3a…6b51`. That file's SHA-1 matches the one in the official 3.2.5 release notes. `build-linux.yml` declares `permissions: contents: read, actions: write`. **Not done:** pinning actions to commit SHAs. |
| F-10 | Fixed | [mount.lambcrypt](src/Setup/Linux/mount.lambcrypt) passes `password=` on standard input (`--stdin`, written by the `printf` builtin). The header comment recommends keyfiles over passwords in fstab. |
| F-11 | Documented only | [Multi-User Environment.html](doc/html/en/Multi-User%20Environment.html) now says that other users can mount with a cached password and wipe the cache, and advises against caching on shared computers. The driver is unchanged: making the cache per-user changes the IOCTL contract, and restricting the wipe would stop standard users from wiping their own cached passwords. |
| F-12 | Fixed | The prompt now reads `sizeK/size[M]/sizeG/sizeT/max`. Translations keyed on the old string fall back to English. |

### Verification

**Run on macOS:**
- `-fsyntax-only` against the configured wxWidgets 3.2.10 headers:
  - `CommandLineInterface.cpp` and `StringConverter.cpp` pass as macOS (FUSE-T), Linux, FreeBSD and OpenBSD.
  - `TextUserInterface.cpp` (`TC_NO_GUI`) passes as macOS, Linux, FreeBSD and OpenBSD. The Linux/BSD checks used macOS PC/SC headers and stub `reader.h`/`sys/prctl.h`.
  - `Pkcs5.c` passes as macOS.
- A parsing harness linked against the patched `src/Platform` passed all 18 cases:
  - **Sizes refused:** 2^63 and above, `16777217T`, `17592186044417M`, `UINT64_MAX - 1`.
  - **Sizes accepted:** `10M`, `8388607T`, 2^63-1.
  - **PIM values refused:** `1O00`, `12abc`, `1 2`, `-5`, empty, `+5`.
  - **PIM values accepted:** `0`, `485`, `2147468`.
- Argon2 parameter comparison, old against new: 0 differences over every PIM from -5 to 2,147,468.
- `mount.veracrypt` was run against a stub `veracrypt`:
  - The password arrives on stdin and is absent from argv, including one with spaces and `%s`.
  - An empty `password=` sends an empty line.
  - The keyfile-only form doesn't use stdin.
  - The exit status is passed through.
- `private_tmp_dir.sh` under `sh` and `bash`:
  - Creates a missing directory with mode 755.
  - Rejects group-writable, world-writable, symlinked and foreign-owned (`/usr`) directories.
  - Does nothing when `PARENTDIR` isn't `/tmp`.
- All seven build scripts pass `sh -n` (the macOS script `bash -n`), and both workflows parse as YAML.
- `Tests/test_macos_discovery.py` passes.

**Not run:**
- **Windows.** Nothing in the SDK (F-02 to F-06) was compiled or run.
- **Full Unix build.** wxWidgets doesn't build against this SDK, so there was no full build and no end-to-end `veracrypt --create`.
- **Tests that need build archives.** `Tests/test_backup_header_retry.py` and the other tests that need `Core.a`/`Volume.a` couldn't run.
- **Real fstab mount.** `Tests/test_mount_helper.py` (Linux, root, real mount) wasn't run.
- **CI.** The workflows haven't run in GitHub Actions.
