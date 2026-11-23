# LambCrypt code audit

Audit date: 23 November 2026

Repository: `e3742526/LambCrypt`  
Branch: `codex/fskit-read-write-mvp`  
Audited HEAD: `271c85a58b4a7151c65149634db33f0a23ff7243`  
Comparison point: local `main` at `954a10b9a76960195ec5ecf552c89ea0d3e968d6`

## Assessment

The FSKit lifecycle has important fail-closed protections, including worker generations, a per-mount teardown lock, same-UID socket checks and a post-detach inventory check. The code also has paths that can retain decrypted-volume keys and a socket indefinitely, and exceptional worker exits that release the service without first proving that the attachment is gone. The highest-priority source concern is the latter because its impact can include interruption of an attached writable filesystem.

This is a **partial static audit**, despite the requested full audit. The review prioritized the modified macOS FSKit code, its immediate callers and selected protocol, volume, signing and CI paths. It did not exhaustively examine every line of the repository or every catalog taxonomy. No application execution, tests, playtest, live network probe, security scanner, dependency advisory lookup, or filesystem fault injection was performed. Findings below are source-derived and their runtime consequences are hypotheses unless explicitly stated otherwise. No conclusion here establishes cryptographic soundness, absence of vulnerabilities, or readiness to promote FSKit.

The comparison point is the local `main` tip, used as a convenient way to enumerate recent branch-specific modifications. It does not represent the full set of changes relative to upstream VeraCrypt. Some inspected code and risks predate that point. Determine modification provenance separately before attributing a finding to a particular author or change.

## Method and reproducibility

From the worktree root, the following read-only commands locate the reviewed scope and evidence. They read source and Git metadata only.

```sh
git rev-parse HEAD
git status --short --branch
git diff --stat 954a10b9 HEAD
git diff --name-only 954a10b9 HEAD -- src
git diff 954a10b9 HEAD -- src/Driver/FSKit/FSKitService.mm src/Core/Unix/CoreUnix.cpp src/Core/Unix/MacOSX/CoreMacOSX.cpp src/Platform/Unix/Process.cpp
nl -ba src/Driver/FSKit/FSKitService.mm | sed -n '256,282p;300,524p;610,750p'
nl -ba src/Core/Unix/CoreUnix.cpp | sed -n '1630,1647p;1724,1796p'
nl -ba src/Core/Unix/MacOSX/CoreMacOSX.cpp | sed -n '190,300p;332,467p;930,1058p'
nl -ba src/Driver/FSKit/VolumeProtocol.cpp | sed -n '110,160p;227,320p'
nl -ba src/Setup/MacOSX/verify_fskit_bundle.sh
rg -n 'AF_INET|AF_UNIX|getpeereid|URLSession|curl_easy|https?://' src/Driver/FSKit src/Core/Unix/MacOSX src/Platform/Unix src/Main
rg -n 'uses:|permissions:|wget |sha256sum' .github/workflows
```

Reproduction sequences in findings are **proposed fault-injection tests**. They have not been run in this audit. Use disposable fixtures and verify the exact image identity before any later live experiment.

## Findings

### F1 — Error exits can release a worker while its image remains attached

**Severity:** High potential impact. **Confidence:** Confirmed code path, runtime trigger and resulting damage unverified. **Evidence:** `src/Driver/FSKit/FSKitService.mm:440-444,504-521`.

The worker exits its loop when `poll` fails with an error other than `EINTR`, or when the listener reports `POLLERR`, `POLLHUP`, or `POLLNVAL`. Those paths reach `volume.Close()`, close both reservations and remove the endpoint without consulting `IsDiskImageAbsentAfterAuxiliaryUnmount`. The inventory gate at lines 383–397 applies to the ordinary auxiliary-loss path and does not guard these error exits.

**Reproduce from source:** Trace a committed worker with an attached writable image, inject a non-`EINTR` poll failure or listener error at lines 440–505, and follow the unconditional cleanup at lines 516–523. A future test should verify the exact image remains attached at the injected event and assert the worker does not report clean release. The practical frequency and ability to continue serving after a damaged listener need measurement.

**Impact and theory:** Premature loss of the decrypted block service can interrupt an active filesystem and may leave unsynchronized writes or an inaccessible attachment. This is a failure-path hypothesis, not observed corruption. A compromised same-user process or an OS failure might cause relevant resource errors, but no exploitability claim is made.

**Proposed solution:** Treat unexpected service failure as incomplete cleanup. Preserve the volume and reservations when feasible, surface a persistent actionable error, and require authoritative attachment absence before normal release. Where a permanently unusable endpoint makes service impossible, design an explicit fault state and recovery protocol rather than claiming the invariant can always be maintained.

### F2 — A failed late-media lookup may permanently disable automatic eject cleanup

**Severity:** Medium, with potentially significant confidentiality exposure through retained keys and a still-accessible auxiliary mount. **Confidence:** Confirmed control flow; real occurrence unverified. **Evidence:** `src/Core/Unix/CoreUnix.cpp:1735-1742`, `src/Driver/FSKit/FSKitService.mm:259-277,360-377,400-426,487-493`.

When initial discovery cannot correlate the attached image, the caller sends a zero identity. The worker sets `attachmentPending = false` and requests a late-media lookup. The helper returns zero after ten seconds or if it cannot obtain the attachment identity. Once it finishes, line 377 sets `observeLateMedia` to `attachmentPending`, now false. The automatic external-eject path at line 422 requires a nonzero `media`, so it does not start watching again.

**Reproduce from source:** Follow the zero-identity branch, then assume the inventory is unavailable for the helper's lookup period and recovers later. Observe that the helper's zero result leaves both `media` and `observeLateMedia` false. Proposed runtime test: on a disposable fixture, inject inventory failure past the lookup period, restore it, eject the image, and check whether the auxiliary mount, socket and worker remain.

**Impact and theory:** Native eject may leave an accessible worker and encryption context until a separate cleanup succeeds. An explicit dismount may still recover the volume if it remains discoverable. The actual GUI and operating-system behavior after eject is not established by this source trace.

**Proposed solution:** Retain a distinct unresolved-media observation state and retry with bounded backoff until the exact media is identified or authoritative safe cleanup is established. Surface an unresolved automatic-cleanup state and test recovery after a transient inventory failure.

### F3 — One visible image match masks other incomplete inventory records

**Severity:** Medium to High conditional on an ambiguous or duplicate attachment. **Confidence:** Confirmed parser behavior; reachability and destructive effect unverified. **Evidence:** `src/Core/Unix/MacOSX/CoreMacOSX.cpp:214-270,283-299,302-310,391-402`.

The parser marks a malformed record, missing image path, or unresolved plausible alias as uncertain. If any other record matches the expected path, lines 262–266 return the match before checking `uncertain`. A matching record plus an unidentifiable record therefore produces a usable device even though another record could refer to the same image. Explicit detach subsequently checks that selected device and media identity, but this parser does not establish that an unknown record is unrelated.

**Reproduce from source:** Construct an inventory containing an exact valid image record and a separate record with no `image-path`, or a plausible alias that cannot be resolved. Trace `uncertain = true`, followed by the early return for the exact match. A future unit test should check both record orders and an alias that points to a second attachment.

**Impact and theory:** A second attachment could remain after the selected image is detached. The post-detach check must still decline cleanup while unknown records remain, which limits the immediate risk. Whether macOS produces these combinations and whether detach of the selected device is safe in that state require validation.

**Proposed solution:** Model “matched but inventory incomplete” explicitly and prohibit destructive detach until the inventory establishes the intended ownership and conflicts. Keep ordinary non-destructive status display separate from permission to detach.

### F4 — A pending attachment can retain keys and reservations without a recovery handle

**Severity:** Medium. **Confidence:** Confirmed state transition; frequency and operator impact unverified. **Evidence:** `src/Core/Unix/CoreUnix.cpp:1638-1641,1755-1760`, `src/Driver/FSKit/FSKitService.mm:313-358,383-397,474-498`.

The caller sends the pending marker before entering `MountAuxVolumeImage`. A `MountServiceCleanupFailed` path closes the channel without a completion report. The worker preserves itself while `attachmentPending` is true and only clears that flag after seeing a matching image. If the attach never publishes, the worker can remain indefinitely. If the auxiliary mount is absent, normal discovery may lack a mount entry from which to drive a retry.

**Reproduce from source:** Trace a pending marker, an attach timeout, channel EOF, an absent auxiliary mount, and repeated authoritative empty image inventories. The exit condition at line 355 stays false while `attachmentPending` is true. A later test should use a disposable image and a fault-injected attach that never publishes.

**Impact and theory:** Availability and confidentiality can be affected by an orphaned worker, retained slot/backing-file reservations, and keys held in process memory. Retention is protective while completion is unknown; an empty point-in-time inventory by itself cannot prove that a timed-out OS request will never publish.

**Proposed solution:** Provide an operator-visible recovery record bound to the worker generation and exact image path, plus a safe reconciliation or explicit administrative recovery operation. Establish an OS-supported terminal condition for an attach before releasing an unseen pending worker.

### F5 — Per-volume reservation does not coordinate different backend families

**Severity:** Medium to High if the same container can be opened simultaneously across backends. **Confidence:** Source-evidenced limitation; cross-backend reproduction unverified. **Evidence:** `src/Driver/FSKit/FSKitService.mm:175-224,579-594`, `src/Core/Unix/CoreUnix.cpp:1377-1378,1418-1429,1489-1492`, `src/Platform/Unix/File.cpp:396-429`; backend selection at `src/Makefile:61-94`.

FSKit holds local lock files named from the backing file identity in its team-scoped application group. The code shown reserves against other processes that use the same lock convention. The generic file-open locking implementation is disabled by `#if 0` in `src/Platform/Unix/File.cpp:396`. The separate common volume reservation in `CoreUnix.cpp:1377-1378` is compiled only on Linux. A pre-mount `IsVolumeMounted` check exists at `CoreUnix.cpp:1428`; its visibility and atomicity across backend families remain to be established. The FSKit lock itself is not a universal cross-backend lock.

**Reproduce from source:** Follow `ReserveVolume` and search the FUSE backends for the same `mount-locks/file-<device>-<inode>` reservation. For a future test, use two disposable copies or a fully isolated host and verify all existing backend-specific open locks before attempting any simultaneous mount. Do not assume this finding proves that other existing file locking is absent.

**Impact and theory:** If no common OS-level exclusion covers a particular backend or alias, simultaneous writable mounts of one encrypted container could corrupt it. Whether the existing file-open layer independently prevents this is unresolved and must be traced and tested before calling this confirmed.

**Proposed solution:** Establish a common backend-independent reservation or verify that an existing kernel file lock reliably covers file aliases, devices and all supported backends. Add a two-backend rejection and retry test.

### F6 — A reused BSD disk identifier remains a check-to-use risk

**Severity:** High potential impact, low-confidence timing hypothesis. **Evidence:** `src/Core/Unix/MacOSX/CoreMacOSX.cpp:302-310,383-402,1033-1053`.

The code validates the exact image path and I/O Registry media ID, then starts `hdiutil detach` or `mount_msdos` with a BSD device path. Another actor or the operating system could theoretically remove the original media and reuse the device identifier between validation and the external command. The per-auxiliary lock serializes cooperating LambCrypt teardown requests but does not itself lock external Disk Images or Disk Arbitration operations.

**Reproduce from source:** Trace `ConfirmDiskImageMedia` immediately followed by the bounded subprocess. A future controlled test requires a disposable VM and deliberate device reuse between those operations. No such race was executed and actual macOS semantics may preclude or narrow it.

**Proposed solution:** Investigate an OS API that binds an operation to the original media object, or add stronger coordination and post-operation verification with explicit uncertainty handling. Keep the existing identity checks even if no stronger primitive is available.

## Security and data-safety coverage

| Surface | Source observations | Remaining uncertainty |
|---|---|---|
| Socket authorization | Server checks `getpeereid` against the owner. The client checks endpoint type, owner and permissions and verifies the peer UID. Generation-bound operations reject stale IDs. | Same-UID processes are inside this trust boundary. Initial inspect accepts a zero generation. The review did not establish whether OS sandbox rules prevent every other same-user process from reaching the endpoint. No exploit or exfiltration was attempted. |
| Read and write | Worker checks transfer limits, generation, volume protection and bounds. Unaligned writes use sector read-modify-write in `src/Volume/Volume.cpp:450-457`. Worker requests are served serially at `FSKitService.mm:504-512`. | Power-loss atomicity, cross-process interference, hardware flush guarantees and full VeraCrypt format compatibility require runtime tests and a cryptographic review. |
| Dismount | Exact-image inventory, media ID checks, worker identity checks, locking and flush exist. | F1, F3 and F6 identify failure or concurrency gaps. The static review cannot prove safe teardown in all OS states. |
| Backend selection | `src/Makefile:61-94` defaults both experimental selectors to zero and rejects selecting FSKit and FUSE-T together. | Cross-backend exclusion is unresolved in F5. |
| Network | The inspected FSKit transport uses local Unix sockets. Source search found GUI website links and release/CI network operations. | This is not an exhaustive network security assessment. No traffic capture, binary inspection, service scan or external endpoint probing was performed. |
| CI source archives | The two examined wxWidgets downloads verify a configured SHA-256 digest before extraction in `.github/workflows/build-linux.yml:161-164` and `.github/workflows/build-linux-big-endian.yml:114-117`. | The digest provenance and remaining dependencies were not independently checked. |
| Release | `src/Setup/MacOSX/notarize.sh` checks signatures, Hardened Runtime, secure timestamps and packaged content. The verifier checks identity, architecture and profile fields. | Current availability, authorization, expiry and real distribution acceptance of signing credentials were not examined. No notarization or installation was run. |
| Cryptography | The selected worker path delegates data transformation to `Volume` and uses `SecureBuffer` in the examined protocol. | Algorithm implementation, side channels, randomness, key derivation, disk confidentiality and all code outside the selected paths remain unaudited. |

## Coverage limits and next review

The catalog selected thirteen required lenses. All were loaded, but each received a focused pass rather than its complete inventory. Twenty-five total skill bodies were loaded. Some referenced shared catalog directory entries could not be loaded as files, while individual shared contracts and the security index were available. Catalog semantic retrieval reported a stale index and used deterministic fallback.

Review priority is F1 and F5, then F2 and F3. The Unix file-open lock is disabled. Trace cross-backend discovery and simultaneous startup before deciding whether cross-backend corruption is reachable. F6 requires an isolated OS-level experiment. The independent skill-adaptation and applicability record is in `codex-auditskill-analysis-23NOV2026.md`.
