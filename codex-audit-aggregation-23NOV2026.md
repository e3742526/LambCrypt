# LambCrypt audit aggregation and repair

November 23, 2026. Baseline `codex/fskit-read-write-mvp` at `271c85a58b4a7151c65149634db33f0a23ff7243`. The tracked tree was clean. The two November 23 audit files were present as untracked reports.

The initial patch set ended at `c2ff6499e8738a31acfab2b563bcd8fa9d0f12e6`. The three audit reports remain local files.

- `03689779ced12dc4526b5397d1b836412e38d1fb` preserves attachment ownership through worker faults.
- `10bd008c0dda832dc83970f318a661d245667b69` reserves local macOS backing files across mount backends.
- `c2ff6499e8738a31acfab2b563bcd8fa9d0f12e6` records the repairs and validation.

The [November 23 source audit](codex-audit-all-23NOV2026.md) supplies the six finding IDs below. The [skill adaptation report](codex-auditskill-analysis-23NOV2026.md) maps lenses to the same findings. The [November 21 source audit](SOURCE-AUDIT-2026-11-21.md) and its repair status are historical context. The older security repair plan is a historical campaign record.

| ID | Source finding | Disposition and verification |
| --- | --- | --- |
| F1 | Listener and poll errors bypassed attachment verification. | **Patched.** Worker reports the polling failure, backs off and continues attachment observation. The regression injects syscall and listener faults, checks continued service, and checks release only after verified absence. A permanently damaged listener may leave I/O unavailable while the worker retains the backing file. |
| F2 | A zero result could permanently stop observing the media. | **Patched.** Worker retries inconclusive lookups with a five-second backoff. The regression returns zero and then a valid media ID. |
| F3 | A valid positive match could hide unresolved inventory records. | **Patched.** Detach requires sufficient inventory to establish ownership. The regression exercises a match before and after an unresolved record, checks refusal before any teardown command, and preserves positive discovery for display. |
| F4 | Startup could leave a retained worker with no persistent recovery indicator. | **Patched for recovery visibility.** A failed handoff with a pending attach creates a private `attachment-pending` indicator. The error supplies the exact image locator. Native delayed publication checks that the marker and resources are cleared after confirmed detach. A request that never publishes can still retain its worker until macOS supplies conclusive evidence. |
| F5 | Local macOS file containers lacked atomic exclusion across backend builds. | **Patched for local regular files.** Each backend takes an exclusive inode lock on its existing backing descriptor before dispatch. The tests verify read-only acquisition, hard-link contention, and retry after release. The production FUSE-T service held the lock through a real mount and released it on dismount. Remote files, raw devices and previously launched older binaries fall outside this guarantee. |
| F6 | BSD device identifiers cross the boundary between identity validation and external commands. | **Unverified wrong-device outcome.** The source establishes a time window. Reuse of the identifier in that window and a resulting wrong-device operation remain hypothetical. Existing image and media revalidation remains in place. Further work needs a safe way to verify operating-system semantics and evaluate media-bound operations. |

Worker retention, exact media identity and backend opt-in behavior are governed by [FSKit-MIGRATION.md](FSKIT-MIGRATION.md) and the [lifecycle contract tests](Tests/test_macos_discovery.py). The worker and inventory work share the ownership invariant. The local inode reservation is acquired before any backend starts and survives the handoff through the open file description. The repair leaves the socket protocol and encrypted volume format intact.

The November 21 source audit records F-01 through F-10 and F-12 as fixed. Its F-11 records the documented shared Windows cache policy. The current Unix `--slot` parser uses wxWidgets `ToULong`, which rejects trailing characters. The rebuilt default client rejected `--list --slot=1X` with exit status 1.

## Verification on arm64 macOS 26.6.2 (25G83)

The refreshed development-signed FSKit, FUSE-T and default macFUSE bundles built and passed the crypto self-tests. The FSKit verifier passed architecture, deployment target, identities, signatures, App Group and development provisioning. The distribution-mode verifier rejected the development profile as expected.

Run the focused regressions with paths pointed to the matching scratch builds.

```sh
python3 -B Tests/test_macos_discovery.py --platform-archive "$VC_FSKIT_BUILD_SRC/Platform/Platform.a"
python3 -B Tests/test_fskit_volume_protocol.py --build-dir "$VC_FSKIT_BUILD_SRC"
python3 -B Tests/test_macos_fskit_worker_lifecycle.py --build-dir "$VC_FSKIT_BUILD_SRC"
python3 -B Tests/test_macos_gui_lifecycle.py --cli-only --binary "$VC_FUSET_BINARY"
bash src/Setup/MacOSX/verify_fskit_bundle.sh "$VC_FSKIT_BUNDLE"
```

| Check | Result |
| --- | --- |
| Injected startup, worker retention, incomplete inventory, reservation and cleanup regressions | **PASS** |
| FSKit worker protocol and Swift provider | **PASS.** Direct invocation with disposable fixtures. |
| Native Disk Images retention and multi-volume drill | **PASS.** Real APFS-backed read-only attachments and production workers with injected mount-table observation. |
| Native FUSE-T FAT write, sync, checksum on read-only remount and reservation handoff | **PASS** |
| Existing signed FSKit module activation and actual filesystem teardown | **NOT TESTED in this repair.** The previously diagnosed OS-disabled state was left as requested. |
| Live macFUSE fallback, Developer ID distribution, notarization and clean install | **NOT TESTED.** The macFUSE driver and distribution steps were outside the available validation environment. |

Disk Images inventory, the mount table and process inspection showed no scratch attachments, mounts or workers after the tests. The activation and release prerequisites remain gates for default-backend promotion.

## Follow-up repair

The branch ends at `f9e6452d50636d7ea354a17be564047c7324f0a8`, which records the follow-up verification and remaining release gates.

- `435752fc` addresses F4's failure classification. Before subprocess launch, rollback may proceed. After launch and before a confirmed normal exit with complete output, interruption leaves the submitted request undetermined. The mount caller keeps its worker and skips the attach retry. The subprocess and discovery tests cover pre-launch failure, normal completion, timeout, signal termination and output loss. A request that never publishes still needs conclusive OS evidence before release.
- `704f18a1` mitigates F6 on the kernel FAT route. The raw-device descriptor spans the kernel command and both image and media are confirmed after open. The test refuses a changed identity or an open failure before launch, verifies the hold inside the command, and checks descriptor release. The mount command resolves the device by name. The descriptor protects the BSD slot while it is open. The explicit detach path still has a name-based handoff after exact ownership validation.

The refreshed discovery, subprocess, Swift provider and two-attachment worker drills passed. Native FAT12, FAT16 and FAT32 raw scratch images passed writable mount, sync, checksum verification after read-only remount and cleanup. This exercise validates the raw descriptor at the native mount boundary. All three refreshed builds passed crypto self-tests, and the FUSE-T client passed its native disposable FAT lifecycle trial. The production signed FSKit path remains gated by effective host enablement. The fresh signed probe returned 3 for a different registered bundle, and FSClient reported that registered module disabled. PlugInKit still recorded a positive election.

The arm64 development installer payload passed offline checks. Distribution mode refused the development profile as expected. The host signing keychain exposed neither Developer ID identity and the macFUSE kernel extension was absent from the loaded inventory. The final Disk Images, mount and process inventories found zero scratch attachments, mounts and workers.
