# VeraCrypt (LambCrypt fork) — Full Audit Report

**Report ID:** `mistral-audit-all-23NOV2026`
**Date:** 23 November 2026
**Repository:** `/Users/eric/Work/vscode/VeraCrypt` (fork of VeraCrypt rebranded "LambCrypt")
**Audited HEAD:** `954a10b9` — `build(macos): add FSKit packaging verification and signing options`
**Method:** agent-skills catalog exhaustive audit-suite (13 required lenses + 19 applicable/adapted standalone skills), executed as a **static code scan only** by 20 independent read-only audit agents
**Authority:** read-only. No code was modified, no builds/tests/application were executed, no playtest was run.
**Evidence basis:** `src/`, `Tests/`, `.github/` source code only. No prior audit reports, bug logs, migration notes, or session logs were used as evidence (BUGLOG.md, FSKIT-MIGRATION.md, SECURITY-REPAIR-PLAN.md, SOURCE-AUDIT-2026-11-21.md, Tests/README-macos-lifecycle.md were excluded from the evidence set by mandate).

---

## 0. Executive Summary

The audit ran the full agent-skills catalog audit-suite: **13 required lens skills, 10 applicable standalone audits, 3 explicitly adapted out-of-domain skills**, delegated to 20 independent child auditors, producing **~150 distinct findings** (≈35 at High/Medium-high severity) plus a large verified-strength inventory.

The audit's four headline conclusions (each independently corroborated by multiple lenses — see §5):

1. **Cross-instance volume concurrency is unguarded outside Linux.** The double-mount guard is check-then-act, file locking is compiled out (`#if 0`), and the new FSKit backend keeps its mount-locks in a *per-user* app-group container. Two read-write mounts of the same container (fast-user-switching, or a file container on a network share) cause racing XTS read-modify-write sector updates — **silent cross-instance data corruption**. *(CON-VC-001, CON-VC-002, NEG-002/F7, INV-002/014 — four independent lenses.)*
2. **Interrupted credential changes roll back silently.** `ChangePassword` durably commits the primary header *before* the backup header. A crash in between leaves the backup header under the **old** password — and the CLI automatically falls back to the backup header on wrong-password retries, so an interrupted rotation can leave the old credential working with no signal. *(TMP-001, STT-VC-001, DAT-VC-001, STT-003+CAS-006 — four independent lenses.)*
3. **Mount discovery lies in both directions, by platform.** On Linux a failed control-file read makes a live mounted volume **silently vanish** from the inventory (so "Dismount All" misses it, and it can be re-mounted). On macOS the same condition aborts **all** volume discovery (healthy volumes become unlistable/undismountable), and under I/O load the FSKit 1-second control deadline turns unrelated mounts into spurious failures. *(CAS-008, CAS-006/STT-004, FSR-004, FSR-005, REL-010/011, NEG F8 — six independent observations.)*
4. **The new FSKit backend is a young parallel abstraction that silently dropped hardening its FUSE sibling has.** No encryption thread pool start (single-threaded crypto — confirmed by grep: zero `EncryptionThreadPool` references in `src/Driver/FSKit/`), no control-request retries, stdout/stderr closed so worker diagnostics are sunk, build-wrapper and CI provide no path to compile or test it, and elevated (device-hosted) mounts are architecturally impossible under its unprivileged-session invariant, contradicting the repo's own declared elevation routing. *(ARC-019/022, NEG-004/006+NEG-008, NEG-003(fd), ARC-VC-001/002/004.)*

Additionally, the **Windows self-extracting installer** carries the single highest-impact parsing defect found: unsigned appended payload walked with attacker-controlled lengths, no bounds checks, and `..\`-tolerant extraction at elevated privilege (IOP-001/IOP-002), and **FreeBSD FUSE writes report failed writes as full success** (CAS-009/REL-011/FSR-VC-001), a silent-data-loss mechanism.

The CI/CD trust chain itself is clean (pinned actions, least-privilege tokens, SHA-gated fetches, no secrets — verified end-to-end); the credible release-integrity paths are the committed code-signing test PFX material, the committed prebuilt WHQL-signed driver binaries, and the absence of any private vulnerability disclosure channel.

---

## 1. Scope & Constraints

| Item | Value |
|---|---|
| Codebase | ~275 k LOC; 240 `.c`, 147 `.cpp`, 323 `.h`, ObjC++/Swift in `src/Driver/FSKit` |
| Active development surface | macOS FSKit driver (`src/Driver/FSKit`, 8 latest commits) |
| Audit mode | Static code scan only — reading + grep only |
| Forbidden actions | Builds; test execution; app runs; playtests; file modification; reading prior bug/audit/migration docs or session logs as evidence |
| Coverage limits (honest gaps) | `src/Boot` UEFI bootloader header parsing, full Windows kernel driver internals, `src/Mount`/`src/Format`/`src/Common` Windows GUI (~45 k LOC, grep-sampled), vendored `libzip/lzma/zlib` internals, Argon2/wolfCrypt internals — each flagged for dedicated follow-up by the audit agents |

---

## 2. Method — Audit-Suite Selection & Coverage Matrix

### 2.1 Selection

`search_skills` was called with an exhaustive-audit intent and `repo_path`; the catalog returned an **audit-suite selection** (`selection_mode: multi_skill`, exhaustive), with: 13 required lens skill IDs, ~40 standalone candidates to triage, zero repository exclusions. Note: the catalog's semantic index was stale, so the call ran in `deterministic_fallback` mode with authored/keyword scoring preserved (issue noted in §8).

### 2.2 Required lenses (all 13 loaded and run)

| Lens skill | Executed by | Key findings (see §4) |
|---|---|---|
| audit-architecture-seam | lens-arch | ARC-017 protocol duplication, ARC-019 pool-start parity, NEG-008 FSKit CI blindness |
| audit-dataflow-cascade | lens-dataflow-cascade | CAS-008 Linux silent drop, CAS-006 macOS all-or-nothing, CAS-009 FreeBSD fake success |
| audit-compliance-posture | lens-gui | CMP-003 hidden-volume claim vs. estimate; CI advisory gap |
| audit-dataflow-concurrency | lens-dataflow-conc | CON-VC-001/002/003/004/006 |
| audit-dataflow-integrity | lens-dataflow-conc | DAT-VC-001 header split, DAT-VC-002 header-before-data |
| audit-dataflow-input-output | lens-dataflow-io | IOP-001/002 installer parsing, IOP-004 no-op guard |
| audit-invariant-sync | lens-invariant | INV-001 prefix triplication, INV-005 wire protocol duplication, INV-002/014 mount exclusivity divergence |
| audit-negative-space | lens-arch | NEG-002 per-user lock scope, NEG-003 fd/diagnostic loss, NEG-008 FSKit rot |
| audit-reliability | lens-invariant | REL-005 stuck-child gate, REL-012 swallowed teardown, REL-010 SUDO_UID |
| audit-security | lens-security | SEC-VC-001 blkid popen, SEC-VC-002 mountprog, SEC-VC-003 LD_LIBRARY_PATH + large PASS inventory |
| audit-dataflow-state-transition | lens-dataflow-cascade | STT-003 half-disassembled dismount, STT-003/011 creation, STT-005 RO downgrade |
| audit-dataflow-temporal | lens-dataflow-io | TMP-001 backup-header rollback, TMP-002 era-mixed VolumeInfo |
| audit-workflow-gui | lens-gui (+adapt-design-webapp) | WFG-008 fake success hotkey, WFG-007 fail-open validation, WFG-002/WFG-003 destructive UX |

### 2.3 Applicable standalone audits (triaged in, loaded and run)

`audit-security-vuln-harness` (static-only, partial), `audit-security-repo-posture` + `audit-security-repo-triage`, `audit-memory-lifecycle` + `audit-resource-lifecycle`, `audit-failsafe-readiness` + `audit-recovery-idempotency`, `audit-operator-signal` + `audit-contract-internalapi`, `audit-architecture-drift` + `audit-repo-path-consistency` + `audit-repo-state-reconciliation`, `audit-deadcode-cleanup` + `governance-code-polish` (inventory-only, both skills carry repair authority — clamped to read-only per mandate), `audit-dependency-criticality` + `audit-dataflow-pipeline-graph`, `audit-performance-profile` + `audit-optimization-opportunities`, `audit-testsuite-economics`.

### 2.4 Excluded standalones (recorded per catalog instruction)

`audit-security-supabase`, `audit-security-llm`, `audit-security-nodejs`, `audit-architecture-nodejs`, `audit-llm-config-drift`, `audit-agent-orchestration-code`, `audit-contract-crossrepo` (single repo), `audit-equation-sourcebase` (data-pipeline surface), `audit-pipeline-externalapi` (no external API consumption), `audit-flutter-ios`, `audit-design-handheld`, `audit-kotlin-app`, `audit-graphdb-design`, `audit-mcp-server`, `audit-go-repo-hardening` (wrong stacks), `audit-secops-*` ×4 (SOC telemetry surfaces; code-scan-only mandate excludes), `audit-playtest-app` (**explicitly excluded by user: "don't run playtest"**), `audit-multiagent-consensus` (consensus overlay not requested by selector or user).

### 2.5 Adapted skills (per user request — see companion report)

`audit-security-code` (web backends → C/C++ system code), `audit-security-owasp` (web app → desktop/driver app), `audit-design-webapp` (web UI → wxWidgets desktop GUI). Adaptation detail and adaptation-attributable findings are in `mistral-auditskill-analysis-23NOV2026.md`.

---

## 3. Steps to Reproduce This Audit

1. **Load the catalog skill**: load `agent-skills-catalog`; then call `tools.mcp_agent_skills.search_skills` with query *"full comprehensive exhaustive audit scan of the entire repository, report only, no code changes"*, `repo_path: /Users/eric/Work/vscode/VeraCrypt`, `limit: 20` (values >20 are rejected by the tool). The response contains `selection.required_lens_skill_ids` (13), `selection.standalone_candidates_to_triage` (~40), and the instruction to triage each candidate's applicability gate and record exclusions.
2. **Triage the standalone candidates** by surface/target against the repo (C/C++ desktop+driver crypto app). Record applicable/excluded in a coverage matrix (§2.2–2.4).
3. **Load each selected skill**: `tools.mcp_agent_skills.load_skill({skill_id})`, then load its `required_shared_contracts` (`000_common/audit-base/*`) via `tools.mcp_agent_skills.load_skill_file({skill_id, path})` — relative `000_common/...` paths only (absolute paths are rejected).
4. **Run each skill's methodology as a static code scan** with these binding rules: (a) every finding cites `path:line` + a verbatim snippet read from `src/`, `Tests/`, `.github/`; (b) no build, no test run, no app execution, no playtest; (c) never open BUGLOG.md / FSKIT-MIGRATION.md / SECURITY-REPAIR-PLAN.md / SOURCE-AUDIT-2026-11-21.md / Tests/README-macos-lifecycle.md / any `*audit*`/`*report*`/`*buglog*`/`*migration*` file / session logs; (d) runtime-dependent confidence capped per the skill's confidence calibration (static evidence ⇒ code-property "Confirmed", runtime manifestation "Likely"/"Plausible" at most).
5. Systematic pattern sweeps used per lens (representative, re-runnable):
   - `grep -rn "catch (...)" src/` (~236 hits), empty-catch walks; grep for `#if 0` (43+ hits), `popen|system|exec`, `sprintf|strcpy|memcpy`, `SUDO_UID|getenv`, `flock|O_EXCL`, `sigaction`, `EncryptionThreadPool`, `losetup|hdiutil|diskutil`, `FSKit::|FuseService::` call graph, branding strings (`veracrypt|VeraCrypt|lambcrypt|LambCrypt`), version literals across `.rc`/plists/`Tcdefs.h`, i18n key reference analysis of `Language.xml`.
   - Deep full reads of: `src/Driver/FSKit/*` (all files), `src/Driver/Fuse/FuseService.cpp` (1,846 L), `src/Core/Unix/CoreUnix.cpp` (~1,944 L), `src/Core/Unix/MacOSX/CoreMacOSX.cpp` (994 L), `src/Volume/{Volume,VolumeHeader,Keyfile,VolumeInfo,EncryptionThreadPool}.cpp`, `src/Core/CoreBase.cpp`, `src/Core/VolumeCreator.cpp`, `src/Platform/Unix/{Process,File,RequesterAccess,Directory}.cpp`, `src/Setup/SelfExtract.c`, `src/ExpandVolume/ExpandVolume.c`, `src/Main/Forms/{VolumeCreationWizard,MainFrame,MountOptionsDialog,WaitDialog}.cpp`, `src/Build/*`, `src/Setup/MacOSX/*`, `.github/workflows/*`.
6. **Cross-lens corroboration + spot verification**: findings independently produced by ≥2 lenses were treated as consensus clusters; the chair spot-verified headline evidence verbatim (`sed -n` against cited lines) before inclusion.
7. Expected result ≈150 findings with the distribution and clusters below. Runtime-dependent magnitudes are intentionally not confirmed (execution was out of scope by mandate); §7 states which findings need a lab drill to confirm.

---

## 4. Consolidated Findings

Severity = highest severity assigned by the owning skill's matrix; consensus count = number of independent audit agents that produced the same finding. Line numbers are as-read at `954a10b9`; several were chair-verified verbatim (marked ✓).

### 4.1 High-severity clusters (detailed)

---

#### CLUSTER A — Unenforced single-writer: concurrent RW mounts of one container (4-lens consensus)

| ID | Skill | Sev | Conf |
|---|---|---|---|
| CON-VC-001 | dataflow-concurrency | High | Confirmed (guard absence) |
| CON-VC-002 | dataflow-concurrency | High | Confirmed |
| NEG-002 / F7 | negative-space | High-if-reachable | Plausible |
| INV-002/014 | invariant-sync | Medium | Confirmed (code) |

**Evidence (✓ verified):**
- `src/Platform/Unix/File.cpp:396` — `#if 0 // File locking is disabled to avoid remote filesystem locking issues` — the entire `File::ShareNone` flock enforcement block is compiled out.
- `src/Core/Unix/CoreUnix.cpp:1427` — `if (IsVolumeMounted (*options.Path)) throw VolumeAlreadyMounted` — an advisory mount-table snapshot, not enforcement.
- `src/Core/Unix/CoreUnix.cpp:1489` — `ReserveMountVolume` exists only `#ifdef TC_LINUX` (Linux adds flock + `IsVolumeUsedByKernelDevice`).
- `src/Driver/FSKit/FSKitService.mm:126-129` — `// Keep the lock local even if the opened volume is on a share.` — FSKit mount locks live in the *per-user app-group container*, not a machine-wide scope (contrast `CoreUnix.h:68` `/var/run/veracrypt` on Linux).
- `src/Volume/Volume.cpp:454-456` (✓) — unaligned writes are a non-atomic read-modify-write of the full sector: `ReadSectors (aligned, alignedOffset); aligned.GetRange(...).CopyFrom (buffer); WriteSectors (aligned, alignedOffset);` with no per-Volume mutex; combined with `fuse_loop_mt` (`FuseService.cpp:598-612`).

**Mechanism:** on FUSE-T/macOS, FreeBSD, OpenBSD, Solaris builds there is *no* volume-level mutual exclusion. Two processes (or two login sessions via fast-user-switching, or two machines mounting a file container on an SMB/NFS share) can each pass `IsVolumeMounted` inside the enumeration window and open the same backing file read-write. Two live `Volume` objects then interleave unaligned RMW sector writes on the same plaintext sectors → lost updates, torn XTS sectors, silent cross-instance corruption, discovered only when a later mount fails header authentication. Per-request protections (`ReserveMountVolume`, FSKit `ReserveVolume` flock) exist only on Linux/FSKit-reservation-scope and do not cover this window. CON-VC-002 additionally shows concurrent writes *within* one FUSE service (multithreaded loop) lose updates deterministically for same-sector conflicts.

**Hypothesis / solution:** (1) restore adaptive file locking — `flock` on local filesystems, skip on network `statfs` types; or (2) port the Linux `ReserveMountVolume` flock-by-identity scheme to all Unix mount paths and add a machine-scoped advisory exclusivity probe at `Volume::Open`; (3) serialise `Volume::ReadBytes/WriteBytes` behind a per-Volume mutex (minimum: around the unaligned RMW path) and make the counters atomic (see Cluster F/CON-VC-003). Lab drill to confirm: two concurrent text-mode mounts of the same container plus concurrent unaligned writers; assert second mount refusal and byte-exact sector results.

---

#### CLUSTER B — Interrupted password/PIM/KDF change leaves split-header credentials (4-lens consensus)

| ID | Skill | Sev | Conf |
|---|---|---|---|
| TMP-001 | dataflow-temporal | Medium | Likely |
| STT-VC-001 | recovery-idempotency | Medium | Confirmed |
| DAT-VC-001 | dataflow-integrity | Medium | Confirmed |
| STT-003+CAS-006 | cascade/state-transition | Medium | Likely |

**Evidence (✓ verified, `src/Core/CoreBase.cpp:58-84`):**
```c
bool backupHeader = false;
while (true)
{
    for (int i = 1; i <= wipeCount; i++) {
        ...
        openVolume->ReEncryptHeader (backupHeader, newSalt, newHeaderKey, newPkcs5Kdf);
        openVolume->GetFile()->Flush();
    }
    if (!openVolume->GetLayout()->HasBackupHeader() || backupHeader) break;
    backupHeader = true;    // primary header committed+flushed FIRST, backup second
}
```
plus `src/Main/TextUserInterface.cpp:1727-1731` — after two wrong-password attempts the CLI auto-retries with `options.UseBackupHeaders = true`.

**Mechanism:** each header write+flush is an independent durability unit. A crash/power loss/kills between the two commits leaves primary = new password, backup = old password. There is no completion marker, no post-change verification of both headers, and the auto-fallback means the *old* password keeps working after an apparently-successfully-started change — or, if the primary is later damaged, the user's credential rotation silently reverts at recovery time. For hidden volumes this partially defeats the purpose of a rotation. The fix ordering already exists in-tree: `src/ExpandVolume/ExpandVolume.c:862-863` deliberately writes "backup header first" — the two routines contradict each other (STT-VC-003).

**Hypothesis / solution:** write the NEW backup header first (mirror ExpandVolume), or journal the two-step; after the change, verify-open both headers with the new derivation and report which header (if any) is stale. Non-atomic single `write()` of the 64 KB header also means a torn write surfaces as "password incorrect" (STT-VC-002/DAT: `VolumeHeader.cpp:287` CRC correctly rejects, but user messaging is misleading) — consider two-slot swap or pre-copy of the current header before overwrite.

---

#### CLUSTER C — Mount discovery truthfulness: silent drop vs. global abort vs. deadline collapse

| ID | Skill | Sev | Conf |
|---|---|---|---|
| CAS-008/REL-010/STT-004 | cascade/reliability/state | High | Confirmed |
| CAS-006/STT-004 | cascade/state | High | Confirmed |
| FSR-004 | dependency-criticality | Medium | Likely |
| FSR-005 / NEG F8 / IAPI-VC-104 | dep-crit / negative-space / opsignal | Medium | Likely |
| TMP-002 | temporal | Low | Plausible |

**Evidence:**
- `src/Core/Unix/CoreUnix.cpp:753-780` — Linux path: `catch (std::exception&) { ... } ` then `if (!mountedVol) continue;` — `UnresolvedMounts` exists only `#ifdef TC_MACOSX` (✓ verified in-tree; the error variable is `(void) e`'d on non-macOS).
- `src/Core/Unix/CoreUnix.cpp:705-707` — macOS path: `if (!result.IsComplete()) throw VolumeDiscoveryFailed (...)` — one unresolved mount aborts list discovery for *all* volumes (GUI refresh `MainFrame.cpp:1103`, `DismountAllVolumes`).
- `src/Driver/FSKit/VolumeProtocol.cpp:197-199` — `const auto deadline = SocketClock::now() + std::chrono::seconds (1);` for control reads, while the worker serves kernel image I/O serially with up to 10 s per request (`FSKitService.mm:230`, `VolumeConnection.swift:25`); the FUSET path has 10 retries (`CoreUnix.cpp:755-760`), the FSKit port has none (`CoreUnix.cpp:685-688`).

**Mechanism:** three divergent handlings of the same condition: on Linux a transient control-read failure makes a live mounted volume vanish from the inventory (it cannot be dismounted via "Dismount All", `IsVolumeMounted` returns false so a second mount of the same backing volume is permitted — feeding Cluster A); on macOS the same failure makes *every* volume unlistable; on FSKit, sustained I/O on one volume makes control reads time out in 1 s, producing spurious unmountable/unlistable states for unrelated volumes. After a binary upgrade, append-un-gated `VolumeInfo` fields (`VolumeInfo.cpp:59-61` — `VolumeCreationTime`, `Pim`, `MasterKeyVulnerable` lack the `ProgramVersion >= 0x10b` gating used by earlier fields) can make mid-era control files deserialize-fail on new binaries and silently drop mounts on Linux.

**Hypothesis / solution:** one shared failure-extraction utility: on control-read failure, record to `UnresolvedMounts` on **all** platforms, surface unresolved mounts distinctly in the UI (the macOS staleness machinery `MainFrame.cpp:1961-1982` is already the honest reference design), retry the FSKit control read bounded like FUSET, and era-gate appended `VolumeInfo` fields.

---

#### CLUSTER D — Fake success on failed writes (3-lens consensus)

| ID | Skill | Sev | Conf |
|---|---|---|---|
| CAS-009/STT-005 | cascade/state | High (FreeBSD) | Confirmed |
| REL-011 | reliability | Medium | Confirmed |
| FSR-VC-001 | operator-signal | High | Confirmed |

**Evidence (✓ verified, `src/Driver/Fuse/FuseService.cpp:1104-1112`):**
```c
#ifdef TC_FREEBSD
    // FreeBSD apparently retries failed write operations forever, which may lead to a system crash.
    catch (VolumeReadOnly&) { return size; }
    catch (VolumeProtected&) { return size; }
#endif
```

**Mechanism:** on FreeBSD, after a hidden-volume-protection trigger or read-only transition, the write handler returns the full requested size to FUSE: the kernel and applications conclude the bytes were persisted — no error, no log, no supersedence signal; the data is silently dropped. (On Windows the same protection event force-dismounts, `src/Driver/Ntdriver.c:4567-4626` exposure via GUI refresh; Unix has no such transition.) The sibling one is Windows-side: `src/Common/Format.c:1553-1566` reports sender-thread write errors one buffer late, and `StopFormatWriteThread` (`:1523-1535`) discards the final buffered error — a failed final header write during volume creation can be reported as success (CON-VC-006).

**Hypothesis / solution:** return `-EIO`/`-EPERM` plus a one-shot syslog; make the failure sticky and surfaced through the control file/statfs; on the format sender thread, carry a sequence counter and never return success for data whose write result is unknown.

---

#### CLUSTER E — Windows self-extracting installer: unbounded walk + zip-slip at elevated privilege

| ID | Skill | Sev | Conf |
|---|---|---|---|
| IOP-001 | dataflow-input-output | High | Confirmed (code) |
| IOP-002 | dataflow-input-output | Medium | Confirmed (code) |
| IOP-003 | dataflow-input-output | Low | Confirmed |

**Evidence (✓ verified, `src/Setup/SelfExtract.c:637-646`):**
```c
while (bufPos <= bufEndPos && fileNo < NBR_COMPRESSED_FILES)
{
    Decompressed_Files[fileNo].fileNameLength = mgetWord (bufPos);
    Decompressed_Files[fileNo].fileName = (wchar_t*) bufPos;
    bufPos += (Decompressed_Files[fileNo].fileNameLength * sizeof (wchar_t));
    Decompressed_Files[fileNo].fileLength = mgetLong (bufPos);
    bufPos += Decompressed_Files[fileNo].fileLength;
```
plus extraction (`SelfExtract.c:721-727`) concatenating the raw filename after the destination path, and `src/Common/Dlgcode.c:10539-10547` — `CorrectFileName` (`:8739-8750`, ✓ verified) only rewrites `'/'`→`'\\'`, converting `../../x` into equivalent traversal instead of rejecting it.

**Mechanism:** within one loop iteration, `bufPos` can advance past `bufEndPos` by up to ~2^16·2 + 2^32 bytes before the condition re-evaluates — out-of-bounds reads into the CRC and filename consumers. Per-file integrity is CRC32 (recomputable by anyone who rewrites the appended payload), and the code's own comment notes the appended archive sits **outside** the Authenticode signature. A modified-but-still-signed installer therefore accepts arbitrary lengths and `..\` names, and extraction runs elevated (`SelfExtract.c:732-737`, `Setup.c:907-912`) — an elevated arbitrary-file-write / OOB-read primitive. Defense-in-depth is currently zero (IOP-002 rides on the same premise; `zip_fread` return also discarded at `Dlgcode.c:10552-560`).

**Hypothesis / solution:** bounds-check each walk step before reading (`fileNameLength*sizeof(wchar_t)` and `fileLength` must fit `bufPos..bufEndPos`); reject `..` segments, absolute/device paths and reserved names; canonicalize and require containment under the destination; sign the payload digest into the signed image region.

---

#### CLUSTER F — FSKit backend parity debt (the actively-developed regression surface)

| ID | Skill | Sev | Conf | Fact |
|---|---|---|---|---|
| ARC-019/022 (lens-arch) | architecture-seam | Medium | Confirmed | Zero `EncryptionThreadPool` references in `src/Driver/FSKit/` (✓ grep-verified) — FSKit crypto is single-threaded while FUSE starts the pool (`FuseService.cpp:676-677`); silent N-core throughput loss. Pre-fix for Cluster A-style races: `TotalDataRead/Written/TopWriteOffset` unsynchronized (`Volume.cpp:380,489-490`) and `HiddenVolumeProtectionTriggered` check-then-act (`Volume.cpp:476-478` vs `:41-50`) on the one shared static `MountedVolume` (`FuseService.h:113`) — CON-VC-003. |
| ARC-017 / INV-001 / INV-005 / IAPI-VC-102 / ARC-VC-003 | seam/invariant | Medium | Confirmed | The C++↔Swift wire protocol (`VolumeProtocol.cpp:27-34` vs `VolumeConnection.swift:7-26`: signature `0x3346434c`, ops 1-5, 1 MB cap, offsets, sockaddr length) and the `/private/tmp/lambcrypt-fskit.` prefix (MountedFilesystem.h:32, FSKitService.mm:424/439) + `lambcryptfs` type (Info.plist, FSKitService.mm:300, FileSystem.swift) are hand-duplicated across languages with no shared owner; a one-sided edit compiles cleanly and fails only at runtime. |
| CORE-OPT/IO-OPT (std-perf) | performance | Medium | Likely | ~1 AF_UNIX connection per 1 MB transferred (`VolumeConnection.swift:106-110`, `FileSystem.swift:271-273`); single accept-serve worker thread (`FSKitService.mm:403-407`) bounds concurrency to 1; per-request mount-table rescans (`:260-263`); fresh 1 MB `SecureBuffer` malloc/wipe/free per request (`VolumeProtocol.cpp:284,291-298`). All unmeasured (static mandate) — profile before changing defaults. |
| NEG-003 (fd) | negative-space | Low | Confirmed | `RunWorker` closes all non-whitelisted fds incl. stdout/stderr (`FSKitService.mm:214-218`) → all worker `SystemLog::WriteException` output is silently sunk. |
| NEG-002/FSR-VC-006 | negative-space/opsignal | Med | Conf/Likely | Peer-auth and reply failures return with no reply and no record (`VolumeProtocol.cpp:231-236`, `:91-101`) — client sees only a 10 s stall; no logging anywhere in the FSKit worker. |
| FSR-VC-003 / VC-HUNT-04 / NEG-003 (Swift) | failsafe / harness / neg | Med/Low | Plausible | `loadResource`/`unloadResource` single-slot state machine (`FileSystem.swift:24-53`, ✓ verified): mismatched or double unload leaves `loadedURL` set → permanent `EBUSY` wedge until the extension recycles; not idempotent. |
| ARC-VC-001 / ARC-VC-004 / NEG-008 | arch-drift / neg | Medium | Confirmed | The FSKit build is unreachable via the documented wrapper (`build_lambcrypt_macosx.sh` has no FSKit flag; only manual `make WITHFSKIT=1`, `Makefile:82-84`) and invisible to CI (no macOS workflow; `build-linux.yml` path filters include `src/Driver/Fuse/**` but not `src/Driver/FSKit/**`) — the *most actively developed* surface has zero automated validation. |
| ARC-VC-002 | arch-drift | Medium | Likely | `FSKitService.mm:35-37` hard-refuses root/elevated sessions inside `ApplicationGroupDirectory()`, but the declared elevation architecture (`CoreServiceProxy.h:33-34`) routes ALL post-elevation device-hosted mount requests through the root process → elevated device-hosted mounts on FSKit builds throw a generic `ExternalException`; removable-disk encryption is a core lineage use-case. |
| RSR-VC-011 | repo-state | Info | Confirmed | FSKit pkg build (`notarize.sh:136-137`) runs bare `productbuild` with no postinstall → no `/usr/local/bin/lambcrypt` CLI symlink on FSKit machines (macfuse/fuset pkg does create it). |
| IAPI-VC-101 | contract-internalapi | Medium | Confirmed | `FSKitService.h` declares 13 functions; `GetAttachedDiskImageDevice` is implemented in `CoreMacOSX.cpp:278` — driver-layer contract implemented in Core, behind another layer's build flag; also `CoreUnix.cpp:38-40` includes Driver headers and uses the FUSE-owned `volume.dmg`/`control` names for FSKit discovery (ARC-004/F2: FSKit discovery depends on a constant physically owned by `FuseService.h:63-70`). |

---

#### CLUSTER G — GUI/operator truthfulness defects (workflow-gui + adapted design lens)

| ID | Sev | Evidence (✓ where marked) | Mechanism (abridged) |
|---|---|---|---|
| WFG-008 / FSR-VC-005 | Med Confirmed | `MainFrame.cpp:1210-1217` (✓) — success string emitted if volumes were mounted *before* `DismountAllVolumes`, postcondition never rechecked (the non-forced branch at `:1192-1200` re-counts — in-tree drift) | User told "volumes unmounted, cache wiped" while volumes remain mounted. |
| WFG-007/WFG-005 | Med Confirmed | `VolumeCreationWizard.cpp:313-322` — `ValidateMacOSXSelectedDeviceForCreation`: `try { infoXml = GetMacOSXDiskutilInfo (devicePath); } catch (...) { return true; }` | Destructive-device guard **fails open** if diskutil errors: APFS-system-store/apple_boot/read-only subsystem checks all silently skip; only the generic overwrite prompt remains. |
| WFG-VC-001 (adapted) | High Confirmed | `VolumeCreationWizard.cpp:944-950` — mkfs executed inside the wx timer handler via `Process::Execute` (no event yield, `Process.cpp:575-601`); abort disabled at `:821-823` | Beachball minutes-long freeze with a stale ~"100%" gauge for a destructive op; no cancel path. |
| WFG-VC-002 / WFG-003 / FSR(sec) | High Confirmed | `VolumeCreationWizard.cpp:997-1006` (✓) — on abort or failure, partial container unconditionally deleted `catch (...) { }`; CLI (`TextUserInterface::CreateVolume`) has no equivalent | Silent irreversible deletion of the user's (possibly multi-GB) file; GUI/CLI divergent postconditions. |
| WFG-VC-003 (adapted; =WFG-013 family) | High Confirmed | `AskYesNo(..., true, true)` defaults: header restore `GraphicUserInterface.cpp:1874`, force unmount `UserInterface.cpp:260`, `FORMAT_ABORT` `VolumeCreationWizard.cpp:767` | Enter-key acceptance of destructive prompts; inconsistent with `OVERWRITEPROMPT` (which uses safe defaults `:1440,1447`). |
| WFG-014/CMP-003 | Med Confirmed | `Language.xml:1506` guarantees "no data on the outer volume are overwritten by the hidden volume" vs `VolumeCreationWizard.cpp:1582-1596` — non-FAT outer substitutes an **estimate** `(avail/5)*4` for the exact scan | Advertised "maximum possible size" can overwrite outer-volume data — guarantee text vs. estimate reality. |
| WFG-009 | Med Confirmed | `UserInterface.cpp:840-850` — "Mount all devices" swallows 8+ exception classes; warning only if nothing mounted | Partial success masks per-device non-password failures. |
| WFG-005 (keyfile guard) | Low Confirmed | `VolumeCreationWizard.cpp:1236-1242,1289-1295,1621-1628` — keyfile-apply failure falls back to raw password for the outer/hidden equality comparison | Plausible-deniability guard (`LINUX_HIDDEN_PASS_NO_DIFF`) evaluated across inconsistent forms; can miss a match. |
| FSR-VC-002 (opsignal) | High Conf/Likely | `CoreService.cpp:1132-1141` — no deadline on elevated-IPC response deserialization; `WaitDialog.h:149-156` vetoes close | GUI unkillable-hang path when the elevated service wedges; killing the app is the only exit. |
| WFG-VC-004/005/013 | Med Confirmed | `MountOptionsDialog.cpp:199-206` silent invalid-PIM dead-end (wizard shows `PIM_TOO_BIG` for the same condition); `WaitDialog` uncancellable/uninformative; `VC_CONVERT_EXCEPTION` hand-maintained list falls through `throw *ex` slicing to message-less base (missing `RandInitFailed`/`CryptoApiFailed`) | Silent invalid-submit; blank error boxes on RNG/CryptoAPI failures. |
| FSR-VC-008 | Med Likely | `Xml.cpp:235-243` — `~XmlWriter(){ try{Close();}catch(...){} }` after `File::CreateWrite` truncated the file at construction | Favorites silently lost on commit failure (UserPreferences::Save does catch — in-tree divergence). |
| WFG-004 | Low Plausible | `TextUserInterface.cpp:1156-1172` before `VolumeCreator.cpp:158` | CLI prints "Done: 100.000%" before the backup-header write completes; Ctrl-C at 100% loses headers. |
| STT-005 | Low Confirmed | `CoreUnix.cpp:1452-1466` | RW mount request silently downgraded to read-only on EROFS/EACCES with no notice. |
| VC-HUNT-02 | Info | `CoreMacOSX.cpp:887-895` free-text `-mountpoint` accepted without leading-"-" rejection (sibling umount uses `--`) | Argv (no shell), self-elevation only; hardening gap. |

---

#### CLUSTER H — Craft-level reliability defects worth prioritizing

| ID | Sev | Evidence | Mechanism |
|---|---|---|---|
| FSR-VC-002 (failsafe) / CON-VC-004 / MEM-VC-001 / NEG-001 | Med/High | `FuseService.cpp:1706-1717,1803-09` — full `DismountVolume` (RPC, fork/exec, exceptions, shared_ptr) inside async-signal context; `FuseService.cpp:1156-1166` — `delete MountedVolume.get()` while other shared_ptr owners live (✓ corroborated by 3 agents) | Signal handler can self-deadlock pre-`_exit` (multi-thread fork lock inheritance), leaving keys in RAM; raw delete = teardown-time UAF/double-destroy window. Fix: write-pipe+`_exit` handler; proper ownership. |
| REL-005/FSR-003 | Med | `Process.cpp:105-110` — one stuck (SIGKILL-surviving) child permanently poisons ALL later `ExecuteBounded` calls as fresh `TimeOut` | D-state hdiutil → every subsequent bounded CLI spawn (mount/dismount/enumerate) refuses until app restart. Fix: distinct "StuckChild" exception + bounded escalation. |
| FSR-008 | Med | `Process.cpp:595-596` — `Process::Execute` (timed) intentionally leaves the child running on timeout | Timed callers leak possibly-privileged children with no reap sweep (unlike ExecuteBounded). |
| FSR-006 | Med | `CoreService.cpp:1900-1903` — unbounded `waitpid` on the sudo handshake child after the timed sync handshake | GUI/CLI hang forever on a stalled/re-prompting sudo. |
| FSR-007 | Med | `CoreMacOSX.cpp:859/861` — legacy macFUSE check stats only `/usr/local/lib/libosxfuse_i64.2.dylib`/`libfuse.dylib` | False refusal on Apple Silicon Homebrew (`/opt/homebrew`) layouts. |
| FSR-014 | Low | `CoreMacOSX.cpp:206-209` — `hdiutil info` budget 2 s vs 30 s attach/detach budgets on the same subsystem | Under-provisioned inventory timeout folds into `DismountServiceCleanupFailed`. |
| FSR-VC-001(opsignal)/REL-012 | Med | `CoreUnix.cpp:398-402,432-436` — non-Linux dismount swallows loop-detach and aux-dir cleanup failures; `FSKitService.mm:411-418` worker exit cleanup unchecked; `WaitForServiceExit` 10 s then throw | Loop-device/dir residue unlogged; ~1 Hz retired-listener error-log cycle keeps growing (`FuseService.cpp:409-416` + serve loop). |
| CON-VC-005 | Med | `EncryptionThreadPool.cpp:254,289-296,343` — check-then-act pool init, plain store | Latent init race; serial callers today. |
| CON-VC-008 | Low | `CoreService.cpp:1507` — per-template `static Mutex` in `SendRequest` | Mount and dismount requests serialize per-type, not globally, in one client. |
| FSR-VC-007 | Med | `GraphicUserInterface.cpp:1240-1255` — single-instance check deletes the lock on ANY probe failure, not only `ENOENT` | Second GUI instance can start alongside a live one → same-slot racing requests. |
| FSR-VC-009 | Low | `Volume.cpp:295-312` — boot-loader probe swallows device I/O errors, surfaces "password incorrect" | Operator retries passwords instead of fixing permissions. |
| SEC-VC-004 | Info | `RandomNumberGenerator.cpp:38-41` — urandom read only `== -1` checked (short reads mix stale heap; confidentiality unharmed via HashMixPool) | Loop until filled. |
| STT-VC-005-style | Low | `ExpandVolume.c:1040-1076` — `goto error` skips `burn(wipeRandChars...)`; old-backup-header wipe failure → `ERR_SUCCESS` (`:1060-1075`) not tracked | Minor key-material wipe gap; stale-header state untracked (old password header survives future changes). |
| IO-OPT-006 | Med Conf(prop) | `FuseService.cpp:882-883` — no `direct_io` on the decrypted volume image (vs `:887/:894` for aux files); no `O_DIRECT`/`F_NOCACHE` anywhere | Decrypted plaintext cached in the host kernel page cache, contrary to the service's own key-hygiene posture — needs measured decision (page cache also helps FUSE-T SMB re-reads). |

---

### 4.2 Security findings (audit-security lens + posture/triage + adaptations)

| ID | Sev | Finding (abridged) |
|---|---|---|
| SEC-VC-001 (lens-security) | Med | FreeBSD `MountFilesystem` probes fs type via `popen` + shell string with device path unquoted and bare `blkid` PATH-resolved, in the elevated process (`CoreFreeBSD.cpp:208-211`), bypassing the repo's own trusted-binary discipline (`Process.cpp:379-381`). Not currently reachable (paths from mdconfig), latent root injection — fix with `FindSystemBinary` + argv. |
| SEC-VC-002 | Low | `--fs-options`/fstype forwarded verbatim by the elevated service; `mountprog=`/`/sbin/mount.<type>` lets the requester choose the root-executed helper (`CommandLineInterface.cpp:449-451`, `CoreFreeBSD.cpp:216-234`, `MountOptions.cpp:141`) — self-elevation-abuse surface; allowlist. |
| SEC-VC-003 / VC-HUNT-03 | Low | `RequesterAccess.cpp:430-445` preserves caller `LD_LIBRARY_PATH` across root `execve("/proc/self/exe")` — needs already-root-equivalent sudoers config to matter; still should sanitize. |
| SEC-VC-001 (adapt-security-code) | Med | SUDO_UID trust in elevated FUSE service with silent catch (`FuseService.cpp:1730-1741`, ✓) — strict-parse counterpart exists (`RequesterAccess.cpp:95-100`); parse fail silently roots the volume; unvalidated env identity feeds `allow_other` traversal. |
| SEC-VC-002 (adapt-code) | Low | Root CoreService honors per-request client policy fields `AllowInsecureMount`/`UserEnvPATH`/`UseDummySudoPassword` (`CoreService.cpp:1231-1233`) — undermines the trojan-mount-point guard for the requester's own namespace. |
| SEC-VC-003 (adapt-code) | Low | Mount-table candidate filter accepts root-owned `lambcryptfs` mounts as "mine" for every uid (`MountedFilesystem.h:26-36`); FUSET has a cross-user exclusion, FSKit does not. |
| SEC-VC-001 (owasp) | Low | PIM cached in cleartext in the unencrypted boot sector for system volumes (`BootConfig.cpp:70-77`) — reduces attacker work-factor space (design tradeoff; warn at enablement). |
| SEC-VC-002 (owasp) | Low/Med | `--password`/`--pim` CLI options expose the secret via `ps` to all local users (`CommandLineInterface.cpp:116,542-548`; CI itself uses `--password test`, `build-linux.yml:212`); `--stdin` exists — deprecate. |
| SEC-VC-003 (owasp) | Low | GUI keystroke password leaves a non-erasable wxWidgets heap copy (admitted at `VolumePasswordPanel.cpp:226`). |
| SEC-VC-010 (adapt-code) / RAM-cache | Info | Password cache: no expiry, `VcGetPasswordEncryptionID` derived from pointer values (`Cache.c:38-49`); same-user compromise only. Flash: RAM-Encryption ID is deterministic. |
| — | — | **Explicit non-findings (verified PASS)**: FSKit/FUSE socket auth chains (per-connect S_ISSOCK/st_uid/mode-0077/getpeereid); ESTALE generation fencing; serializer/TLV/header bounds checks; trusted-binary walk (`Process.cpp:415-431`); SetFileOwner device-scope chown; O_NOFOLLOW+fstat locks; admin-password pipe transport + erase; core-dump disabled in all 3 privilege daemons; CSPRNG everywhere; no shell interp on mount paths (`--` separators); Blender: `xx` XXE mitigations in the validator. |
| **Repo posture** | — | Victim verdict: **partial**. Strengths: all 4 workflows `permissions: contents: read`, all 18 action pins full-SHA, no `pull_request_target`, no untrusted event data in `run:`, wxWidgets+SDK SHA-gated fetches, strong notarize-time verification, no committed secrets beyond test material. Material findings: committed test code-signing PFX keys w/ public password (`src/Signing/TestCertificate` + `sign_test.bat:5-8`) — repo-supplied keys trusted by TESTSIGNING workflows; committed prebuilt WHQL-signed drivers (`src/Release/Setup Files/veracrypt-{x64,arm64}.sys/.cat`; `Product64.wxs:261`) not rebuildable from source — release provenance rests on upstream signature; product identity divergence (LambCrypt-installer ↔ VeraCrypt binaries); no SECURITY.md / private disclosure channel; no CODEOWNERS; no secret-scanning automation; no published per-release checksums from CI. |

---

### 4.3 Tests/CI economics (audit-testsuite-economics)

| ID | Sev | Finding |
|---|---|---|
| TSE-017 | High | 69% of test-suite LOC (9,304/13,379) executed by **no** CI workflow; no macOS/Windows/root-Linux runner exists; unwired: all FSKit/Fuset/macOS/linux-root tests incl. `test_fskit_volume_protocol.py`, `test_macos_discovery.py` (1,377 L), encryption-pool pair. |
| TSE-014 | High | Every recent FSKit/Fuse fix commit shipped regression tests CI cannot run (e.g., `f6a23912` EBUSY/253-byte-socket-path tests) — the newest, defect-densest area has no re-escape tripwire. |
| TSE-001/002 | Med | No tiering: pure unit checks embedded in the 30-min package-build job; only `test-wxbuild.yml` is a fast lane (5 min). |
| TSE-010 | Med | 10 harnesses pin production source *layout* via marker-string slicing (`test_macos_discovery.py:61-88` `source.index("\tclass CFHolder")`…; pool-exceptions, windows-kdf, fuset harnesses) — renames/reindents break tests with `ValueError`, asserting nothing about shipped behavior; mock re-implements the `/private/tmp/lambcrypt-fskit.` fact (drift-blind). |
| TSE-015/016 | Med | No test policy / AGENTS.md — lanes undiscoverable for humans and agents. |
| TSE-011 | Med | `volume_password_cache_test.cpp` (a real 1,000-iteration GUI-timer-vs-mount-thread race) is orphaned — no runner, no reference anywhere (relates to Cluster A/C). |
| TSE-013 | Med | Inverted pyramid: only integration layers auto-verified; unit/fault-injection (operator-new failure, EINTR replay, `--wrap` fault injection) unwired. |
| TSE-012/005/008/018 | Low | Sleep-based waits (6/10.5/24/30 s; 4 s subprocess budgets) → imminent flake risk if the recommended macOS CI lands; duplicated path-filter/cmp blocks in `build-linux.yml:195-260`; hand-maintained fakes drift-prone; ~20 `time.sleep` sites. |
| CORE-OPT-008 | Low | `BenchmarkDialog.cpp:224-247` — single run, ms clock, 100 ms window, pool confound → user-facing benchmark numbers measure dispatch, not algorithm throughput. |
| Positive | — | Suite is value, not theater: adversarial invariants (EROFS, EINTR/short/fault-write replay, FAT bootstrap expectations), fixture hygiene with two-way digest completeness check; drivers externalize exit codes. |

---

### 4.4 Dead code / polish / branding inventory (DEAD/POL — report-only)

| ID | Sev | Finding |
|---|---|---|
| DEAD-002 (SM4) | Med | 1,003 LOC SM4 cipher (`sm4.cpp`/`sm4-impl-aesni.cpp`) wired into **no** build system anywhere; `doc/html/en/SM4.html` advertises it (doc drift). Decide: register or remove. |
| DEAD-024 | Med | 38 vetted-unused i18n keys incl. the whole dead system-crash-analysis feature cluster (11 keys), 3 TrueCrypt-mode keys, rebrand-orphaned `START_TC` "Start LambCrypt" (`Language.xml:1555`). |
| DEAD-009 | Med | TrueCrypt-mode UI excised (0 refs) but docs + catalog strings remain on 3 surfaces (keep legacy-format volume *code* — it is live). |
| DEAD-010 | Med | 20+ `#if 0` blocks; one deliberate (DriveFilter hibernation reference) but its "hide creation-time" edit was copy-pasted into 4 driver files — reversion must touch all. |
| DEAD-005 | Med | `src/Setup` vs `src/SetupDLL` cloned installer codebases w/ intentional, non-mechanical divergence (`SetupDLL/Setup.c:1271`) and ComSetup CLSID drift risk; also harmless duplicated `OBJS` line (`Core.make:27-28`). |
| POL-001 | Med | `IsTrueCryptInstallerRunning()` checks own `Global\VeraCrypt Setup` mutex (name lies; behavior correct). |
| POL-010 | Med | Magic literal `0x10b` ("backup-header-capable" version sentinel) unnamed in 3 files (`VolumePropertiesDialog.cpp:75-76`, `Volume.cpp:198`) — a typo silently flips format logic; also FSKit string-matches the English error text `" is disabled!"` of an external binary (`FSKitService.mm:~577`). |
| POL-006/008/005/009 | Low | 5 commented debug `wcerr` lines in `Application.cpp`; unused `<iostream>` in `CoreUnix.cpp:16`; stale TrueCrypt comments (`Mount.c:8561,:2032,:147`); untracked TODO ledger w/ duplicate cluster (`Mount.c:10776`+`Tcformat.c:9622`). |
| Branding | Med | Three live identities coexist (`lambcrypt`/`veracrypt` binary+env+mount paths `Makefile:61`, `CoreUnix.cpp:638,643`, registry `Setup.c:1466`, live `IDI_TRUECRYPT_ICON` resource IDs) and `Language.xml` mixes 286 LambCrypt vs 146 VeraCrypt strings — sibling messages on the same code path disagree (`xml:424` vs `:425`). Syslog ident vs message branding disagree (`openlog("lambcrypt")` vs "VeraCrypt FUSE shutdown worker" error). Zero-byte orphaned `Common/IccDataExtractor.{h,cpp}`. `Tests/bench.bat` references the dead install path `c:\Program Files\VeraCrypt\veracrypt.exe`. Maintain decision: upgrade-compat identity retention vs cleanup. |
| POL-016/017 | Med | Giant dialog procs (`Tcformat.c MainDialogProc` 2,919 L, `PageDialogProc` 2,423 L; `Mount.c` 14.4 k L); Core↔Driver boundary inversion (`CoreUnix.cpp:38-40,1564`; `.veracrypt_aux_mnt` prefix shared across backends `CoreUnix.h:79`) — routed to architecture, not repairable as polish. |
| IOP-011 | Info | Rebrand seam: user strings say LambCrypt while the XML dialect is still `<VeraCrypt>` (`Xml.c:276`) and `TC_APP_NAME` comparisons live in `Volume.cpp:332`. |

---

### 4.5 Repository state / build / packaging

| ID | Sev | Finding |
|---|---|---|
| ARC-VC-005 (RSR) | Med | Divergent live worktree `codex/fskit-read-write-mvp` = main + 13 unmerged FSKit commits with overlapping subject matter to main's latest fixes (`adcdf1ca`/`82d7e7`/`d26bf25c` vs `f6a23912`/`954a10b9`); branch strictly contains main (fast-forwardable **now** — later it won't be). |
| RPC-VC-007 | Low | `/tmp` wxWidgets build cache keyed by wx version, not checkout ("wx-config already exists … Skipping wxbuild" — `build_lambcrypt_macosx.sh:159-161`, same in Linux script); two live worktrees share `/tmp/wxBuild-3.2.10`; `private_tmp_dir.sh` validates ownership, not identity/freshness. |
| RSR-VC-006 | Low | Debian/RPM postinstall `rm -f` lists still remove removed donation docs/languages (`src/Build/Packaging/debian-control/postinst:4-9`) — actively wrong doc of shipped content. |
| RPC-VC-008 | Info | Tracked `.vcxproj.user` embed previous maintainer's VM names (`Driver.vcxproj.user:9-10` `VM11`). |
| ARC-VC-010/012/013/014 | Info | README documents a subset of build-script flags; silent `PARENTDIR=/tmp` fallback undocumented; legacy script doc-drift (SDK 10.9) and bypasses `private_tmp_dir.sh` hardening siblings use. |
| INV-001 (versions) | Med | Version `1.27.0` ground truth `Tcdefs.h:62/73` vs 10 hand-maintained `.rc` copies + `Language.xml:3` (macOS path derives correctly via `Main.make:116`); `TC_RESCUE_DISK_UPGRADE_NOTICE_MAX_VERSION` hand-bump (`BootCommon.h:20`). |

---

### 4.6 Performance profile (all findings unmeasured-static per the skill's own doctrine — "measure first")

| ID | Finding |
|---|---|
| IO-OPT-001/002 | Connection-per-request FSKit IPC (~1 connection/MB; single-threaded worker = concurrency ceiling 1 independent of the pool that isn't started anyway — see Cluster F). |
| CORE-OPT-003/004/005 | Thread-pool fragmentation of small I/O (1 sector/worker; per-service AND per-CLI pool spawn); write-path triple-touch double-buffering per call; fresh 1 MB SecureBuffer per FSKit request. |
| CORE-OPT-010 | Whole-machine `sync()` on dismount under standard hidden-volume protection + 2.2 s retry cap per volume; Dismount-All multiplies. |
| GUI-OPT-007/011 | 2 s GUI poll re-reads every volume's control state (2 socket round-trips each on FSKit; retry loops sleep up to 10×500 ms in discovery); every CLI invocation starts a full pool even for `--list`. |
| CORE-OPT-008 | BenchmarkDialog methodology invalid per skill rubric (single run, ms clock, 100 ms window, pool confound). |

### 4.7 Memory/resource lifecycle

| ID | Finding |
|---|---|
| RES-VC-001 | Retired FUSE listener → permanent ~1 Hz error-log cycle (unbounded log residue) until external unmount. |
| MEM-VC-002/RES-VC-002 | CFDictionary leak on failed IOKit lookups (poll loop small leak/second); control-file `fi->fh` heap buffer leaks on force-kill (self-heals at exit). |
| Explicit clean | All reservation/activation/lock paths close on every branch (`finally_do`); key wipe disciplined on ALL derivation/retry paths incl. stdin; `ExecuteBounded` leaves no residue; FormatSDK wipes passwords on all exits; FSKit short-read zero-fill. |

---

## 5. Cross-Lens Corroboration Map (consensus strength)

| Cluster | Independent agents producing it | Consensus |
|---|---|---|
| A. Concurrent RW mounts / RMW loss | dataflow-conc, lens-arch(NEG), lens-invariant, std-depcrit(pipeline) | 4× |
| B. Password-change split headers | dataflow-temporal, recovery-idempotency, dataflow-integrity, cascade/STT, lens-gui (indirect) | 4× (+ExpandVolume in-tree contradiction) |
| C. Discovery silence vs. abort; FSKit 1s deadline | cascade, reliability, dep-crit, lens-arch(NEG F8), opsignal, temporal | 6× |
| D. Failed writes reported as success (FreeBSD; Format.c late error) | cascade, reliability, opsignal, dataflow-conc | 3–4× |
| F. FSKit parity debt (no pool, protocol dup, CI blindness, single-thread worker) | lens-arch, lens-invariant, std-perf, std-arch-repo, contract-internalapi, std-depcrit | 5–6× |
| G. GUI truthfulness defects | lens-gui, adapt-design-webapp, opsignal | 3× |
| SUDO_UID identity trust | adapt-security-code, adapt-owasp, dep-crit, reliability | 4× |
| Linux silent discovery drop | cascade, reliability, invariant, temporal | 4× |
| Config control-file prefix `/private/tmp/lambcrypt-fskit.` triplication | invariant-sync, lens-arch, std-arch-repo, lens-gui (indirect) | 3–4× |
| i18n 38 dead keys / TrueCrypt-mode drift | std-deadcode | 1× (verified exhaustive grep) |
| Version-string drift (0x10b magic literal; .rc copies) | std-deadcode(POL-010), std-arch-repo(INV-001), lens-invariant | 3× |

---

## 6. Analysis & Root-Cause Theory

**Theory 1 — "Sibling-implementation drift" is the dominant defect generator.**
The FSKit backend is a hand-ported parallel abstraction of FuseService.cpp. Each of its dropped hardenings — encryption pool start, control-read retries, per-connection logging, stdout/stderr retention, cross-user discovery exclusion, checksum of mount-identity — was independently rediscovered by a different lens. The pattern repeats structurally: hand-duplicated facts (protocol constants, `/private/tmp` prefix, `volume.dmg` names, version strings, fsid/mount-liveness logic in both drivers, Setup vs SetupDLL installer clones, 12-flag vs README drift, ChangePassword vs ExpandVolume header ordering) have no single owner and no drift guard, so each duplicated copy silently rots. **The fix class is the same everywhere: single-owner constants (generated header shared C++↔Swift), shared helpers for mount-liveness/reservation, one header-order policy, one discovery failure policy — plus a drift-guard test that exercises the *real* code rather than a re-implementation of it.**

**Theory 2 — "Report-only surfaces lie."**
The fake-success family (FreeBSD write success, Format.c late error, hotkey success message from pre-state, ExpandVolume wipe-failure-as-success, mount wait swallowing into empty MountPoint, favorites loss in a destructor, silent deletion of the partial container) all share one morphology: a routine that catches everything and returns/vanishes with no record. The codebase already contains the correct counter-patterns (FUSET's `controlFileError` capture, macOS `VOLUME_DISCOVERY_STALLED` staleness labels, `UserInterface::DismountVolumes` unconfirmed-cleanup reporting, the orphaned-but-correct design of `MainFrame` non-forced dismount post-count) — the remediation is to make those the shared standard, not per-path exceptions.

**Theory 3 — Exclusivity is enforced by convention, not mechanism, outside Linux.**
Cluster A and the FUSE-T in-process-only slot reservation show the codebase's mount-exclusivity model was designed around Linux's kernel-visible loop devices. Where there is no kernel object to interrogate (FUSE-T, FSKit app-group), the check-then-act guard plus compiled-out file locking leaves nothing. The per-user app-group reservation is a deliberate isolation decision, but it needs a second, machine-scoped advisory exclusivity probe at `Volume::Open` keyed on device/inode.

**Theory 4 — Fork debt compounds silently.** The rebrand (veracrypt→lambcrypt) applied to Makefile/C++ file names/logs but not uniformly to language catalogues (146 vs 286 split), `Language.xml` keys referencing dead names, NO-ops like `IsTrueCryptInstallerRunning`, mount paths, env var names, and the installer's `--veracrypt` flag — plus divergent identity between shipped (prebuilt VeraCrypt) binaries and the LambCrypt label. None of these are individually severe; collectively they erode operator trust and triage (cf. syslog ident mismatch, FSR-VC-010).

**Theory 5 — The release pipeline is the true critical path, not CI.** CI is clean and honest; but the release identity rests on (a) committed prebuilt binaries, (b) committed test signing keys trusted by TESTSIGNING environments, (c) manual Windows signing (sign.bat, Idrix thumbprint), and (d) no published checksums — while the discovered installer-format weaknesses (IOP-001/002) sit exactly on that path.

---

## 7. Prioritized Remediation Hypotheses (recommended order — all subject to lab confirmation, none applied)

1. **Installer walk hardening** (Cluster E): bounds-check every SelfExtract step, reject `..`, canonicalize — small, self-contained, eliminates an elevated write primitive.
2. **Dismount/write honesty** (Cluster D + fake-success family): `-EIO`/`-EPERM` + sticky state on FreeBSD; sequence-carry the Format.c sender error; success strings only on verified postconditions.
3. **Volume exclusivity** (Cluster A): restore adaptive flock / port `ReserveMountVolume` to all Unix; per-Volume mutex around RMW; atomicize counters.
4. **Header commit ordering + verification** (Cluster B): backup-header first; verify both headers post-change; surface diverged-header state.
5. **Discovery policy unification** (Cluster C): `UnresolvedMounts` on all platforms; FSKit control retry parity; era-gate VolumeInfo additions.
6. **FSKit parity checklist** (Cluster F): pool start, retain stdout/stderr for syslog, request-level logging, logout of wedges (idempotent `unloadResource`), elevated-session design decision (ARC-VC-002 needs a maintainer choice), CI macOS job (`make WITHFSKIT=1` + `test_fskit_volume_protocol.py`) + add `src/Driver/FSKit/**` to path triggers.
7. **Ownership/governance**: shared constants (protocol header, prefix, type name, 0x10b sentinel, version), SECURITY.md, CODEOWNERS, secrets scanning, drift-guard tests replacing source-slicing harnesses, stash guidance for the divergent worktree (fast-forward now while it is still free).
8. **Security hardening set**: FreeBSD blkid argv conversion, `mountprog` allowlist, LD_LIBRARY_PATH sanitization, SUDO_UID strict parse, `--password` deprecation, PIM-cache enablement warning.

---

## 8. Issues Encountered (noted only, per mandate)

1. **Catalog retrieval mode:** `search_skills` reported `index_stale`; the call degraded to `deterministic_fallback` scoring (deterministic results preserved). No findings affected.
2. **Skill text truncation:** several `load_skill`/`load_skill_file` payloads exceeded the 16 k inline capture size; auditors recovered them by paged re-loads or by reading the skill's on-disk copies (outside the forbidden-evidence set). All 13 lenses and all applicable standalones were loaded; a few shared contract tails (`routing_guide`, `model_adaptations` on some agents) were applied from visible summaries.
3. **Missing catalog file:** `audit-security-code`'s `000_common/checklists/appsec-hardening/INDEX.md` is not shipped under the skill directory (load failure noted; CSEC taxonomy substituted).
4. **vuln-harness partial run:** the skill mandates multi-agent phases (independent refuter/verifier); the read-only single-context engagement could not spawn them, so the harness ran sequentially with self-refutation — **formally a partial run per the skill's own preflight rule**; its findings carry no independent-verification endorsement.
5. **Static-only ceiling:** all skills mandating measurement (performance profile, testsuite-economics timing) or dynamic attack drills (vuln-harness EX-4, protocol-fuzz consent drills) were run at their static ceiling; per the skills' own calibration this caps the corresponding confidences at Likely/Plausible. No magnitudes were fabricated.
6. **Absolute-path rejection** in `load_skill_file` (must pass relative `000_common/...` paths) — noted, worked around.
7. **Unreviewed surfaces** (each flagged by the owning agent as a follow-up requirement, not a silent gap): `src/Boot` UEFI header parsing, Windows kernel driver internals under load, Windows GUI trio deep read, vendored libzip/lzma/zlib CVE posture (no web lookup was allowed), `src/Format/InPlace.c` Win32 wizard surface.
8. No prohibited files were read; no repository files were created/deleted/modified besides this report; no builds, tests, or playtests were run.

## 9. Verified-Strength Inventory (explicit non-findings worth preserving)

Perimeter protocol validation (per-connect uid/mode/getpeereid checks, ESTALE generation fencing, write bounds, 1 MB caps, exact-size control replies); trusted-binary resolution walk; elevated temp-dir trust walk (`IsTrustedElevatedTempDirectory`); header/KDF robustness (DeserializeEntry bounds, sector-size clamps, header+key-area CRC, forced-RO on geometry overrun, legacy `<v4` CRC note); header/KDF parallel derivation with abort-on-first-success; Linux idempotent loop/dm teardown ("retry after a partial dismount is safe"); FUSE startup rollback epoch retirement; bounded retry caps throughout; honest macOS staleness labels and `CanConfirmEmpty`; notarize-time verification chain; CI pinning/least-privilege/SHA-gating; fixture hygiene (two-way digest completeness); GUI wizard success gating and disabled-control liveness; fork-kept legacy-format volume compatibility (live, must not be cleaned up).

*End of report. Companion: `mistral-auditskill-analysis-23NOV2026.md` details how the adaptations were made and what findings they produced.*
