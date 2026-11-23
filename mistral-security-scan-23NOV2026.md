# VeraCrypt (LambCrypt) — Full-Repository Security Scan

**Report ID:** `mistral-security-scan-23NOV2026`
**Date:** 23 November 2026
**Repository:** `/Users/eric/Work/vscode/VeraCrypt` at HEAD `954a10b9`
**Scope:** the **entire** codebase — Windows kernel driver, boot chain, Windows GUI trio + COM elevation, Linux/macOS elevation & cross-platform core, crypto layer, smartcard/token surfaces, vendored libraries' usage sites, installer/parser surfaces. Not limited to FSKit; FSKit/Fuse interfaces were re-checked only as they touch the audited surfaces.
**Method:** 6 independent read-only security auditors, each running the `audit-security` catalog skill (SEC taxonomy); the kernel-driver, Windows-GUI and cross-platform agents additionally ran `audit-security-vuln-harness` (EX-1..EX-4 exploitability ladder — rung-3 survivors only; rejects have their failing rung named).
**Discipline:** static code scan only. No builds, no runs, no tests, no fuzzing, **no playtest**. No web/CVE lookups (version evidence is from the tree only). No prior audit reports or bug logs were used as evidence (BUGLOG.md, FSKIT-MIGRATION.md, SECURITY-REPAIR-PLAN.md, SOURCE-AUDIT-2026-11-21.md, mistral-audit-all-23NOV2026.md, mistral-auditskill-analysis-23NOV2026.md, Tests/README-macos-lifecycle.md excluded). Headline evidence was chair-verified verbatim against the source (marked ✓).

---

## 0. Executive Summary

This scan deliberately targeted the surfaces the earlier audit could only grep-sample, and it found **material defects in every one of them**. Four results stand above the rest:

1. **`RemoveDeviceWriteProtection` drops an elevated `.cmd` script in `%TEMP%` under a fixed, predictable name and executes it via `ShellExecute "runas"`** (SEC-COM-001, HIGH). A same-user non-elevated process that stalks `%TEMP%` can swap in attacker content before the elevation click → local admin code execution with a UAC prompt the user already expects. Verified verbatim (✓ `Dlgcode.c:13993-13994, 14023`).
2. **The Linux elevation path follows `APPIMAGE`/`APPDIR` environment variables to choose the binary that `sudo` executes as root** (SEC-CORE-001, HIGH). The only guard is a spawnable-prefix check (`/tmp/.mount_` + a 6-char lowercase name fragment) against world-writable `/tmp` — a user-controlled layout makes the attacker's own path the elevation target while the real sudo prompt (suppressed text) and real password are collected. Verified (✓ `CoreService.cpp:1689`, `Process.cpp:713-716`).
3. **A wild pointer write in the elevated COM server** (SEC-BOOT-001, MED): `WriteEfiBootSectorUserConfig` double-dereferences a `BSTR`, turning the first UTF-16 code unit of the message into a `char*` it then writes through — an elevated-process wild write + guaranteed access violation whenever the feature is actually used (verified ✓ `BaseCom.cpp:521-523`; both FormatCom and MainCom servers expose it).
4. **A kernel NULL-deref reachable from an unprivileged status ioctl** (SEC-DRV-001, MED): a failed header reopen NULLs `HeaderCryptoInfo` but leaves `DriveMounted` true, and the unprivileged `GET_BOOT_ENCRYPTION_STATUS` poll then reads through the NULL pointer → bugcheck on demand after one wrong admin password (verified ✓ `DriveFilter.c:1796-1799, 2550`).

Beyond these: TOCTOU on a fixed-name `%TEMP%` INF consumed by the elevated registry installer (SEC-COM-002), portable-mode driver load without signature verification of the `.sys` beside the EXE (SEC-COM-003), rescue-disk config TOCTOU feeding the pre-boot config (SEC-REG-001), a FAT full-format integer overflow that over-writes/past the data area on >2 TiB FAT volumes (SEC-COMM-003), a non-NUL-terminated global installation path under MSI elevation (SEC-COMM-004), and a set of crypto/KDF precision defects (PIM overflow in the C++ boot KDF path, abort-reported-as-success in KDF wrappers, unbounded RDRAND retry, unbounded PIN retry).

The verified-strength inventory is proportionally large: the Windows boot handoff validation, kernel ioctl dispatch hygiene (all `METHOD_BUFFERED` + length validation), header deserialization bounds, Argon2 parameter provenance (PIM-only, never header-derived), key-wipe discipline, TLV/APDU bounds, and the per-instance-UAC COM elevation design all held up under adversarial reading — most findings live in *elevated helper/plumbing* code, not in the core crypto path.

---

## 1. Coverage & How to Reproduce

| Auditor | Surface (files read in depth) | LOC |
|---|---|---|
| sec-windriver | `src/Driver` Windows kernel: Ntdriver.c dispatch (all ~95 ioctl cases), DriveFilter.c (boot handoff, reopen, status), VolumeFilter.c, DumpFilter.c, EncryptedIoQueue.c, Ntvol.c, Apidrvr.h | ~7,400 |
| sec-boot | `src/Boot/Windows` (all 10 files incl. BootSector.asm, Decompressor.c), `Volumes.c` boot header path, `Pkcs5.c` boot derives, `BootEncryption.cpp` (~half of 8,220 L), `BaseCom.cpp` full, rescue ISO/ZIP builders | ~11,000 |
| sec-wingui | `Dlgcode.c` (17.1k), `Mount.c` (14.4k), `Tcformat.c` + `InPlace.c` (~13.2k), COM surfaces (MainCom/FormatCom/COMReg/ComSetup), Registry.c, language/XML load | ~8,000 deep + sweeps |
| sec-crypto | `src/Volume` KDF/XTS/header (5,400), `src/Common` Pkcs5.c/Volumes.c/TLV/EMV/APDU/SecurityToken (6,300), `src/Crypto` wolfCrypt glue/rdrand/Argon2 (1,200), RNG | ~12,900 |
| sec-vendored | libzip/lzma/zlib usage sites + versions, Wipe/Cmdline/Language/Xml/Fat.c/FatFormatter, InPlace.c geometry, FormatDLL/SetupDLL MSI custom actions, SecurityToken PKCS#11 | ~6,500 |
| sec-crossplat | ExpandVolume.c full, CommandLineInterface/TextUserInterface/Xml/UserPreferences, Platform (Serializer/Pipes/Process/Files), CoreService elevation loop, second-opinion on Fuse/FSKit interfaces | ~8,000 |

Reproduction: same catalog load path as before (`search_skills` → triage → `load_skill` for `audit-security` + optionally `audit-security-vuln-harness`), then per-area systematic sweeps: enumerate every ioctl/parser/elevation entry point, verify buffer bounds / overflow / sign / TOCTOU / privileged-transition at each, apply the EX ladder, record strengths. Representative greps: `TC_IOCTL/IOCTL` handler census; `ShellExecute|runas|_wfopen|GetTempPath`; `wcsncpy|wsprintf|wcsncmp`; `getenv\(` on elevation paths; `int .* = pim|<<= 16`; `zip_fread|sb.size`; `MmProbeAndLockPages|MDL_PARTIAL`; `bits(|incnt|inlen` in boot decompressor. Static ceiling: code-property facts Confirmed; runtime manifestations capped Likely/Plausible.

---

## 2. Findings

### 2.1 High severity

**SEC-COM-001 — Elevated script drop + `ShellExecute "runas"` in `%TEMP%` at fixed names → local privilege-elevation race** *(Windows GUI; EX-1..EX-4 pass; runtime winnability not statically provable → manifestation Likely)*
- Evidence (✓): `src/Common/Dlgcode.c:13993-13994` — `StringCbPrintfW (cmdBatch, ..., L"%s\\VeraCrypt_Write_Protection_Removal.cmd", temp); ... .diskpart` ; `:14023` — `ShellExecute (NULL, (!IsAdmin() && IsUacSupported()) ? L"runas" : L"open", cmdBatch, ...)`. Files are written with plain `_wfopen("w")`, closed, then launched by path.
- Mechanism: the standard-user token can already write `%TEMP%`. A watcher process replaces the `.cmd` (or the `.diskpart` it invokes) between `fclose` and the elevation launch; the user approves a UAC prompt they expect in this flow; attacker-controlled script runs as admin. No ACL hardening, no unique name, no reparse-point refusal, no content check before launch.
- Fix: perform the operation via the existing elevated COM server in-process; otherwise unique temp names in a private ACL'd directory + verify-before-execute (or `runas diskpart /s <verified-script>` directly).

**SEC-CORE-001 — AppImage env-determined elevation target on Linux** *(cross-platform; EX-1/2/4 pass, EX-3 guard spoofable)*
- Evidence (✓): `src/Core/Unix/CoreService.cpp:1673-1693` — elevation target taken from `request.ApplicationExecutablePath` / `FindSystemBinary`, then under `TC_LINUX`: `const char* appImageEnv = getenv("APPIMAGE"); if (Process::IsRunningUnderAppImage(appPath) && appImageEnv != NULL) appPath = appImageEnv;` then `execvp("sudo", { "-S", "-p", "", appPath, "--core-service", ...})`. The guard `IsRunningUnderAppImage` (`src/Platform/Unix/Process.cpp:707-740`) only checks that the current executable path starts with `$APPDIR` and that `$APPDIR` starts with `/tmp/.mount_` + 6 chars matching `"veracr"` case-insensitively.
- Mechanism: the launching user controls both env vars and can lay out a fake AppImage tree under `/tmp/.mount_veracrX`. On the next elevation, sudo receives the attacker's path as the target while the genuine admin password is typed into the genuine (text-suppressed) sudo prompt. Practical preconditions: same-user malware + one credential entry; the classic sudoers-path-constrained bypass remains blocked (sub-variant rejected at EX ladder).
- Fix: derive the elevation target only from `/proc/self/exe` (or verify `APPIMAGE` against the process's actual mount), never from environment.

### 2.2 Medium severity

**SEC-BOOT-001 — BSTR double-dereference in elevated COM server (`WriteEfiBootSectorUserConfig`)** *(✓ verified)*
- Evidence: `src/Common/BaseCom.cpp:521-523` — `DWORD maxSize = ((DWORD *) ((BYTE *) customUserMessage))[-1]; char* msg = (char*) *customUserMessage; if (maxSize > 0) msg[maxSize-1] = 0;`
- Mechanism: `customUserMessage` **is** the BSTR (the idl parameter type). `*customUserMessage` yields the first UTF-16 code unit, used as a `char*` and written through (`msg[maxSize-1] = 0`), then processed as the message. For any non-empty message: one wild low-address write inside an elevated process + access violation, converted to `ERROR_EXCEPTION_INSERVICE` — the EFI boot-sector user-config save silently fails through UAC elevation. Exposed by both `FormatCom` (`:189-192`) and `MainCom` (`:206-209`); the codebase's own correct idiom sits 400 lines away (`BaseCom::CallDriver:93-95`).
- Fix: `CW2A` conversion + server-side length check against `TC_BOOT_SECTOR_USER_MESSAGE_MAX_LENGTH`.

**SEC-DRV-001 — Kernel NULL-deref via unprivileged status poll after failed header reopen**
- Evidence (✓): `src/Driver/DriveFilter.c:1796-1799` — failed `TC_IOCTL_REOPEN_BOOT_VOLUME_HEADER` (wrong password) does `crypto_close (HeaderCryptoInfo); HeaderCryptoInfo = NULL;` while `DriveMounted` stays TRUE; unprivileged `TC_IOCTL_GET_BOOT_ENCRYPTION_STATUS` (`Ntdriver.c:3034-3036`, no privilege gate — the tray app must poll it) later executes `bootEncStatus->MasterKeyVulnerable = Extension->HeaderCryptoInfo->bVulnerableMasterKey;` (`DriveFilter.c:2550`).
- Mechanism: admin types one wrong password in the system-encryption change/restore flow → every status poll (any local user, or the GUI's own timer) reads near-NULL in kernel mode → bugcheck. EX-2 is partial (state requires the prior admin error), hence Medium, but the trigger sequence is routine.
- Fix: NULL-check at :2550 regardless; on reopen failure, restore/re-open a replacement header (or set state so the `!VolumeHeaderPresent` branch answers the poll).

**SEC-COM-002 — `%TEMP%\veracrypt_driver_setup.inf` write-then-reopen TOCTOU under elevation**
- Evidence (✓ fixed path at `Dlgcode.c:14378`): the INF is written with `CREATE_ALWAYS` at the fixed name, closed, then reopened by path (`SetupOpenInfFileW`) and installed with `SPINST_REGISTRY` against a `KEY_ALL_ACCESS` class key — from the elevated path (`BootEncryption.cpp:6755/6788`).
- Mechanism: a non-elevated same-user process swaps the INF between close and reopen → registry section of the attacker's choosing installed elevated (filter-driver list tampering/persistence; capped by driver-signature enforcement on modern Windows).
- Fix: unique temp name, keep the handle between write and parse, or install the value directly in-process (the code already has that fallback shape at `BootEncryption.cpp:6768-6776`).

**SEC-COM-003 — Portable-mode driver load starts `veracrypt-x64.sys` beside the EXE without signature/hash verification**
- Evidence: `src/Common/Dlgcode.c:5366-5408` (`DriverLoad`, reached in non-install mode): path = EXE directory + `veracrypt-{x64,arm64}.sys`; guard = `FindFirstFile` (`:5341` ✓) existence only; `CreateService` + `StartService`. Contrast: the wizard DOES verify (`Mount.c:2151` `VerifyModuleSignature`).
- Mechanism: EXE folders are routinely user-writable (Desktop/Downloads/extracted zip) — a planted `.sys` is loaded as a kernel driver. Modern x64 signature enforcement forces the planted driver to be signed (BYOVD-style), which caps payload choice but not the persistence/abuse path; older systems fully exposed.
- Fix: `WinVerifyTrust` on the driver before `StartService` (same call the wizard uses), or pin a build-time catalog hash.

**SEC-COMM-003 — FAT full-format fill loop wraps `int` for FAT volumes >2 TiB (sectors >2^31): writes past data area**
- Evidence: `src/Common/Fat.c:445-452` — `x = ft->num_sectors - ft->reserved - ft->size_root_dir/ft->sector_size - ft->fat_length*2;` with `int x` (num_sectors is `unsigned int`; UI permits up to `TC_MAX_FAT_SECTOR_COUNT = 0x100000000ULL` sectors, `Tcformat.c:3697-3698`); `while (x--)` then writes encrypted filler sectors.
- Mechanism: for >2^31 sectors the signed wrap makes `x` negative → the loop runs ~2^32 times writing past the data area: file containers grow until the host disk is full; device/partition volumes get random-keyed overwrite to the end of the medium before aborting with `ERR_OS_ERROR`. Quick-format path is safe (`unsigned __int64`).
- Fix: `uint64` counter + assertion against `num_sectors`. *(Second, related: `SEC-COMM-004` — `wcsncpy` to `InstallationPath[TC_MAX_PATH]` without guaranteed NUL at `SetupDLL/Setup.c:2124`, un-terminated global then fed to `StringCbCopyW`/`wsprintfW` consumers in an elevated MSI custom action.)*

**SEC-REG-001 — Rescue-disk `DcsProp` config staged through a fixed-name `%TEMP%` file and read back by name**
- Evidence: `src/Common/BootEncryption.cpp:5785-5795` — `%TEMP%\_dcsproprescue` written by `conf.Save`, deleted in `finally`, re-opened by name and its re-read size trusted for the buffer → same-user swap race lands attacker content in the **rescue ISO's pre-boot authentication configuration**.
- Window is small and the attack is same-user, but the artifact crosses into the boot chain. Fix: unique name + read back from the same handle (the sibling zip path already uses `GetTempFileNameW` at `:5706`).

### 2.3 Low severity (selected — full list per area below)

| ID | Area | Finding |
|---|---|---|
| SEC-BOOT-002/003 | boot | Boot-sector PIM 2-byte writes unchecked at the sink (COM + EFI paths) — bypassing callers store wrong low-16 PIM → wrong pre-boot KDF iterations / correct-password-fails; pre-boot prompt accepts 7-digit PIMs the 16-bit packing can't represent. Fix: clamp to `MAX_BOOT_PIM_VALUE` at sinks + 5-digit prompt. |
| SEC-CRYPTO-001 | crypto | C++ KDF `GetIterationCount` int overflow: `pim * 2048` (Boot classes, `Pkcs5Kdf.h:95`) wraps for pim > 1,048,575; GUI validates only the `*1000` formula's `MAX_PIM_VALUE`; the C++ core lacks the C-side cap (`Volumes.c:830` exists there). Self-inflicted (UB + weak-derivation attempt). Fix: mirror the C cap + int64 math. |
| SEC-CRYPTO-002 | crypto | Non-wolfCrypt C++ KDF wrappers always `return 0` — user abort reported as success with partial key material in the output buffer (`Pkcs5Kdf.cpp:198-203`; `Pkcs5.c:330-333` burns context but not `dk`). Candidate decrypt on junk; no boundary crossing. Fix: return `ERR_USER_ABORT` (wolfCrypt variant already does, `wolfCrypt.c:250-258`). |
| SEC-CRYPTO-003 | token | PKCS#11 PIN retry loop unbounded (`SecurityToken.cpp:497-516`) → token PIN-counter lockout (physical-token DoS). PIN material itself is burned each iteration. Fix: retry cap. |
| SEC-CRYPTO-004 | RNG | RDRAND/RDSEED fill loops retry forever with no cap and cannot report failure (`rdrand_ml.asm:66-70`, `rdrand.c:9-17`) — unkillable spin on RDRAND-advertising faulty/hypervisor-broken hardware (user-space poll + kernel seed path). Fix: bounded retries + fallback. |
| SEC-DRV-004 | driver | `TC_IOCTL_GET_SYSTEM_DRIVE_CONFIG` returns raw MBR content to unprivileged callers with only a 28-30-char path-shape check (`Ntdriver.c:2451-2459`) — info disclosure of partition table/bootloader bytes; path grammar admits 3-digit disk indices. Fix: decimal-grammar check + access gate. |
| SEC-DRV-002/003 | driver | DumpFilter: PFN swap doesn't reject `MDL_PARTIAL`; HIGH_LEVEL memcpy over possibly-paged mapped VA on new dump stacks (OS-supplied MDLs only — hardening). |
| SEC-COMM-002 | installer | `DecompressZipToDir` ignores `zip_fread` return + trusts `sb.size` (already known from audit #1 — confirmed again from the vendored-usage side; huge stated sizes → elevated `bad_alloc` crash / >4 GB sizes truncate to partial files). |
| SEC-COMM-008 | SDK | FormatDLL SDK ignores `StringCbCopyW` truncation for keyfile/container paths → volume silently created with a different derived key than the caller believes. |
| SEC-COMM-009/010 | MSI | PKCS#11 `ulValueLen` used unvalidated for allocation (hostile module → crash); uncaught `stoi`/`vswprintf` conversions in deferred CAs crash the elevated install on malformed MSI properties. |
| SEC-CORE-002 (crossplat) | CLI | `TextUserInterface::AskPassword` stack over-read: copy capped at `MaxSize` (128) but conversion given full unbounded line length (`TextUserInterface.cpp:156-197`) → CLI crash on very long stdin lines; errors out before silent use. Fix: clamp. |
| SEC-MOUNT-003 | CLI | Missing `break` after `case OptionEnableIME` (`Mount.c:10468-10488`) — `/enableime` silently also sets `DisablePeriodicDeviceUpdate`. |
| SEC-BOOT-004/005/007 | boot | Decompressor `bits()` reads past declared `inlen` (64K-segment-contained; authority = boot-sector writer); checksum length word unvalidated (same authority); DecryptDrive sector retry loops spin forever on persistent BIOS errors (pre-boot hang, header half-writable on power-off). Hardening-grade. |
| SEC-COMM-001 (installer) | — | Zip-slip (`CorrectFileName` = slash-only translation) **reconfirmed with its load-bearing control identified**: activation requires a supply-chain-crafted *signed* installer (VerifyModuleSignature + whole-file CRC with signature areas zeroed, `SelfExtract.c:443-449`). Robustness if the signing key or build pipeline is ever compromised; sanitize anyway. |

### 2.4 Hardening notes (EX-rejected, failing rung named)

ExpandVolume `uint64` underflow on tiny device volumes (self-harm rung); `SetFileValidData` fast-resize leaves prior disk bytes inside container slack (privacy footgun); `Cmdline.c:201` silent truncation of `/p` password (mount-fail only); `UserPreferences` `SecurityTokenLibrary` trusted config→PKCS#11 module path (0700 dir, same-user); `FastResizeFile`; `SetFileValidData` again with `initFreeSpace` guard covering it; `TrueCryptFactory::CreateInstance` `if (hr) delete` (QueryInterface only returns S_OK/E_NOINTERFACE today); `BaseCom::ReadWriteFile/DeviceIoControl` trusting caller `size` (sole client pre-allocates; REGCLS_SINGLEUSE per-instance UAC is the boundary); `wsprintfW` into `mainModule[1024]` (admin-controlled input, EX-2); benchmark array guards compile-time-bounded; `PrintHardCopyTextUTF16` title-as-filename (current callers pass constants); dead `#if 0` XP hibernate filter and dead unbounded `DecompressDeflatedData` inflate API (delete); `wmemcmp` OOB read in setup table lookup (same signed-installer gate); `PACKS` TSE hygiene noted elsewhere.

---

## 3. Verified Strengths (adversarially confirmed — the load-bearing controls)

- **Kernel ioctl surface**: all 44+ custom ioctls are `METHOD_BUFFERED` (no `METHOD_NEITHER`); every handler validates input length (`ValidateIOBufferSize`); sensitive structs exact-size checked and burned on return; file-hosted opens use `OBJ_FORCE_ACCESS_CHECK` with client impersonation; abort/mount paths TOCTOU-guarded (sequence numbers, bounded SID copies, fail-closed).
- **Boot handoff** (`DriveFilter.c`): BootArguments CRC + read-once copy; `BootSecRegionValidate` signature/size/count/slot-type/CRC + double overlap rejection; password cache count-capped; PIM clamped. Rated "hardened beyond upstream."
- **Elevation design (COM)**: `Elevation:Administrator!new:` moniker + `REGCLS_SINGLEUSE` per-class instance ⇒ every elevated interface costs a fresh UAC consent; credentials never in argv (`sudo -S` pipe; admin password burned via `finally_do`).
- **Header/key derivation**: `DeserializeEntry` bounds every field (C++ and C mirrored); fixed-offset salt (no count-driven slots); Argon2 parameters derive **only from PIM** (never from header bytes) with upstream `validate_inputs` enforcement; key material burned on every error path; weak-key (duplicate-half) detection at create AND read; XTS key-split/tweak identical across all three backends; `AES_ERR_CHK` unconditional (no silent unencrypted output).
- **TLV/EMV/APDU**: fully bounded parsing (indefinite lengths rejected, nesting ≤32, EMV directory 254-record cap); PIN/PAN burned on every path; APDU construction bounds-checked.
- **Trusted-binary resolution (Unix)** and `Process::Execute` argv discipline; `--stdin` path bounded with explicit aborts; `--size` overflow-guarded; XML parsers bounds-checked with in-tree self-tests; favorites-label attribute injection closed.
- **Rescue/restore controls**: exact-size backup validation, partition-table preservation on MBR writes, sys-loader-backup ACL trust check, header restore requires password + confirmation; rescue ISO fragments and decompressed loader bounds capped (`TC_MAX_BOOT_LOADER_DECOMPRESSED_SIZE`).
- **Trusted binary installs**: driver service names/paths constant; `RecordInstallationPath` shape-validates before HKLM writes.

---

## 4. Prioritized Remediation

1. **SEC-COM-001 + SEC-COM-002 + SEC-REG-001** (same repair class: elevated helpers staging through user-writable `%TEMP%` at fixed names): move to in-process elevated COM operations or unique-name private-directory staging with verify-before-use. *(No code changed — remediation list only, per report-only mandate.)*
2. **SEC-CORE-001**: elevation target from `/proc/self/exe` only on Linux.
3. **SEC-BOOT-001**: single-line fix (`CW2A` + length check) in `BaseCom.cpp`; both COM servers inherit it.
4. **SEC-DRV-001**: NULL-check + state repair on failed reopen.
5. **SEC-COM-003**: `VerifyModuleSignature` on the portable driver path.
6. **SEC-COMM-003**: `uint64` FAT loop counter (+ SEC-COMM-004 `StringCbCopyW` terminator guarantee).
7. Crypto precision set: C++ PIM caps mirroring `Volumes.c:830`; `ERR_USER_ABORT` propagation; RDRAND retry caps; PIN retry caps.
8. Installer parser robustness (bounds-checked walk + `..` rejection) — defense-in-depth beneath the signing gate.

## 5. Coverage Gaps & Issues Encountered (noted only)

- `src/Boot/EFI/**` ships **only prebuilt `.efi` binaries** (DcsBoot/DcsCfg/DcsInt/DcsRe from upstream 2011/2023 UEFI CA trees) — the EFI rescue/authentication chain is **not statically auditable from this tree**; a binary-assisted review is the only path.
- wolfSSL internals (external dependency) and `wc_AesXtsEncryptConsecutiveSectors` sector-size contract for the 448-byte header payload unverifiable in-tree (functional question, not a defect).
- asm/intrinsic bodies (AES/SHA/Serpent/Twofish/etc.), vendored libzip/lzma/zlib internal trees: version evidence only (zlib 1.3.2, libzip 1.11.3, LZMA SDK 24.09 — recorded from the tree; **no CVE cross-reference was possible** under the no-web constraint).
- Tooling: several catalog contract payloads were clipped by output-size limits (auditors re-paged); one child reported three contract files returning non-displayable payloads (rules not applied); `load_skill_file` rejects absolute paths (retried). No repository file was modified; nothing was built, run, or playtested.

*Companion reports: `mistral-audit-all-23NOV2026.md` (full-suite audit) and `mistral-auditskill-analysis-23NOV2026.md` (adaptation analysis).*
