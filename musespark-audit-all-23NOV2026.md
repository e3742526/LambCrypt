# VeraCrypt Protective Code-Scan Audit — musespark-audit-all-23NOV2026.md

Date: 23 NOV 2026
Mode: REPORT ONLY — no code changes, no playtest, no dynamic mount/crypto runtime
Method: read-only static code scan of `src/` via agent workflow (5 sweep agents + critic + gap follow-up + synthesis)
Bans honored: prior `*.log`, session logs, prior audit MDs (`*AUDIT*.md`, `SECURITY-REPAIR-PLAN.md`, `BUGLOG.md`) deliberately NOT read; no corroboration against them
Scanners: broad SAST / secret-scanner / dependency scan SKIPPED per instruction and tool absence — recorded as gap, not as pass
Live network: reachability/TLS of `github.com`, `veracrypt.io`, `cdburnerxp.se` NOT tested (read-only scan); assumed OS-browser-handled
Workspace: `/Users/eric/Work/vscode/VeraCrypt`

## 0. Scope and protective question

Goal: as a data-protection system the user modified, did the checkout introduce anything of concern — silent exfiltration, weakened KDF/header/auth, destructive I/O, secret leakage, privilege or supply-chain risk?

Verdict from code scan: no in-app silent network, no remote-fetch parser, no plaintext secret logging found. Highest residual risk is durability / data-loss (torn or mismatched headers, destructive backup-export, expand crash windows), then deniability footprint (sparse/TRIM), then memory retention (Unix paging, dump). Details below with file:line provenance and steps to reproduce (STR).

Status of this report: `partial` — full-part evidence for KDF, memory, durability-negatives, and skill mapping was retained in workflow handoffs but compacted out of the synthesis packet; those sections below are marked lineage-gaps and rely on retained handoffs, not re-inspection in synthesis.

## 1. Network / telemetry / update — protective: no silent network

Only outbound targets found are fixed HTTPS constants:

- `src/Common/Tcdefs.h:431-433` — `TC_HOMEPAGE` / `TC_APPLINK` (`https://github.com/e3742526/LambCrypt`), `TC_UPSTREAM_DOCS` (`https://veracrypt.io/en/`) — all HTTPS.

User-initiated browser open only, no in-app fetch:

- `src/Common/Dlgcode.c:11979-12159` `Applink(dest)` maps donate/main/downloads/news/contact to fixed HTTPS URLs, docs pages to local file else `TC_UPSTREAM_DOCS` + page; opens via `ShellExecuteW` / `SafeOpenURL` only.
- `src/Main/GraphicUserInterface.cpp:1531-1715` `GetHomepageLinkURL` / `OpenHomepageLink` — same fixed HTTPS set (downloads/releases, issues, `cdburnerxp.se/en/home`); local HTML preferred, fallback to `TC_UPSTREAM_DOCS`; `wxLaunchDefaultBrowser` only.
- `src/SetupDLL/Setup.c:796-958` `Applink_Dll` — identical fixed URL set, `ShellExecuteW` / `SafeOpenURL`; no silent download in installer.
- `src/Common/Dlgcode.c:15665-15702` `SafeOpenURL` — de-elevated open via `rundll32 url.dll,FileProtocolHandler` or `IShellDispatch2` / `ShellExecuteW`; URL passed to OS browser, no app-side TLS/certs.
- `src/ExpandVolume/WinMain.cpp:1068` `SafeOpenURL(Lhttps://veracrypt.jp)` on `IDM_HOMEPAGE` menu — user-click browser open only.
- `src/Common/Dlgcode.c:16262-16286` `IsInternetConnected` uses `INetworkListManager::get_IsConnectedToInternet` only; caller at `12135` selects local vs online docs — connectivity check only, no version/phone-home payload.
- `src/Main/FatalErrorHandler.cpp:35,68` — error report URL is `GetHomepageLinkURL(issues)` + `AskYesNo` prompt before `wxLaunchDefaultBrowser`; crash report is opt-in browser open, no automatic telemetry upload.
- `src/Common/Dlgcode.c:2301` + `src/Main/Forms/AboutDialog.cpp:40-41` — `http://www.truecrypt.org/` is display/attribution string only, not fetched; legacy HTTP is text, zero transport risk.
- `src/ExpandVolume/WinMain.cpp:1068` veracrypt.jp open is menu-click only (same as above).

Negative scan of `src/*.c/*.cpp/*.h`: no `WinHttp` / `WinINet` / `InternetOpen` / `HttpSend` / `URLDownloadToFile` / `curl` / `libcurl` / `HttpClient` / socket-fetch, no auto-update/version-poll, no telemetry/crashpad/sentry/phone-home, no proxy env/use-proxy code (only `CoSetProxyBlanket` COM/WMI + `CoreServiceProxy` IPC naming), no app TLS stack/certs/pinning. Consequence: downgrade / proxy-bypass / cert-pinning checks are N/A rather than verified-present — nothing to pin because the app never performs HTTPS itself.

STR (protective negative): precondition — instrument or proxy OS browser traffic; action — click every Help/Homepage/Download/Issue link and trigger crash-report dialog; outcome expected — only OS-browser HTTPS navigations to the fixed hosts above, zero app-originated sockets.

## 2. XML / ZIP parsing — protective: local-only, XXE closed by flags

- `src/Mount/Mount.c:719-737,14038-14056` `validateDcsPropXml` via MSXML6 `DOMDocument60` `loadXML` with `async=false`, `validateOnParse=false`, `resolveExternals=false` on local ESP `DcsProp` text — no remote DTD/schema fetch; XXE surface closed by flags.
- `src/Core/Unix/MacOSX/CoreMacOSX.cpp:90-102` `ParsePropertyList` parses local `hdiutil -plist` stdout via `CFPropertyListCreateWithData` — no remote XML.
- `src/Common/BootEncryption.cpp:5717,6008,6152` `zip_open` / `zip_open_from_source(ZIP_CHECKCONS)` builds/reads local rescue-disk ZIP (EFI images, `DcsProp`, `svh_bak`) — no remote archive fetched/parsed; inflation is bundled `zlib`/`libzip` on local data.

STR: precondition — local ESP `DcsProp` with external-entity payload; action — run DCS validation and rescue-ZIP build/read; outcome expected — entities not resolved, no outbound fetch, parse of local bytes only.

## 3. Durability / data-loss — highest risk rank

Positives observed (do not cancel negatives):

- `src/Volume/Volume.cpp:424-450,467-470` `Volume::WriteBytes` / `WriteSectors` bounds checks with read-modify-write confined to `VolumeDataSize`.
- `src/Volume/Volume.cpp:244-248` `CheckProtectedRange` + read-only fallback when header-declared data area exceeds host.
- `src/Format/InPlace.c:660-664` in-place encryption verifies backup header by re-decryption before encrypting — sound resume gate.
- User confirmations: `src/ExpandVolume/DlgExpandVolume.cpp:244-253` `QUICK_EXPAND_WARNING`, `src/Main/Tcformat.c:6028` `WARN_QUICK_FORMAT`, `6036` `WARN_FAST_CREATE`, `6050` `CONFIRM_SPARSE_FILE`, `431-435` fast-create security comment.
- `src/Common/Format.c:780-785` format failure truncates preallocated container so no half-randomized container is left behind.

Negatives (each with STR as precondition / action / outcome):

(a) Missing Flush windows. `src/Core/VolumeCreator.cpp:366-372` + `139-201` primary header written with no Flush, single `VolumeFile->Flush()` only after data+backup-header writes; `src/Mount/Mount.c:13175-13204` external restore writes primary then re-encrypts and writes backup with no flush/fsync between, `CloseHandle` at `13231-13235` with no flush; `src/Main/TextUserInterface.cpp:1947-1955` same single Write with no flush; `src/Volume/Volume.cpp:397-416` `ReEncryptHeader` `SeekAt`/`SeekEnd`+Write with no Flush (durability depends on caller — `CoreBase::CoreBase.cpp:72-73` flushes per wipe pass, TextUI restore path does not); `src/Format/InPlace.c:1227-1300` resume `closing_seq` `CloseHandle` with no `FlushFileBuffers`, per-chunk ciphertext `WriteFile` at `~1007` has no barrier. STR: non-quick create or header restore in flight; kill/power-loss between primary and backup writes; outcome durable-primary/stale-backup or torn header unopenable by either password, or header/media length disagreement on resume.

(b) Unix `File::Write` no EINTR/short-write loop. `src/Platform/Unix/File.cpp:516-524` single `write()` vs `526-561` `WriteAt` loop with EINTR/EOVERFLOW handling. STR: signal during create; `File::Write` bulk path; outcome `ERR_OS_ERROR` abort, SetLength-preallocated but partially written container must be recreated.

(c) Backup-export truncates before writing. `src/Main/GraphicUserInterface.cpp:445-446` `backupFile.Open(CreateWrite)` + `src/Platform/Unix/File.cpp:323-324` `O_CREAT|O_TRUNC` and `src/Mount/Mount.c:12665` `_wopen(_O_CREAT|_O_TRUNC)`. STR: backup path points at existing file holding the only prior backup; confirm backup; crash before `_write`/`backupFile.Write`; outcome prior backup destroyed before replacement exists.

(d) Expand grows file before new headers. `src/ExpandVolume/ExpandVolume.c:780-784` grown via `SetFilePointerEx`+`SetEndOfFile` before new headers at `915-925`/`1004-1005`; size-restore on failure only covers pre-header path `843-858`; `bQuickExpand` path `790-796` uses `SetFileValidData` exposing stale disk bytes (mitigated by YES_NO/MB_DEFBUTTON2 warning at `DlgExpandVolume.cpp:244-253`). STR: expand with init; crash mid-expand; outcome size/header mismatch, tail undecryptable.

(e) Sparse holes never randomized + forced quick format. `src/Common/Format.c:407-427` sparse container = `FSCTL_SET_SPARSE` + `SetEndOfFile` preallocation with holes never randomized; `Tcformat.c:6054-6058` forces quick format for sparse. STR: sparse container; write data; outcome host-FS allocation metadata leaks approximate used-range footprint; hidden-volume free-space deniability weakened.

(f) TRIM/discard absence. Regex sweep for `DISCARD|BLKDISCARD|FITRIM|FSCTL_SET_ZERO|punch|ZERO_RANGE|fallocate` over `src/Driver,Volume,Platform,Core,Common` returns only unrelated UI string (`Language.xml:1258`); no deallocation passthrough anywhere. STR: any overwrite/delete on flash; normal use; outcome stale ciphertext retained in SSD/FTL/host journals outside volume control.

(g) TOCTOU check-then-act. `src/Platform/Unix/File.cpp:351-357` `stat()` before open for `PreserveTimestamps` and `287-292` `Length()` via `lseek SEEK_CUR/SEEK_END` are racy; `Tcformat.c:3464-3469` `QueryFreeSpace` adds existing-file size to free space then file is overwritten. Hardening exists only on mount paths (`CoreUnix.cpp:46-81` `realpath`+`lstat`, `128-135` `O_NOFOLLOW`, `1292-1305` `openat O_NOFOLLOW`), not on create/format stat paths.

(h) In-place resume barrier gap. Recovery design is sound (backup header re-verified by decrypt at `InPlace.c:660-664`, `FastVolumeHeaderUpdate` at `1231-1239` on interrupt) but OS crash can lose tail of encrypt/decrypt pass while header already accounts for it. STR: in-place encrypt/decrypt interrupted by OS crash; resume; outcome header `EncryptedAreaLength` disagrees with media, sectors mis-decrypted.

## 4. KDF / password / header / RNG (from retained full-part handoffs — compact-empty lineage gap)

- `src/Volume/Pkcs5Kdf.h:39,44-52,71,89,109,127,145,208` KDF matrix: PBKDF2 default `pim=0` maps to 500000 iters (Boot variants 200000); custom PIM formula `15000+pim*1000` (Boot: `pim*2048`); Argon2id default PIM 12; `ValidateParameters` rejects empty password/salt/key and `iter<1`; unknown KDF name throws.
- `src/Common/Pkcs5.c:1285-1335,1441-1473` `get_pkcs5_iteration_count` mirrors header formulas; `get_argon2_params`: `pim<=0->12`, `mem=64+(pim-1)*32` MiB capped 1024 MiB (PIM31), `time=3+(pim-1)/3` up to 31 then `13+(pim-31)`; custom `PIM=1` risks WEAK cost (96 MiB/t3 vs default 416 MiB/t6) yet caller only warns; boot PIM clamped to 16-bit in `Volumes.c:228`.
- `src/Volume/Pkcs5Kdf.cpp:213-226,243-254` `Pkcs5Argon2(pim)` path resolves memory+iters via `get_argon2_params`; iterationCount-only overload throws `ParameterIncorrect` (no silent fallback); WolfCrypt ctor raises PBKDF2 iteration ceiling to `INT_MAX`.
- `src/Volume/VolumePassword.h:30,44-46` + `src/Volume/VolumePassword.cpp:19-22,67-79` `operator==` via `ConstBufferPtr::IsDataEqual`; `MaxSize=128` (legacy 64), Warn<12, SmallPIM threshold 20; `Set` erases buffer first, throws `PasswordTooLong`; serialize pads pipe with 128 KiB zero `WipeData`.
- `src/Platform/Memory.cpp:48-56` + `src/Platform/Buffer.h:33` `Memory::Compare` is size-check then `memcmp` (NOT constant-time); only used for password-object equality, not for header MAC (header auth is decrypt+magic+CRC32), so timing-oracle scope is local password-object compare only.
- `src/Volume/VolumeHeader.cpp:76,347` + `src/Common/Volumes.c:700-707` XTS weak-split-key detected via `memcmp` halves-equal → `XtsKeyVulnerable` / `bVulnerableMasterKey` flag (WARN-only, volume still opens); `memcmp` here is non-secret random-key comparison, safe.
- `src/Volume/VolumeHeader.cpp:105-204,266-358` + `src/Common/Volumes.c:571-596,638-644,722-744` header auth = XTS decrypt then `VERA` magic + version range + header CRC (>=v4) + key-area CRC32; wrong password returns `false` / `ERR_PASSWORD_WRONG` with no distinguisher; `HigherVersionRequired` only on version>current; sector-size bounds enforced; `Deserialize` copies `DataAreaKey` only after both CRCs pass.
- `src/Volume/Volume.cpp:125,138-177,194-283` Open tries layouts in order (`V2Normal`, `V1Normal`, `V2Hidden`, System), primary vs backup selected by flag; truncated-host forced ReadOnly (offset/size vs host check); hidden-outer open verifies inner hidden password and records `ProtectedRange`; wrong inner password maps to `ProtectionPasswordIncorrect` (outer still opened).
- `src/Volume/VolumeLayout.cpp:68-86,100-156` + `src/Volume/VolumeLayout.h:33-44,73-130` `V1Normal` has NO backup header (`HasBackupHeader=false`); `V2Normal` backup at `-TC_VOLUME_HEADER_GROUP_SIZE`; `V2Hidden` primary `TC_HIDDEN_VOLUME_HEADER_OFFSET` / backup negated; hidden deniability relies on outer free-space indistinguishability; V1 volumes lack embedded-backup recovery path.
- `src/Volume/Keyfile.cpp:22-91,133-156` `Keyfile::Apply` mixes file bytes via CRC32 adds into pool (pool>=4 B, max 1 MiB/file, empty/single-byte throws `InsufficientData`); dirs expanded, dotfiles skipped on Unix; pool seeded with zero-padded password sized 64/128 by legacy flag; token path burns temp vector via `finally_do_arg`.
- `src/Volume/EncryptionAlgorithm.cpp:21,63-82` + `src/Common/Crypto.c:129,774-777` no cipher or KDF marked Deprecated in inspected constructors/table (`Deprecated=false` default; table-driven); legacy LRW path retained only as fallback in header decrypt (`LegacyEncryptionModeKeyAreaSize` branch) for TrueCrypt-compat volumes.
- `src/Volume/Cipher.h:66-71` + `src/Volume/EncryptionModeXTS.h:31-46` XTS mode only; master+secondary keys in `SecureBuffer`; no ECB/CBC/LRW offered on modern path; cascade ciphers (AES-Twofish-Serpent etc.) increase key material via `DataKeyAreaMaxSize=256`.
- `src/Common/Random.c:255-260,427-460,680-836` RNG pool 320 B, `Randmix` per 16 B, `SlowPoll` once + `FastPoll`; Windows `SlowPoll` seeds `BCryptGenRandom SYSTEM_PREFERRED_RNG` + RDSEED/RDRAND if present; `IsRandomPoolEnrichedByUser` tracks mouse/keyboard enrichment; `RandStop` clears enriched flag.
- `src/Common/Password.c:59,137-187` + `src/Volume/Pkcs5Kdf.h:40-42` + `src/Common/Password.h:18-28,31` `MIN_PASSWORD=1` (keyfiles can satisfy empty password); <20-char warns; custom PIM below default requires >=20-char password else hard Error; PIM above default only Warning; `MAX_PIM_VALUE` 2147468 overflows 32-bit formula risk bounded by `INT_MAX` wolfCrypt set.
- `src/Common/Volumes.c:334-335,769,ret_key_info` + `src/Volume/VolumeHeader.cpp:67,449` `dk`/header/`keyInfo` buffers `VirtualLock` + burn on all exits (ret/err); Argon2 failure zeroes `dk` (`Pkcs5.c:1385-1389`); residual: base `Pkcs5Kdf::DeriveKey(void)` overloads ignore `pAbortKeyDerivation` (no-op forward).
- `src/Common/Password.c:190-218` + `src/Common/Volumes.c:1512-1513` `ChangePwd` rejects empty old/new and `wipePassCount<=0`; `Volumes.c` documents `bPrimaryOnly`/`bBackupOnly` random-fill flags: user-modification risk = restoring stale backup header reverts PIM/KDF/master key (data-loss/desync), wiping header area without backup destroys volume.

STR (KDF/header): precondition — custom PIM=1 volume and default-PIM volume; action — attempt open with wrong password, with weak split key, with V1 truncated host; outcome expected — `ERR_PASSWORD_WRONG` with no oracle, WARN-only weak-key open, V1 no-backup path, read-only fallback on truncation.

## 5. Memory / privilege / build / supply chain (from retained full-part handoffs — compact-empty lineage gap)

- `src/Common/Tcdefs.h:373-377` `burn()` = `RtlSecureZeroMemory`+volatile loop on Win32, volatile-only loop elsewhere → non-Windows lacks guaranteed non-elided wipe (no `explicit_bzero`/`memset_s` fallback).
- `src/Platform/Buffer.cpp:82-92` `Buffer::Erase` uses `memset_s` only under `TC_MACOSX` else `burn` → Linux/Unix wipe relies on volatile loop only.
- `src/Common/Volumes.c:239-335` `VirtualLock(dk/header/keyInfo/workItems)` + `:749-781`/`:1403-1404` burn+`VirtualUnlock` on ret/err paths → KDF/header keys locked and wiped on all exits.
- `src/Common/Cache.c:219-224` `WipeCache` burns `CachedPasswords`/`CachedPim`; `src/Driver/DriveFilter.c:1197` `burn(pwdCache)` → boot pwd cache wiped after copy.
- `src/Common/Password.c:81-84,127,565` burn tmp password buffers but `:384` plain `memset(buffer)` for short-read header path (later burned at `error:` label) → transient non-volatile clear only.
- `src/Common/Keyfiles.c:247-248` `VirtualLock(keyPool)`+`finally_do` burn+`VirtualUnlock` → keypool locked/wiped even on exception.
- `src/Common/Dlgcode.c:4139` `VirtualLock(CmdTokenPin)` with no matching `VirtualUnlock` found → process-lifetime lock, benign but never released.
- No `mlock`/`munlock`/`mlockall`/`VirtualLock` counterpart in `src/Platform`, `src/Volume`, `src/Core` (grep hits only Windows files + jitterentropy header) → Unix key material pageable; swap exposure (inferred from zero hits, not runtime-verified).
- No pagefile/minidump/crash-dump suppression found (no `SetErrorMode`/WER/opt-out, `Dump()=DbgPrintEx` debug-only per `Tcdefs.h:337-345`, `Ntdriver.c:276` version string only) → crash-dump/pagefile can retain keys.
- `src/Common/Apidrvr.h:27` all `TC_IOCTL()=CTL_CODE(FILE_DEVICE_UNKNOWN,METHOD_BUFFERED,FILE_ANY_ACCESS)` → any local user can open device; authorization deferred to per-handler checks.
- `src/Driver/Ntdriver.c:792-799` `IoCreateDevice FILE_DEVICE_SECURE_OPEN`, `Exclusive=FALSE` + `:817` symlink → ACLs from SDDL/default; `METHOD_BUFFERED` avoids NEITHER probe bugs.
- `src/Driver/Ntdriver.c:573-593` `ValidateIOBufferSize` checks in/out lengths + zeroes output buffer → length confusion mitigated.
- `src/Driver/Ntdriver.c:4717-4723` `UserCanAccessDriveDevice` gates via MountPointManager accessibility; `:1005`,`:5203` `SeTokenIsAdmin` bypass lets admins act on other users mounts/volumes → by-design admin override, document.
- `src/Driver/Ntdriver.c:2577,2865,2949,3112,3907` privileged ops check `UserCanAccessDriveDevice`; `:1024-1033` abort restricted to same-SID/admin → cross-user mount abort blocked.
- `src/Common/Dlgcode.c:10165` `IsAdmin()=IsUserAnAdmin`; `:4178`,`:10699`,`:13901`,`:14026` runas `ShellExecute` elevation; `:11822-11831`,`:14565-14602` `AdjustTokenPrivileges` with finally restore → least-privilege elevation pattern.
- Manifests: `Mount.manifest`+`Format.manifest` asInvoker; ExpandVolume `VeraCryptExpander.manifest` requireAdministrator; Setup/`Setup.manifest`+SetupDLL requireAdministrator; Portable asInvoker → installer/expander always elevated, main app elevates on demand.
- `src/Core/Unix/CoreService.cpp:227-252` sudo/doas helper selection, NoNewPrivs note, rejects FreeBSD security/doas; `:1731-1734` `sudo -S` spawn; `CoreUnix.h:49` `HasAdminPrivileges` `getuid/geteuid==0` → no setuid binary, elevation via helper.
- `src/Common/Dlgcode.c:14378` `RegisterDriverInf` predictable `GetTempPathString()+veracrypt_driver_setup.inf` → symlink/planting race in shared temp (File created with delete-finally but no `O_EXCL` evidence; exploitability not proven) vs safe `BootEncryption.cpp:5702-5706` `GetTempPathW`+`GetTempFileNameW` `_vrd` prefix + `DeleteFileW` finally, `CoreMacOSX.cpp:712-734` per-user temp + `mkstemps O_EXCL` `.command` suffix, `CoreUnix.cpp:117-1521` `mkdtemp` + `O_NOFOLLOW`/`O_CLOEXEC` + ownership/mode checks.
- No password/PIN/key material in logs found: `Dump()` only versions/status/sector counts (`Ntdriver.c:276`, `EncryptedIoQueue.c:1493` commented-out sector log); `SecurityToken.cpp:430-500` PIN via `C_Login` with `finally_do` burn → no log leak.
- `src/Makefile:52-53` `CFLAGS`/`CXXFLAGS` `-Wall` only, no `-Werror`/`-fstack-protector`/`-D_FORTIFY`/`-Wformat-security`; `LFLAGS`: `-fpie`/`-pie` + `:256` `max-page-size=4096` for ASLR, no `-Wl,-z,RELRO/NOW/BIND_NOW` → no Full RELRO/BIND_NOW, no SSP/Fortify evidence.
- `src/Build/CMakeLists.txt`: no `POSITION_INDEPENDENT`/`RELRO`/`FORTIFY`/stack-protector/Werror hits; packaging comments `:387-414` static wxWidgets notes incl Ubuntu 24.04 wx 3.2.5 bug → hardening not enforced in CMake.
- Windows vcxproj: `Crypto.vcxproj:93,113` `BufferSecurityCheck=false` in Debug configs (Release true); `Driver.vcxproj:106,134` `TreatWarningAsError=true`; generally WarningLevel Level4 → Debug crypto lacks `/GS`.
- Third-party pinning: wxWidgets external via `WX_ROOT`/pkg-config (`Makefile:58,72,769-808`), libpcsclite/fuse/gtk via pkg-config unpinned; libzip/zlib vendored in `src/Common`; Crypto/Argon2 in-tree; `UPSTREAM.md` fork base `f38c8090` but no per-dep version lockfile found → supply-chain drift risk.

STR (memory/privilege): precondition — Unix volume open with key in RAM; action — force swap/crash-dump, inspect temp dir during driver INF install, open device node as non-owner; outcome expected per code — pageable secret possible, predictable INF name observable, per-handler access check decides.

## 6. Analysis of the issue, theory / hypothesis / solution (ranked)

(1) Data-loss cluster — HIGHEST. Theory: header-slot writes lack flush/barrier and backup-export destroys the only good copy before replacement exists; expand grows the container before new headers with incomplete rollback. Hypothesis: a crash/power-loss in any of those windows yields torn or mismatched headers unopenable by either password, or tail undecryptable. Solution: flush/fsync between header slots + verify-before-overwrite; write backup header first or via atomic temp+rename; O_EXCL/no-truncate backup export; EINTR/short-write loop in `Unix/File.cpp:516-524`; fsync before size-restore-arm in expand; audit every `ReEncryptHeader` caller for flush.

(2) Deniability cluster — HIGH. Theory: sparse holes are never randomized and TRIM is absent, so host allocation metadata and FTL/journal copies leak used footprint and stale ciphertext. Hypothesis: observer of host file or flash dump learns approximate usage, weakening hidden-volume deniability. Solution: warn loudly on sparse, document TRIM absence, avoid sparse for hidden volumes; consider explicit zero/randomize on release if TRIM stays absent.

(3) Memory-retention cluster — MEDIUM. Theory: Unix paths lack `mlock` and dump suppression; non-Windows `burn` is volatile-only. Hypothesis: keys pageable to swap and retained in crash dumps. Solution: `mlock`/`VirtualLock` on Unix key paths, dump opt-out, burn audit replacing transient `memset` at `Password.c:384` and OSX-only `memset_s` gate.

(4) Network cluster — LOW / protective. Theory: app never performs HTTPS itself; all opens are OS-browser handoffs. Hypothesis: no silent exfiltration introduced. Solution: keep browser-handoff, no change; live-TLS verification remains OS-browser responsibility.

(5) Temp-race / build-hardening / deps — LOW-MEDIUM. Theory: predictable INF temp name, `-Wall`-only flags, unpinned external deps. Hypothesis: local planting during driver install, easier exploit on memory bug, supply drift. Solution: `O_EXCL`/unique temps, enable RELRO/NOW/SSP/Fortify, `/GS` in Debug+Release, pin wx/pcsclite/fuse versions.

No evidence in scanned surfaces of an introduced backdoor, silent network exfil, header-auth bypass, or secret logging. That is a code-scan negative, not a proof — scanner, constant-time, driver-lifecycle, and dynamic-mount verification were all out of scope/banned.

## 7. Steps to reproduce (summary checklist)

- KDF/header: build default and `PIM=1` volumes; wrong-password open → `ERR_PASSWORD_WRONG` with no oracle; weak split key → WARN-only open; V1 volume → no backup slot; truncated host → read-only fallback.
- Durability: interrupt non-quick create / header restore / expand / in-place pass; export backup over existing file; create with signals on Unix `File::Write`; sparse container + writes; flash overwrite/delete — observe outcomes listed in §3.
- Network/XML/ZIP: proxy OS browser; click all links; feed external-entity `DcsProp`; build/read rescue ZIP — observe §1–§2.
- Memory/privilege: swap/dump inspection; temp-dir watch during INF install; non-owner device open — observe §5.

## 8. What was NOT verified / named gaps

- Broad security scanner not run (skipped per instruction; no tool in env).
- Live reachability/TLS of `github.com` / `veracrypt.io` / `cdburnerxp.se` not tested — assumed OS-browser-handled.
- Downgrade / proxy / pinning N/A rather than verified (no in-app HTTP client found).
- Compaction-loss gaps: priors 1/2/4 full parts carry file:line evidence but compact evidence empty — KDF/header/RNG, memory/IOCTL/hardening, skill-mapping verdicts rely on retained handoffs, not re-inspected in synthesis.
- Durability negatives exist in full part of prior-5, positives-only in compact notes — ranked fix list uses full-part STR.
- Constant-time audit of `Crypto/*` cipher internals not line-inspected; driver key lifecycle only at call sites.
- Unix `mlock` absence inferred from zero grep hits, not runtime-verified; device SDDL beyond `FILE_DEVICE_SECURE_OPEN` not runtime-inspected; INF temp race (`Dlgcode.c:14378`) exploitability unproven.
- Journaling/FUSE write-ordering assessed from code only; no TRIM implementation exists to audit beyond absence sweep.
- Prior-audit MD corroboration banned by task; dynamic mount/crypto banned by no-playtest constraint.



