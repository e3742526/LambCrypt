# Unrelated & Specialized Audit Skills Adaptation Analysis (`gem-hydrogen--auditskill-analysis-23NOV2026`)

> **Scope Notice**: Companion methodological & technical report to [gem-hydrogen--audit-all-23NOV2026.md](file:///Users/eric/Work/vscode/VeraCrypt/gem-hydrogen--audit-all-23NOV2026.md). Details how all **26 unrelated / domain-specialized `audit-*` skills** from `/Users/eric/Work/vscode/agent-skills/010_audit/` were systematically domain-translated onto the LambCrypt / VeraCrypt (`main` @ `954a10b9`) C/C++/Objective-C++/Swift/assembly/shell/CMake/Python codebase via **static code scan only** (zero code modifications, zero reading of prior audit logs/reports, zero playtests).

---

## 1. Adaptation Methodology & Accounting Overview

### A. Catalog Partition (55 Total `audit-*` Skills)
- **13 Core Required Lenses** + **14 Applicable Standalone Skills** (27 total): Executed natively in [gem-hydrogen--audit-all-23NOV2026.md](file:///Users/eric/Work/vscode/VeraCrypt/gem-hydrogen--audit-all-23NOV2026.md).
- **2 Excluded Orchestration / Runtime Skills**:
  - `audit-playtest-app`: Explicitly skipped per user constraint (`Don't rum playtest`).
  - `audit-multiagent-consensus`: Not applicable in a single-agent audit run.
- **26 Adapted Unrelated / Specialized Skills**: Exhaustively translated below via **Structural Isomorphism Mapping** — preserving each skill's abstract failure invariant (authority boundaries, trust-boundary translation, lifecycle ownership, state convergence, math/layout invariants, telemetry/detection posture, supply-chain drift) while swapping domain-specific nouns (`RLS` -> `Kernel/FSKit/POSIX ACLs`, `prompts/models` -> `CLI/KDF/crypto provider pins`, `HTML/CSS/React` -> `wxWidgets/Win32/BIOS Pre-Boot UI`, `Cypher` -> `device-mapper & vnd topology`, etc.).

### B. Operational Note on Catalog Discovery (`index_stale`)
- `agent-skills` MCP `search_skills` reported `semantic_available: false` (`fallback_reason: "index_stale"`), returning a deterministic lexical `audit_suite`. Every remaining skill in `010_audit/` was manually loaded so zero catalog checks were silently omitted.

---

## 2. Master Adaptation Matrix (All 26 Adapted Skills)

| # | Skill Name | Original Target Domain | LambCrypt / VeraCrypt Adapted Surface | Key Findings Produced |
|---|---|---|---|---|
| 1 | `audit-architecture-drift` | Repo architecture graphs / ADRs | `UPSTREAM.md` fork scope, FSKit vs FUSE, OpenBSD stub | `REL-OBSD-001`, `CMP-MAC-001`, upstream/fork parity gaps |
| 2 | `audit-architecture-nodejs` | Node/TS module graph & async boundaries | C/C++/ObjC++/Swift cross-module deps & `Makefile` | `INV-BLD-001`, `REL-FSK-001`, Windows/Unix driver vs core split |
| 3 | `audit-security-nodejs` | JS/npm server & child-process vulns | Dynamic loader (`dlopen`/`LoadLibrary`), `sh -c`/`popen`, `Xml.cpp`, deps | `SEC-UNIX-001`, `SEC-BSD-001`, `SEC-SUP-001`, `RES-TOK-001` |
| 4 | `audit-security-code` | Web/backend/DB CSEC catalog | Privileges, injection, XML/serialization, crypto/KDF, temp files | `SEC-RNG-001`, `SEC-WIN-001`, `SEC-WIN-002`, `SEC-TOK-001` |
| 5 | `audit-security-owasp` | OWASP Top 10 (2021) A01–A10 | IOCTL/RPC access control, crypto hygiene, supply-chain/logging | `SEC-KRN-001`, `SEC-RNG-001`, `SEC-SUP-001`, `CMP-MAC-001` |
| 6 | `audit-security-vuln-harness` | Defensive vulnerability hunting workflow | Non-destructive recon -> static sink hunt -> trace validation | Confirmed `MEM-FUSE-001`, `SEC-RNG-001`, `SEC-UNIX-001`, `SEC-WIN-001` |
| 7 | `audit-security-supabase` | Supabase RLS, JWT, PostgREST, Edge Fn | Kernel device ACLs, `RequesterAccess` (`SO_PEERCRED`), App Group IPC | `SEC-KRN-001`, `SEC-MAC-001`, `RequesterAccess` verified safe |
| 8 | `audit-security-llm` | LLM prompt/tool/agency security | Untrusted input -> privileged helper/shell/driver sinks | `SEC-UNIX-001`, `SEC-BSD-001`, `SEC-MAC-002` (UID wrap) |
| 9 | `audit-llm-config-drift` | Model IDs, SDK pins, instruction drift | Build pins, `UPSTREAM.md`, signing timestamps, wolfCrypt flags | `SEC-SUP-001`, `SEC-SUP-002`, `CMP-MAC-001`, `TSE-CI-001` (`Dummy.txt`) |
| 10 | `audit-agent-orchestration-code` | Agent state machines & tool dispatch | `VolumeCreator` / `EncryptionThreadPool` / `FSKitService` worker orchestration | `MEM-FUSE-001`, `REL-FSK-001`, `EncryptionThreadPool` verified safe |
| 11 | `audit-contract-crossrepo` | Multi-repo API/schema contracts | `VeraCrypt-DCS` (`Boot/EFI`), FSKit Swift<->C++, Upstream `.hc` format | `PERF-FSKIT-001`, `DAT-XML-001`, `Boot/EFI/Readme.txt` external seam |
| 12 | `audit-dataflow-pipeline-graph` | Multi-stage ETL DAG & branch invariants | Password/keyfile -> KDF -> Header decrypt -> Block cipher I/O -> Mount | `SEC-KRN-001`, `RES-BOOT-001`, `SEC-TOK-001` |
| 13 | `audit-repo-state-reconciliation` | Docs vs CI vs git/packaging truth | `README.md`, `UPSTREAM.md`, `.github/workflows/*.yml` vs `Tests/` & `Main.make` | `TSE-CI-001` (CI omits macOS/Win + unit suites), `CMP-MAC-001` |
| 14 | `audit-repo-path-consistency` | Path canonicalization & root containment | `/tmp`, `/private/tmp`, `%TEMP%`, `/usr/local`, `/dev/mapper` | `SEC-WIN-001`, `SEC-WIN-002`, `SEC-MAC-001`, `private_tmp_dir.sh` holds |
| 15 | `audit-design-handheld` | Constrained-viewport mobile UX | Windows 16-bit Pre-Boot BIOS/EFI & `TextUserInterface` (TTY) constraints | `RES-BOOT-001`, pre-boot silent/custom message bounds, TUI parity |
| 16 | `audit-design-webapp` | Desktop/web UI affordance & error states | wxWidgets `MainFrame` / `UserInterface` / macOS Disk Utility fallback | `SIG-MAC-001`, `UserPreferences` (`INV-PREF-001`), `--allow-insecure-mount` badge |
| 17 | `audit-equation-sourcebase` | Mathematical / financial / ledger invariants | Volume offset math, XTS sector units, PIM/KDF bounds, BIOS subtraction | `RES-BOOT-001` (`sector + --sectorCount` underflow), `VolumeLayout` & `VolumeCreator` bounds |
| 18 | `audit-flutter-ios` | Apple/iOS bundles, entitlements, platform parity | macOS `LambCrypt.app`, `FSKit` AppEx, `Info.plist`, `notarize.sh`, `postinstall.sh` | `CMP-MAC-001`, `REL-FSK-001`, `SEC-MAC-001` |
| 19 | `audit-go-repo-hardening` | CLI/subprocess/atomic-persistence/signal hardening | CLI `CommandLineInterface`, `Process.cpp`, `XmlWriter`, `Main.make`, signal cleanup | `REC-PREF-001`, `SEC-UNIX-001`, `SEC-BSD-001`, `INV-BLD-001` |
| 20 | `audit-graphdb-design` | Entity graph, edges, identity resolution | Mount <-> Loop/VND <-> DM-Crypt cascade layers & ownership lookup | `CoreLinux` UUID teardown holds; `REL-OBSD-001` bare `throw;` |
| 21 | `audit-kotlin-app` | Typed lifecycle, concurrency, FFI/JNI bridge | C++/Swift/ObjC++ FSKit bridge, `EncryptionThreadPool` & GUI lifecycle | `MEM-FUSE-001`, `REL-FSK-001`, `Thread`/`SyncEvent` drain |
| 22 | `audit-mcp-server` | RPC schema, payload framing, worker ops | `VolumeProtocol` UNIX socket RPC & `CoreService` pipe IPC | `PERF-FSKIT-001` (`getattr` churn + dynamic `VolumeInfo` size), `REL-FSK-001` |
| 23 | `audit-secops-alert-triage` | Signal fidelity, noise vs missed escalation | Driver `Dump()`, `dlerror()` vs `errno`, `CoreMacOSX` silent catch | `RES-TOK-001`, `SIG-MAC-001`, commented Windows crash URL reporter |
| 24 | `audit-secops-detection-coverage` | Telemetry & rule coverage vs threats | Self-tests (`AutoTestAlgorithms`), XML/i18n CI validators, `Tests/` coverage | `TSE-CI-001` (Streebog `burn`, `OpenBSD`, FSKit & IOCTLs unguarded in CI) |
| 25 | `audit-secops-incident-investigation` | Post-incident memory, disk & dump forensics | Key zeroization (`burn`), `DumpFilter` hibernation, temp print files | `SEC-RNG-001`, `SEC-TOK-001`, `SEC-WIN-002` (`PrintHardCopyTextUTF16`) |
| 26 | `audit-secops-threat-hunt` | Adversarial TTP hypothesis hunting | Temp TOCTOU elevation, `appimagetool` fetch, `LoadLibrary`/`dlopen`, HTTP TSA | `SEC-SUP-001`, `SEC-SUP-002`, `SEC-WIN-001`, `SEC-UNIX-001`, `SEC-MAC-001` |

---

## 3. Detailed Skill-by-Skill Adaptation & Code-Scan Findings

### 1. `audit-architecture-drift` (`AID-001..014`)
- **Adaptation Mapping**:
  - `AID-001` (Partial implementation) / `AID-003` (Abandoned architecture) -> Platform `Core*` subclasses and disabled features.
  - `AID-009` (Declared-design contradiction) / `AID-010` (Documentation drift) -> `README.md` / `UPSTREAM.md` vs actual `Main.make` and `Signing/` manifests.
  - `AID-011` (Testing gap) -> Features declared without CI execution.
- **Steps to Reproduce (Static)**: Compare `src/Core/Unix/OpenBSD/CoreOpenBSD.cpp:37-110` against `CoreBase` contract; compare `UPSTREAM.md` and `src/Setup/MacOSX/LambCrypt.entitlements.plist` against `src/Main/Main.make:314-323`.
- **Analysis of the Issue**: `CoreOpenBSD` leaves incomplete stubs (`throw;` on `readOnly` & `GetHostDevices`, `// not sure what this is used for`), causing `std::terminate()` (`REL-OBSD-001`). Separately, `Main.make:314-323` synthesizes an inline `app-entitlements.plist` omitting `disable-library-validation`, drifting from PKCS#11 dynamic loading support (`CMP-MAC-001`). Legacy commented-out telemetry (`Dlgcode.c:3229-3256`) and Windows `sign.bat` still reference `VeraCrypt-*.exe` outputs inside a LambCrypt fork.
- **Theory / Hypothesis / Solution**: Rapid macOS FSKit fork development left non-macOS `Core*` stubs and inline Makefile plist synthesis decoupled from single-source manifests. Enforce a build-time entitlement template merge (`LambCrypt.entitlements.plist` as canonical source) and complete or explicitly disable incomplete `CoreOpenBSD` methods with `NotApplicable(SRC_POS)`.

---

### 2. `audit-architecture-nodejs`
- **Adaptation Mapping**:
  - Event-loop / module dependency direction & ambient config (`ARC-018`) -> `Makefile` exports, native `dlopen`/`LoadLibrary`, and UI -> Core -> Driver -> Crypto layering.
  - Non-blocking worker safety -> `FSKitService.mm` & `FileSystem.swift` dispatcher boundaries.
- **Steps to Reproduce (Static)**: Check `src/Makefile:221-222` (`export LD_LIBRARY_PATH=/usr/local/lib`) and `src/Driver/FSKit/FileSystem.swift:349` calling `VolumeProtocol` sync socket connect per `attributes(of:)`.
- **Analysis of the Issue**: Overwriting `LD_LIBRARY_PATH` in `Makefile:221-222` (`INV-BLD-001`) couples every sub-process cleanly to `/usr/local/lib`. In `FSKit`, Swift filesystem callbacks synchronously establish fresh `VolumeConnection` inspects per `getattr` (`PERF-FSKIT-001`), coupling Finder metadata rate directly to UNIX socket setup.
- **Theory / Hypothesis / Solution**: Layer leaks stem from mixing global env overrides into build rules and lacking a pooled/snapshot client cache in the Swift-to-C++ bridge. Preserve existing `LD_LIBRARY_PATH` and cache `VolumeInfo` per generation in `VolumeConnection`.

---

### 3. `audit-security-nodejs` (`SECN-001..022`)
- **Adaptation Mapping**:
  - `SECN-004` (Dynamic `require`/`import`) -> `dlopen()` / `LoadLibrary()` module loading.
  - `SECN-006` / `SECN-007` (`exec`/`spawn` command/arg injection) -> `sh -c`, `popen()`, `ShellExecute()`.
  - `SECN-019` / `SECN-020` (Supply-chain/lifecycle scripts) -> `wget appimagetool` + `postinstall.sh`.
- **Steps to Reproduce (Static)**: Trace `src/Main/Main.make:759-770`, `src/Core/Unix/CoreUnix.cpp:280-316`, `src/Core/Unix/FreeBSD/CoreFreeBSD.cpp:208-211`, and `src/Common/SecurityToken.cpp:538-559`.
- **Analysis of the Issue**: Hits `SEC-SUP-001` (`wget continuous` `appimagetool` -> `chmod +x` with no digest check), `SEC-UNIX-001` (`sh -c` unquoted `VirtualDevice`), `SEC-BSD-001` (`popen` unquoted `devicePath`), and `RES-TOK-001` (`dlopen` leak + `errno` masking `dlerror()`). *Positive Non-Finding*: Windows `Dlgcode.c` & `Random.c:723-730` & `Setup.c:2894-2900` resolve `System32` absolute DLL paths before `LoadLibrary()` (or use `LOAD_LIBRARY_SEARCH_SYSTEM32` at `Dlgcode.c:4149, 14801`), preventing current-working-directory DLL planting!
- **Theory / Hypothesis / Solution**: Build/POSIX wrappers bypassed the strict `Process::FindSystemBinary` / `sha256sum` discipline used elsewhere in the repo (`openwrt`, `Process.cpp`). Route `blkid`/`fsck` strictly through `argv` / positional parameters and verify pinned SHA-256 hashes on all downloaded build tools.

---

### 4. `audit-security-code` (`CSEC-001..057`)
- **Adaptation Mapping**:
  - `CSEC-015` (Command injection) -> `CoreUnix.cpp:289`, `CoreFreeBSD.cpp:208`.
  - `CSEC-029` / `CSEC-037` (XML parsing & insecure temp files) -> `Main/Xml.cpp`, `Dlgcode.c:10597, 13993, 14378`, `postinstall.sh`.
  - `CSEC-043` / `CSEC-041` / `CSEC-056` (Memory/secret scrub & weak crypto) -> `Random.c:385`, `SecurityToken.cpp:489-500`, `makeself_repro_finalize.py`, `sign*.bat`.
- **Steps to Reproduce (Static)**: Grep `burn(`, `GetTempPath`, `fopen`, `MD5`, `sha1`, and inspect `Random.c:385`, `Dlgcode.c:10597, 13993`, `Main/Xml.cpp:117-124`.
- **Analysis of the Issue**: Produces Confirmed findings `SEC-RNG-001` (`sizeof(sctx)` on `stctx`), `SEC-WIN-001` & `SEC-WIN-002` (predictable `%TEMP%` UAC batch scripts & un-wiped plaintext printouts), `SEC-TOK-001` (`std::string` PIN copy + malformed `CKA_PRIVATE` fail-open), and `SEC-SUP-002` (legacy `sha1`/`MD5`).
- **Theory / Hypothesis / Solution**: Legacy Win32 temp-file helpers and manual C `sizeof` arguments lack compiler/type enforcement. Replace `burn(p, sizeof(q))` with type-safe `burn_var(x)`, migrate Windows UAC helpers off shared `%TEMP%`, and wipe printouts or print via GDI.

---

### 5. `audit-security-owasp` (OWASP Top 10 2021)
- **Adaptation Mapping**:
  - *A01 Broken Access Control* -> `Ntdriver.c` `TC_IOCTL_*`, `RequesterAccess` `SO_PEERCRED`, `SecurityToken` `CKA_PRIVATE`.
  - *A02 Cryptographic Failures* -> `Random.c:385` Streebog stack scrub, `EncryptionModeXTS`, `sign_test.bat /fd sha1`, `makeself` MD5.
  - *A03 Injection* -> `CoreUnix.cpp` `sh -c`, `CoreFreeBSD.cpp` `popen`, `Main/Xml.cpp` `\` escape.
  - *A04 Insecure Design* -> `RemoveDeviceWriteProtection` `%TEMP%` UAC batch pattern; `FSKitService.mm` double-`fork()`.
  - *A08 Software/Data Integrity Failures* -> `Main.make` `appimagetool` unverified fetch; `XmlWriter` non-atomic `CreateWrite`.
  - *A09 Security Logging/Monitoring Failures* -> `CoreMacOSX` silent `catch (...)`, `SecurityToken` `errno` vs `dlerror()`.
- **Steps to Reproduce (Static)**: Map every boundary check in `Ntdriver.c:2934-2955`, `Random.c:385`, `Main.make:759-770`, `CoreMacOSX.cpp:789-805`.
- **Analysis of the Issue**: *A01* caught `SEC-KRN-001` (`ProtectedHidVolPim` unchecked at IOCTL) & `SEC-TOK-001` (`CKA_PRIVATE` size bypass); *A02* caught `SEC-RNG-001`; *A03* caught `SEC-UNIX-001`, `SEC-BSD-001`, `DAT-XML-001`; *A08* caught `SEC-SUP-001` & `REC-PREF-001`; *A09* caught `RES-TOK-001` & `SIG-MAC-001`.
- **Theory / Hypothesis / Solution**: Even offline disk-encryption suites exhibit full OWASP-analog failure classes at IPC, subprocess, XML, and software-update/packaging seams. Applying the P0/P1 list in `gem-hydrogen--audit-all-23NOV2026.md` closes all identified OWASP analogs.

---

### 6. `audit-security-vuln-harness`
- **Adaptation Mapping**: Adopts strictly Phases 1–3 (*Recon -> Hunt -> Validate/Disprove*) without constructing exploit payloads or live attack harnesses.
- **Steps to Reproduce (Static)**: Enumerate all attacker/untrusted-input entrypoints (IOCTLs, env vars `SUDO_UID`/`TMPDIR`, XML configs, PKCS#11 attributes, BIOS sector counts, FSKit socket RPC) -> trace to sinks -> check dominating guards.
- **Analysis of the Issue**: Successfully *validated* `MEM-FUSE-001`, `SEC-RNG-001`, `SEC-UNIX-001`, `SEC-BSD-001`, `SEC-WIN-001`, `RES-BOOT-001`, `SEC-KRN-001`, `SEC-MAC-002` while *disproving* false alarms around `DriveFilter.c:581-735` (which properly validates BootArgs CRC and physical ranges before `MmMapIoSpace`), `RequesterAccess.cpp`, `CoreService.cpp` `chown`, and `Dlgcode.c` `System32` DLL loading.
- **Theory / Hypothesis / Solution**: Systematic dominance-check validation separates real vulnerabilities (`burn(&stctx, sizeof(sctx))`) from already-hardened upstream code (`DriveFilter.c`, `CoreLinux.cpp` mount isolation).

---

### 7. `audit-security-supabase`
- **Adaptation Mapping**:
  - Postgres RLS policies & `SECURITY DEFINER` RPCs -> Privileged OS daemons/drivers (`Ntdriver.c`, `CoreService.cpp`, `FSKitService.mm`).
  - `service_role` leakage -> Privileged `root`/`SYSTEM` helper exposure to unprivileged desktop callers (`--allow-insecure-mount`, `SetFileOwner`, `SystemFavorite`).
- **Steps to Reproduce (Static)**: Audit `Ntdriver.c:2949` (`if (mount->SystemFavorite && !UserCanAccessDriveDevice()) return STATUS_ACCESS_DENIED;`), `RequesterAccess.cpp` (`SO_PEERCRED`), `CoreService.cpp` `chown` guards, `postinstall.sh`, `Dlgcode.c:13993-14026`.
- **Analysis of the Issue**: `Ntdriver.c` `SystemFavorite` check and `CoreService.cpp` `chown` target allowlisting properly enforce server-side authorization (*Holds*). However, Windows UAC `RemoveDeviceWriteProtection` (`SEC-WIN-001`) and macOS `postinstall.sh` (`SEC-MAC-001`) step across user-writable `%TEMP%` / `/usr/local` directories without strict owner-only ACL enforcement.
- **Theory / Hypothesis / Solution**: Equivalent of "RLS enabled on core tables, bypassed via permissive bucket/helper permissions." Harden Windows `%TEMP%` UAC path / eliminate temp script files and enforce root-only checks in `postinstall.sh`.

---

### 8. `audit-security-llm` (`LLM-001..014`)
- **Adaptation Mapping**:
  - `LLM-003` (Improper output handling into shell/SQL/path) -> Subprocess/provider strings (`VirtualDevice`, `devicePath`, `dlerror()`, `title`) flowing unvalidated into `sh -c`, `popen()`, `%TEMP%\<title>`.
  - `LLM-005` / `LLM-006` (Confused-deputy escalation / side-channel leak) -> `SUDO_UID` truncation (`SEC-MAC-002`), stack key residue (`SEC-RNG-001`).
  - `LLM-013` (Tool/plugin supply-chain & provenance) -> Floating `appimagetool` (`SEC-SUP-001`), unentitled third-party PKCS#11 `dlopen` (`CMP-MAC-001`).
- **Steps to Reproduce (Static)**: Trace provider/system output (`blkid`, `VirtualDevice`, `dlopen`, GitHub continuous download) -> privileged consumer.
- **Analysis of the Issue**: Treating derived/external tool strings as trusted syntax produces `SEC-UNIX-001`, `SEC-BSD-001`, `SEC-SUP-001`, and `SEC-WIN-002`.
- **Theory / Hypothesis / Solution**: Treat all metadata strings crossing process/tool boundaries (`VirtualDevice`, `devicePath`, `title`, remote assets) as untrusted data requiring strict argv separation or cryptographic digest pinning.

---

### 9. `audit-llm-config-drift` (`LCD-001..022`)
- **Adaptation Mapping**:
  - Model IDs & beta headers -> Crypto/KDF/backend flags (`WOLFCRYPT_BACKEND`), code-signing SHA-1/timestamp URLs, CI distro/test filenames.
  - Silent default drift (`LCD-009`), credential/env resolution drift (`LCD-017`), instruction/doc rot (`LCD-019`).
- **Steps to Reproduce (Static)**: Compare `.github/workflows/build-linux.yml:218` vs `260`; `UserPreferences.cpp:20-26, 76, 96, 207, 227`; `Main.make:314-323` vs `LambCrypt.entitlements.plist`; `Makefile:221-222`; `Signing/sign_test.bat`.
- **Analysis of the Issue**: Uncovered `TSE-CI-001` (`Dummy.txt` vs `dummy.txt`), `INV-PREF-001` (duplicate `BackgroundTaskEnabled` and fail-open bool `"false"` -> `true`), `CMP-MAC-001` (entitlement generation drift), `INV-BLD-001` (`LD_LIBRARY_PATH` clobber), and `SEC-SUP-002` (legacy SHA-1 dual-sign & HTTP TSA drift).
- **Theory / Hypothesis / Solution**: Hand-copied constants across Makefiles, batch files, CI YAMLs, and C++ preference macros drift whenever one copy is updated. Consolidate single sources of truth (entitlement plist, macro list iteration, pinned tool digests, consistent CI smoke filenames).

---

### 10. `audit-agent-orchestration-code` (`AOC-001..030`)
- **Adaptation Mapping**:
  - Worker pool dispatch, cancellation, graceful drain, orphan cleanup, backpressure -> `EncryptionThreadPool`, `FSKitService.mm` worker daemon, `FuseService` teardown, `Process::ExecuteBounded`.
- **Steps to Reproduce (Static)**: Trace `FuseService::CloseMountedVolume()` (`FuseService.cpp:1155-1168`), `FSKitService.mm:230-235, 515-527`, `EncryptionThreadPool.cpp` (`PoolReferences`, `StopWorkers()`), `Process.cpp` (`ExecuteBounded`).
- **Analysis of the Issue**: `EncryptionThreadPool` and `Process::ExecuteBounded` implement clean worker drain & child reaping. In contrast, `FuseService::CloseMountedVolume()` forcibly `delete`s a live shared worker target (`MEM-FUSE-001`) instead of draining holders cleanly, and `FSKitService.mm` double-`fork()`s post-ObjC init with fd `0..2` unallocated (`REL-FSK-001`).
- **Theory / Hypothesis / Solution**: Safe multi-worker orchestration requires cooperative quiescence/refcount drainage (`EncryptionThreadPool` model) rather than raw manual destruction or unsafe post-runtime `fork()`.

---

### 11. `audit-contract-crossrepo` (`XREP-001..016`)
- **Adaptation Mapping**:
  - Cross-repo boundaries: (1) LambCrypt <-> Upstream `VeraCrypt` `.hc` & `/dev/mapper/veracrypt` compatibility (`UPSTREAM.md`), (2) `LambCrypt` <-> external `VeraCrypt-DCS` EFI bootloader (`src/Boot/EFI/Readme.txt` referencing VS2010 / `UDK2015` / `VeraCrypt_1.18`), (3) Swift `FileSystem.swift` <-> C++ `VolumeProtocol.cpp`, (4) `validate_translation_formats.py` manual `PRINTF_KEYS` allowlist <-> `LangString[...]` callers.
- **Steps to Reproduce (Static)**: Inspect `src/Boot/EFI/Readme.txt:1-16`, `src/Driver/FSKit/FileSystem.swift:349` vs `VolumeProtocol.cpp:321-343`, and `.github/workflows/validate_translation_formats.py:1-60`.
- **Analysis of the Issue**:
  1. `Boot/EFI/Readme.txt` pins external `VeraCrypt-DCS` (`VeraCrypt_1.18` branch) and is opaque inside this checkout (`Boot/Windows` vs `Boot/EFI` divergence).
  2. `FileSystem.swift` <-> `VolumeProtocol.cpp` exhibits `XREP-012` / `TMP-001`: `ReadControl` re-serializes `VolumeInfo` dynamically on read after `attributes(of:)` reported an earlier size (`PERF-FSKIT-001`).
  3. `validate_translation_formats.py` explicitly notes manual sync requirement (`PRINTF_KEYS`), risking drift if new formatted strings omit registration.
- **Theory / Hypothesis / Solution**: Snapshot control file payload per open/generation across the Swift-C++ FSKit seam, document EFI DCS commit pinning accurately, and automate extraction of `wxString::Format` / `StringCbPrintf` keys rather than maintaining a manual Python set.

---

### 12. `audit-dataflow-pipeline-graph` (Gates 0–7)
- **Adaptation Mapping**: Model VeraCrypt/LambCrypt as a linear/branching dataflow DAG:
  `[Input: Password/PIM/Keyfile/Token]` -> `[KDF: Pkcs5Kdf / Argon2]` -> `[Header: VolumeHeader]` -> `[Queue/Filter: DriveFilter/EncryptedIoQueue/BootEncryptedIo/VolumeProtocol]` -> `[Storage: HostFile/Disk]`.
- **Steps to Reproduce (Static)**: Trace graph edges across `Ntdriver.c:2934` -> `Ntvol.c:622-647`; `Random.c:361-387`; `BootEncryptedIo.cpp:82-93`.
- **Analysis of the Issue**: Gate 4–6 edge-branch expansion exposed three broken DAG branch transitions: `ProtectedHidVolPim` escaping IOCTL boundary validation (`SEC-KRN-001`), `STREEBOG` case skipping full `burn()` (`SEC-RNG-001`), and `BootEncryptedIo::WriteEncryptedSectors` exiting on the hidden-volume overlap branch without releasing `SectorBuffer` (`RES-BOOT-001`).
- **Theory / Hypothesis / Solution**: Secondary/branching paths (`hiddenVolume`, `ProtectedHidVolPim`, less-common `STREEBOG`) receive less manual scrutiny than primary normal-volume AES/SHA-512 paths. Adding branch-coverage unit checks across every KDF and volume-type edge closes the gap.

---

### 13. `audit-repo-state-reconciliation`
- **Adaptation Mapping**: Reconcile declared capabilities (`README.md`, `UPSTREAM.md`, `.github/workflows/*.yml`, `Tests/`) against actual build, CI, and test reality.
- **Steps to Reproduce (Static)**: List `.github/workflows/*.yml` vs `Tests/*` and `src/Build/*`.
- **Analysis of the Issue**: Despite `README.md` emphasizing macOS 26 Tahoe Apple silicon FSKit as LambCrypt's primary focus, `.github/workflows/` runs **only** Linux x86_64/s390x builds, `wxWidgets` builds, and XML validation — **zero macOS builds, zero Windows builds, and zero `Tests/test_*.py` / `Tests/*.cpp` unit runs execute in CI** (`TSE-CI-001`).
- **Theory / Hypothesis / Solution**: CI automation lagged behind macOS/FSKit test authoring (`test_fskit_volume_protocol.py`, `test_macos_*.py`). Add a macOS build + non-privileged unit test CI workflow so repo state stays verified continuously.

---

### 14. `audit-repo-path-consistency`
- **Adaptation Mapping**: Trace all filesystem paths across `/tmp`, `/private/tmp`, `%TEMP%`, `/usr/local`, `/media`, and build trees (`PARENTDIR`).
- **Steps to Reproduce (Static)**: Compare `src/Build/Tools/private_tmp_dir.sh`, `src/Core/Unix/CoreUnix.cpp:1514-1534`, `src/Setup/MacOSX/postinstall.sh:3-14`, `src/Common/Dlgcode.c:10597, 13993, 14378`, `.github/workflows/build-linux.yml:218 vs 260`.
- **Analysis of the Issue**: Unix runtime/build paths show rigorous path-consistency hardening (`private_tmp_dir.sh`, `CoreUnix.cpp` aux mount templates, `MountedFilesystem.h` `/private/tmp/lambcrypt-fskit.`), whereas Windows `Dlgcode.c` (`SEC-WIN-001`, `SEC-WIN-002`, `veracrypt_driver_setup.inf`) and macOS `postinstall.sh` (`SEC-MAC-001`) still construct predictable shared-temp or `/usr/local` paths, and `build-linux.yml` mixes `Dummy.txt` vs `dummy.txt`.
- **Theory / Hypothesis / Solution**: Incremental hardening focused on Linux/macOS runtime `/tmp` without retrofitting legacy Windows `GetTempPath()` helpers or macOS `.pkg` postinstall scripts. Standardize Windows helper temp creation on private ACL'd directories / pipe-based `diskpart` and fix `Dummy.txt` consistency.

---

### 15. `audit-design-handheld` (8 Gates -> Constrained BIOS Pre-Boot & CLI/TUI)
- **Adaptation Mapping**: Constrained-screen/touch handheld gates map onto **16-bit BIOS real-mode Pre-Boot (`src/Boot/Windows/`)** and **`TextUserInterface` (TTY terminal)** environments where memory, screen columns, and error recovery are severely constrained.
- **Steps to Reproduce (Static)**: Inspect `src/Boot/Windows/BootConfig.cpp:40-83` and `src/Boot/Windows/BootEncryptedIo.cpp:79-144`.
- **Analysis of the Issue**: `BootConfig.cpp:57-68` copies `CustomUserMessage` cleanly (`TC_BOOT_SECTOR_USER_MESSAGE_MAX_LENGTH` + null terminator) before printing/disabling output. However, `BootEncryptedIo.cpp:82-93` deadlocks/leaks `SectorBuffer` if a partial hidden-volume boundary error occurs (`RES-BOOT-001`), leaving pre-boot interaction stalled without recovery signaling.
- **Theory / Hypothesis / Solution**: Constrained pre-OS environments cannot afford resource leaks on error returns. Fix `ReleaseSectorBuffer()` on error exit and guard `sectorCount == 0`.

---

### 16. `audit-design-webapp` (6 Gates -> Desktop wxWidgets / Win32 UI)
- **Adaptation Mapping**: Webapp layout/state/error-honesty/affordance gates map onto `GraphicUserInterface.cpp`, `Forms/`, `UserPreferences.cpp`, and `CoreMacOSX.cpp`.
- **Steps to Reproduce (Static)**: Inspect `src/Main/GraphicUserInterface.cpp:1330-1335` (`INSECURE_MODE` title badge), `src/Core/Unix/MacOSX/CoreMacOSX.cpp:789-805`, and `src/Main/UserPreferences.cpp`.
- **Analysis of the Issue**: Positive control: GUI visibly updates main window title with `LangString["INSECURE_MODE"]` when `--allow-insecure-mount` is active (`1331-1334`), preventing silent security downgrade. Defect found (`SIG-MAC-001`): `CoreMacOSX` catches `(...)` on automated fsck preparation and opens `Disk Utility.app` silently, violating the *Actionable Error & Honest State* gate.
- **Theory / Hypothesis / Solution**: Fallback UX masked an unexpected failure behind a generic utility launch. Surface the exact verify/repair error reason before offering Disk Utility.

---

### 17. `audit-equation-sourcebase` (Lenses A/B/C -> Cryptographic Layout & Offset Math)
- **Adaptation Mapping**:
  - *Lens A (Structural/Root)* -> Exact formulas in `VolumeLayout.cpp`, `VolumeCreator.cpp`, `Pkcs5Kdf.cpp`, `EncryptionModeXTS.cpp`.
  - *Lens B (Forensic Trust-Boundary)* -> Unchecked integer subtraction/narrowing on external inputs.
  - *Lens C (Adjudication)* -> Agreement between writer layout, BIOS pre-boot sector math, and kernel I/O bounds.
- **Steps to Reproduce (Static)**: Audit `src/Volume/VolumeLayout.cpp:88-96, 139-145, 188-202`; `src/Core/VolumeCreator.cpp:176, 326, 330-333`; `src/Boot/Windows/BootEncryptedIo.cpp:138-144`; `src/Driver/Fuse/FuseService.cpp:1740, 1745`.
- **Analysis of the Issue**:
  1. `VolumeLayoutV2Normal::GetMaxDataSize` (`VolumeLayout.cpp:141-144`) and `VolumeLayoutV2Hidden::GetMaxDataSize` (`198-201`) cleanly guard underflow (`if (volumeSize < TC_TOTAL_VOLUME_HEADERS_SIZE) return 0;`). (Note `VolumeLayoutV1Normal::GetDataSize` at `93-96` subtracts `GetHeaderSize()` without underflow guard, though `V1` is legacy read-only mount.)
  2. **Confirmed Equation Defect (`RES-BOOT-001`)**: `BootEncryptedIo.cpp:140` computes `uint64 readWriteEnd = sector + --sectorCount;` — when `sectorCount == 0`, `--sectorCount` wraps unsigned 16-bit to `65535`, breaking interval math!
  3. **Confirmed Narrowing Defect (`SEC-MAC-002`)**: `FuseService.cpp:1740, 1745` narrows `uint64` to 32-bit `uid_t`/`gid_t` (`x mod 2^32`).
- **Theory / Hypothesis / Solution**: Off-by-one inclusive end-sector arithmetic (`start + count - 1`) without a `count == 0` guard universally underflows unsigned types. Guard `sectorCount == 0` and enforce range bounds before integer width narrowing.

---

### 18. `audit-flutter-ios` (5 Gates -> macOS App / FSKit Bundle / Signing / Notarization)
- **Adaptation Mapping**: Maps iOS/macOS bundle IDs, provisioning profiles, entitlements, `Info.plist`, dynamic library loading, and platform parity onto `LambCrypt.app` + `LambCryptFSKit.appex` + `Main.make` + `notarize.sh` + `postinstall.sh`.
- **Steps to Reproduce (Static)**: Audit `src/Main/Main.make:314-323`, `src/Setup/MacOSX/*.entitlements.plist`, `src/Driver/FSKit/Info.plist`, `src/Setup/MacOSX/signing.env.example`, and `src/Setup/MacOSX/postinstall.sh`.
- **Analysis of the Issue**: Caught `CMP-MAC-001` (Hardened Runtime missing `com.apple.security.cs.disable-library-validation` in `Main.make`-generated `app-entitlements.plist`), `SEC-MAC-001` (`postinstall.sh` legacy `/usr/local/lib/libosxfuse.2.dylib` & `/usr/local/bin/lambcrypt` symlink checks), and `REL-FSK-001` (FSKit daemonization fd/fork safety).
- **Theory / Hypothesis / Solution**: Apple platform hardening requires single-source entitlement control and App Group container IPC without legacy `/usr/local` symlink assumptions or Foundation `fork()` without `exec()`.

---

### 19. `audit-go-repo-hardening` (`GOH-001..015`)
- **Adaptation Mapping**: Every `GOH-*` rule translates cleanly onto LambCrypt's CLI/service C++ & build scripts:
  - `GOH-002` (Secret exposure) -> `SEC-RNG-001`, `SEC-TOK-001`, `SEC-WIN-002`.
  - `GOH-004`/`005` (Process-tree/signal cleanup) -> `FSKitService.mm`, `FuseService.cpp`, `Process::ExecuteBounded` (*Holds*).
  - `GOH-010` (Overbroad shelling) -> `SEC-UNIX-001`, `SEC-BSD-001`.
  - `GOH-012` (Non-atomic persistence) -> `REC-PREF-001` (`XmlWriter::Open(..., File::CreateWrite)`).
  - `GOH-013` (Env precedence surprise) -> `INV-BLD-001` (`LD_LIBRARY_PATH` overwrite in `Makefile:221-222`).
  - `GOH-015` (Missing operational tests) -> `TSE-CI-001`.
- **Steps to Reproduce (Static)**: Cross-check `Xml.cpp:158`, `UserPreferences.cpp:261-285`, `CoreUnix.cpp:289`, `CoreFreeBSD.cpp:208`, `Makefile:221-222`.
- **Analysis of the Issue**: High yield: `GOH-012` directly spotlighted non-atomic config overwrite (`XmlWriter`), `GOH-010` flagged `sh -c`/`popen`, and `GOH-013` flagged `LD_LIBRARY_PATH` clobbering.
- **Theory / Hypothesis / Solution**: CLI/service reliability contracts are language-agnostic across Go and C++. Stage XML saves via temp+fsync+rename, pass subprocess args via `argv`, and append rather than clobber build env vars.

---

### 20. `audit-graphdb-design` (`GDB-001..026`)
- **Adaptation Mapping**: Models Linux/BSD/macOS volume mount graphs (`Volume` -> `AuxMount` -> `Loop/VND` -> `dm-crypt` cascade layers `_0.._n-1` -> `Filesystem Mount`) as an entity-relationship graph focusing on `GDB-004` (Sync/drift blindness), `GDB-012` (Identity-resolution gap), and `GDB-022` (Idempotent cleanup).
- **Steps to Reproduce (Static)**: Audit `src/Core/Unix/Linux/CoreLinux.cpp:925-995` and `src/Core/Unix/OpenBSD/CoreOpenBSD.cpp:47-109`.
- **Analysis of the Issue**: *Positive verification on Linux*: `CoreLinux` resolves cascade graph nodes (`_0.._n-2`), holds the underlying loop FD via `OpenLoopDeviceUnder` + `SetLoopDeviceAutoClear` before `RemoveDeviceMapperDevice(..., serialInstanceNumber)` so concurrent/partial mounts are never confused (`GDB-012` & `GDB-022` *Hold*). Conversely, OpenBSD (`CoreOpenBSD`) only scans static slots `vnd0..vnd3`, throws raw strings when full, and crashes on `GetHostDevices()` (`REL-OBSD-001`).
- **Theory / Hypothesis / Solution**: Kernel object graphs must bind teardown identity via unique instance UUIDs (`CoreLinux` model) and return structured graph-enumeration/not-applicable errors (`CoreOpenBSD` repair).

---

### 21. `audit-kotlin-app`
- **Adaptation Mapping**: Maps Android/Kotlin structured concurrency, coroutine cancellation, JNI C++ bridges, and lifecycle leaks onto LambCrypt's multi-threaded C++ GUI (`GraphicUserInterface.cpp`), `EncryptionThreadPool`, and Swift <-> C++ FSKit FFI (`FileSystem.swift` <-> `VolumeProtocol.cpp` <-> `FSKitService.mm`).
- **Steps to Reproduce (Static)**: Inspect `src/Driver/Fuse/FuseService.cpp:1155-1168`, `src/Driver/FSKit/FSKitService.mm:515-527`, and `EncryptionThreadPool.cpp`.
- **Analysis of the Issue**: Caught `MEM-FUSE-001` (manual `delete` across shared multi-thread ownership breaking structured lifecycle) and `REL-FSK-001` (`fork()` inside multi-thread-capable ObjC++/Foundation runtime), whereas `EncryptionThreadPool` maintains structured refcount/event drainage.
- **Theory / Hypothesis / Solution**: Multi-language/threaded apps require unambiguous ownership across worker cancellation and FFI boundaries. Enforce thread join/drain before destruction and `posix_spawn` instead of post-init `fork()`.

---

### 22. `audit-mcp-server` (Phase A0–A6)
- **Adaptation Mapping**: Maps MCP tool/resource schemas, per-call context/serialization overhead, and stdio/descriptor safety (`0,1,2` corruption) onto LambCrypt's two internal RPC servers: `FSKit` (`VolumeProtocol.cpp` <-> `VolumeConnection.swift`) and `CoreService` (`CoreService.cpp` <-> `RequesterAccess.cpp`).
- **Steps to Reproduce (Static)**: Trace `FSKitService.mm:232-235` (fds `0..2`), `FileSystem.swift:349`, and `VolumeProtocol.cpp:321-343`.
- **Analysis of the Issue**:
  - *Stdio Descriptor Hygiene* (`FSKitService.mm:232-235`): Closing fds `0..2` without `/dev/null` leaves descriptors `0, 1, 2` assignable to the RPC socket (`REL-FSK-001`), the classic MCP stdio-server corruption bug (`stderr`/`NSLog` corrupting framing)!
  - *RPC Payload & Setup Cost*: `attributes(of:)` reconnects/inspects per `getattr`, while `ReadControl` recomputes `VolumeInfo` bytes dynamically (`PERF-FSKIT-001`), analogous to non-idempotent/non-cached MCP resource reads changing size between `stat` and `read`.
- **Theory / Hypothesis / Solution**: Any binary speaking structured RPC over FDs/sockets must reserve fds `0..2` to `/dev/null` (`RequesterAccess.cpp` already does this!) and keep inspect/read metadata generation-consistent.

---

### 23. `audit-secops-alert-triage`
- **Adaptation Mapping**: Evaluates operator/kernel alert & error signal fidelity (`SIG-*`) to distinguish actionable alerts from dropped or misleading errors.
- **Steps to Reproduce (Static)**: Inspect `src/Common/SecurityToken.cpp:538-559`, `src/Core/Unix/MacOSX/CoreMacOSX.cpp:789-805`, `src/Common/Dlgcode.c:3229-3256`, and `src/Setup/MacOSX/postinstall.sh:16`.
- **Analysis of the Issue**: `SecurityToken.cpp` reports `errno` instead of `dlerror()` on `dlopen()` failure (`RES-TOK-001`), `CoreMacOSX.cpp` swallows verify/repair exceptions silently into Disk Utility (`SIG-MAC-001`), and `postinstall.sh` ignores symlink errors and exits `0` (`SEC-MAC-001`).
- **Theory / Hypothesis / Solution**: Silenced catch blocks and wrong error-domain capture (`errno` vs `dlerror`) destroy triage signal. Propagate exact backend failure strings (`dlerror()`, typed `Exception`) to operator UI/stderr.

---

### 24. `audit-secops-detection-coverage`
- **Adaptation Mapping**: Evaluates what security/reliability bugs existing CI checks, runtime self-tests (`AutoTestAlgorithms()`), and `Tests/` catch vs what threat/defect classes have **zero automated detection** in CI.
- **Steps to Reproduce (Static)**: Audit `.github/workflows/*.yml`, `Tests/*.py`, `src/Driver/DumpFilter.c:112` (`AutoTestAlgorithms()`), and `.github/workflows/validate_translation_formats.py`.
- **Analysis of the Issue**: `DumpFilter.c:112` & `CoreLinux.cpp:1423` perform strong runtime crypto self-checks, and `validate_translation_formats.py` catches format-string mismatches cleanly. However, CI executes **zero** tests covering `SEC-RNG-001` (Streebog `burn`), `MEM-FUSE-001`, `SEC-KRN-001` (`ProtectedHidVolPim`), `REL-OBSD-001`, or `Tests/test_fskit_volume_protocol.py` (`TSE-CI-001`).
- **Theory / Hypothesis / Solution**: Detection exists in isolated developer scripts (`Tests/`) rather than automated CI gates. Promote non-privileged C++/Python unit harnesses into mandatory CI workflows.

---

### 25. `audit-secops-incident-investigation`
- **Adaptation Mapping**: Evaluates forensic artifact & key-residue resilience assuming a host disk image, swap/hibernation file, crash dump, or `%TEMP%` directory is examined post-incident.
- **Steps to Reproduce (Static)**: Audit `Random.c:385`, `SecurityToken.cpp:489-500`, `Dlgcode.c:10588-10646`, `DumpFilter.c:48-55, 291-315`, and `DriveFilter.c:600-733`.
- **Analysis of the Issue**: *Strong forensic controls*: `DumpFilter.c` encrypts hibernation/crash writes at `HIGH_LEVEL` and `RtlSecureZeroMemory`s scratch buffers; `DriveFilter.c` burns `BootArgs` & `CryptoInfo` physical mappings. *Forensic Gaps Found*: `Random.c:385` leaves trailing `STREEBOG_CTX` bytes on stack (`SEC-RNG-001`), `SecurityToken.cpp` risks unburned `std::string` PIN copies (`SEC-TOK-001`), and `Dlgcode.c:10597-10643` leaves un-wiped plaintext print files in `%TEMP%` after `Sleep(6000)` (`SEC-WIN-002`).
- **Theory / Hypothesis / Solution**: Forensic confidentiality fails at the weakest residual copy. Fix `burn(&stctx, sizeof(stctx))`, move PIN handling to `SecureBuffer`, and eliminate plaintext disk temp files in `PrintHardCopyTextUTF16`.

---

### 26. `audit-secops-threat-hunt`
- **Adaptation Mapping**: Runs five proactive defensive threat-hunt hypotheses against static code sinks:
  1. *H1 — Build Tool Poisoning*: Unverified remote binary execution in build Makefiles/scripts -> **Confirmed Hit (`SEC-SUP-001`)** at `Main.make:759-770` (`wget` mutable `continuous` `appimagetool` + `chmod +x`). (Disproved on OpenWrt/CI wxWidgets, which enforce `sha256sum`.)
  2. *H2 — Temp/Elevation Hijack*: Fixed paths in shared `TEMP` / `/usr/local` passed to elevated execution -> **Confirmed Hit (`SEC-WIN-001`, `SEC-MAC-001`)** at `Dlgcode.c:13993-14026, 14378` and `postinstall.sh:3-14`.
  3. *H3 — Shell Argument Splitting / Injection*: Device/volume paths into `sh -c` or `popen` -> **Confirmed Hit (`SEC-UNIX-001`, `SEC-BSD-001`)** at `CoreUnix.cpp:280-316` & `CoreFreeBSD.cpp:208-211`.
  4. *H4 — DLL/Dylib Sideloading*: Unqualified `LoadLibrary`/`dlopen` -> **Disproved on Windows (`Dlgcode.c` uses `System32` / `LOAD_LIBRARY_SEARCH_SYSTEM32`)**; **Flagged on macOS Entitlement Drift (`CMP-MAC-001`)**.
  5. *H5 — Legacy Transport / Verification Downgrade*: HTTP downloads/TSA, SHA-1, MD5 -> **Confirmed Hit (`SEC-SUP-002`)** across `sign*.bat` HTTP TSA + test `/fd sha1` and `makeself_repro_finalize.py` MD5-only (`CRCsum="0000000000"`).
- **Theory / Hypothesis / Solution**: Hypothesis-driven code hunting systematically pinpoints non-obvious build, temp-file, and legacy-shell weak links that module-by-module reading often overlooks.

---

## 4. Explicit Exclusion Note
- **`audit-playtest-app`**: Deliberately NOT adapted or executed in compliance with the user prompt constraint (`Don't rum playtest`). All findings above derive strictly from static source inspection.
