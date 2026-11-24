# FSKit writable exFAT and APFS integration gate

This historical design started from `ce521cefb91dc6e68125d17166b9323ff36e54fd`
on November 23, 2026. For the current personal-use requirements, activation
procedure, and verified filesystem results, see the
[migration matrix](../FSKIT-MIGRATION.md#personal-use-verification-november-23-2026)
and [local maintenance runbook](../fskit-reactivation-runbook.md).

## Goal

Support safe, persistent writable mounts of exFAT and APFS inside LambCrypt's
VeraCrypt-compatible encrypted block device using **Apple's existing filesystem
drivers**. Keep FSKit as the sole macOS block-image provider. Do not introduce
macFUSE, FUSE-T, or a custom APFS/exFAT implementation.

## Existing path to preserve

`src/Core/Unix/MacOSX/CoreMacOSX.cpp::MountAuxVolumeImage` detects unpartitioned
FAT12/16/32 and routes it through `hdiutil attach -nomount` plus
`/sbin/mount_msdos`. Everything else currently goes through normal Disk Images
filesystem auto-selection. Keep the FAT path and its exact image/media validation.

Do not infer that read-only exFAT passing means writable exFAT passes.
APFS needs separate GPT/APFS-container handling, not the FAT boot-sector path.
A Disk Images device can have multiple partition/synthesized APFS devices and
mount points; do not assume one `/dev/diskN` or one `system-entities` record.

## Stage A — gated, disposable native controls

1. Require Apple Silicon macOS 26+, a properly signed/activated FSKit extension,
   an isolated signed scratch app, and no existing LambCrypt/VeraCrypt mounts.
2. Create fresh, sizeable, disposable encrypted file containers with NO
   filesystem. Record fixture path, inode, volume size, worker identity, and
   prior Disk Images/mount inventories.
3. Mount each encrypted fixture attach-only. Before **any** format command,
   confirm that the target disk belongs to the exact `aux/volume.dmg` in
   `hdiutil info -plist`, and that the worker maps to that exact disposable
   encrypted container. Revalidate immediately before the operation. Never
   format a device selected solely by its current BSD name.
4. exFAT: format a disposable test device using the OS's exFAT formatting path.
   APFS: create a GUID partition layout and an APFS container/volume using
   Apple's `diskutil` facilities. Record actual physical-store, container,
   and synthesized volume identities returned by the OS. Confirm that all
   partitions fit within the encrypted block-device geometry.
5. Detach the test disk cleanly. Mount ordinarily through the production
   LambCrypt FSKit path and let Disk Images select the filesystem.
6. Confirm that the intended exFAT/APFS volume, not the auxiliary FSKit mount,
   appeared with the intended read/write mode and target mount directory.
   Confirm **all** Disk Images child devices belong to the one exact image.
7. Create a file tree; exercise random/unaligned writes, overwrite, truncate,
   rename, delete, timestamps, fsync and close; verify expected hashes.
   Verify exFAT/APFS-specific metadata only where supported by the OS.
8. Test busy unmount refusal, retry after handles close, and Finder/Disk
   Arbitration eject. Check that no image, synthesized APFS container, mount,
   worker, socket, or reservation is left without reporting incomplete cleanup.
9. Mount read-only and verify content hashes/metadata. Use an independent
   VeraCrypt reader to verify the decrypted image, including any GPT and
   APFS metadata; verify that independent read does not mutate ciphertext.
10. Repeat on a clean signed Tahoe VM and on the physical Mac after its FSKit
    `enabled=false` activation blocker is resolved.

Use all-new fixtures. Preserve failed artifacts for diagnosis, and never run
format/erase/repair on an existing user's volume.

## Stage B — production mount and discovery changes, only where controls fail

- Prefer the existing Disk Images auto-selection if both filesystems mount
  correctly. Do not force an explicit driver unnecessarily.
- If auto-attach fails while a verified attach-only mount works, implement a
  narrowly scoped, **single-attempt** attach-only plus Disk Arbitration /
  `diskutil mount` fallback. Only do this after confirming that the exact
  attachment exists, and never blindly reattach an unresolved image.
- For APFS, support the hierarchy of physical store, synthesized APFS
  container, child volume, and volume mount point. Select the actual
  mountable volume without assuming `diskNs1` or a single `mount-point`.
- Preserve arbitrary volume identifiers; identify by I/O Registry / Disk
  Images parentage, not recycled BSD names. If multiple APFS volumes are
  present, either support them explicitly in discovery and dismount, or
  reject with a clear unsupported-layout error; never silently choose one.
- Reconcile `VolumeInfo`, GUI/CLI listing, user mount path, busy detection,
  teardown and Finder eject against **all** OS volumes for the one encrypted
  attachment. A failed detach must keep keys, worker, and reservations.
- Preserve read-only enforcement, no-filesystem/attach-only modes, FAT/HFS+
  behavior, and existing test semantics.
- Never perform automatic APFS conversion, repair, diskutil erase, or
  formatting as part of a normal mount.

## Stage C — tests

Extend `Tests/test_macos_discovery.py` with mocked Disk Images inventories:
- exFAT one-device mount; APFS GPT parent + partition + synthesized container
  + mounted volume; multiple APFS volumes; no mounted volume; stale identities.
- Read-only and writable modes, custom/default directories, attach-only.
- Partial attachment, delayed publication, busy failure, missing inventory,
  failure to resolve exact image/media ownership.
- Finder eject and independent multi-volume teardown.
- Confirm FAT detection continues to use the old explicit kernel route.

Extend `Tests/test_macos_gui_lifecycle.py` or add an equally guarded, signed,
disposable integration runner for --fskit-exfat and --fskit-apfs. Do not report
native PASS until those modes actually run. Include explicit negative tests
that refuse non-disposable physical disk identifiers and active user volumes.

## Release gates

| Case | Required result |
| --- | --- |
| exFAT read-only | revalidate existing baseline on current signed build |
| exFAT read-write | new signed native write/fsync/eject/remount/hash PASS |
| APFS read-only | new signed native GPT/container/volume mount PASS |
| APFS read-write | new signed native write/fsync/eject/remount/hash PASS |
| APFS multiple volumes | supported with complete discovery/teardown OR fail-closed documented restriction |
| FAT12/16/32, HFS+ | previous successful matrix passes on changed build |
| worker lifetime | no worker released with an attached child disk/image |
| activation | FSClient reports enabled and actual mount succeeds |
| release | distribution signing, notarization, installation remain separate gates |

## Design constraints

No new macFUSE dependency. No privileged global policy changes. No edits to
real encrypted containers. No blind forced dismount. No broad auto-retry of
Disk Images attach. No APFS filesystem reimplementation. Do not confuse
passing an OS-only raw-disk control with an integrated signed FSKit result.

## Required report

For each filesystem, report exact host/build, fixture layout, code commit,
backend/driver, mount and image identities, write and read-only verification,
busy retry, Finder eject, final inventory, and PASS/PARTIAL/FAIL/NOT TESTED.
Distinguish source changes and tests from expectations.
