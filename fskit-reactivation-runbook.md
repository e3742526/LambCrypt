# FSKit Reactivation Runbook — 23 NOV 2026

Prepared from live-machine diagnosis on the physical Mac (macOS 26.6.2, 25G83).
Companion evidence: `.fskit-preboot-snapshot-23NOV2026/` (pre-reboot state baseline).

## Diagnosis recap (one paragraph)

Signature, profile, device authorization, app group, TCC and Finder association all
verified GREEN on this machine. The block is two machine-local state layers:
(1) fskitd's authoritative enablement record (written only via System Settings'
File System Extensions **category sheet**) has never been committed — 30h of
fskitd logs contain zero `setEnabledState` events; every "positive election"
observed so far is a non-authoritative PlugInKit record. (2) The appex's
ExtensionKit adoption was broken by the registration surgery + the
1.29.1 → 1.27.1 version downgrade-restore (missing
`~/Library/Application Scripts/io.github.e3742526.LambCrypt.fskit.module`
artifact, absent from fskit_agent's inventory). Reference precedent:
FUSE-T issue #104 (same OS family, same symptom, closed — category sheet is the
authoritative toggle; the "By App" view is unreliable).

## Phase 1 — NOW (before reboot; all user-level, safe with other processes running)

### 1.1 Quarantine stale container state (reversible)
No LambCrypt processes are running, so all of this is dead state:
```bash
GC=~/Library/Group\ Containers/4K5Z4MZ8ZU.lambcrypt-fskit
Q=_quarantine-preboot-20261123
mkdir -p "$GC/$Q/mount-locks"
# stale mount-point dirs (4, Nov 21-22):
mv "$GC"/lambcrypt-fskit.???????? "$GC/$Q/" 2>/dev/null
# stale UUID worker/session dirs (6, Nov 21-22; identify by names NOT in Library/mount-locks):
for d in "$GC"/*/; do case "$(basename "$d")" in
  [0-9a-f][0-9a-f][0-9a-f][0-9a-f]-*) mv "$d" "$GC/$Q/";; esac; done
# stale flock identity locks (145 files, all attached to dead processes):
mv "$GC"/mount-locks/file-* "$GC/$Q/mount-locks/" 2>/dev/null
# verify container is now clean:
ls -la "$GC" && ls "$GC/mount-locks" | wc -l    # expect: Library/ + mount-locks/ + quarantine dir only
```
Why: these are untouched residue from two days of failed activation trials. A clean
container makes the post-reboot trial unambiguous — any new artifact you see afterward
came from THIS attempt. (Longer-term fix remains code: add the startup stale-worker
sweep this residue proves is missing.)

### 1.2 Build and sign the probe (measurement hardening)
Unsigned/ad-hoc probes can be silently filtered by fskitd (`getTeamIDForToken` —
observed live). Compile and sign ONCE now:
```bash
cd /Users/eric/Work/vscode/VeraCrypt
swiftc Tests/check_fskit_activation.swift -o build/fskit-probe
codesign -s "Apple Development: <your identity>" --entitlements <(cat <<'EOF'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict/></plist>
EOF
) build/fskit-probe
# sanity: exit 2/3/1 interpretations remain as documented; absence-of-module from a
# SIGNED probe is now trustworthy.
```
(If the sandbox-free entitlement step fights you, a plain `codesign -s` without
entitlements still gives fskitd a team-mappable token — that's what matters.)

### 1.3 Build the reinstall package — forward-only versioning
Bump the SAME number pair you used for the 1.29.1 trial to **1.29.2 or higher**
(both app and appex `CFBundleVersion`, matching numbers). Rule for this machine
going forward: the same bundle ID must NEVER see a lower version than any version
previously registered on it. Build + sign + run your normal
`make prepare`-equivalent and `src/Setup/MacOSX/verify_fskit_bundle.sh`, and stage
the productized pkg — do not install yet.

## Phase 2 — REBOOT
Plain restart. No other prep needed. `/private/tmp` residue clears on boot;
launchd restarts fskitd; the login session gets a fresh fskit_agent.

## Phase 3 — POST-REBOOT (in this exact order)

```bash
# 3.1 Registration survived the reboot?
pluginkit -mDAvv | grep -A3 e3742526                     # expect the module line w/ correct path
ls ~/Library/Application\ Scripts/ | grep LambCrypt.fskit.module   # may be absent until install

# 3.2 Install the staged 1.29.2 pkg (normal installer flow).

# 3.3 Adoption artifact check (the thing broken today):
ls ~/Library/Application\ Scripts/ | grep LambCrypt.fskit.module   # expect it to EXIST now

# 3.4 Stream while you flip the authorize toggle:
/usr/bin/log stream --style compact --predicate 'process == "fskitd"'
# 3.5 In System Settings → General → Login Items & Extensions →
#     by-category File System Extensions → ⓘ → toggle "LambCrypt FSKit" ON.
# 3.6 In the stream you EXPECT:
#   "Call fskit_agent to set enabled state of identifier io.github.e3742526.LambCrypt.fskit.module to (1)"
```

### Branch A — the setEnabledState line appears
Verify with the signed probe:
```bash
build/fskit-probe /Applications/LambCrypt-FSKit.app; echo "exit=$?"   # 0 = enabled
```
Then run migration gate 1 (disposable container: mount, write, sync, dismount,
read-only remount). If the probe says disabled despite the log line, save the
next ~20 fskitd lines after it — that subset names the persist failure.

### Branch B — the line NEVER appears when you flip the toggle
The sheet refused silently. Re-run 3.4–3.5 once after a logout/login (not full
reboot). If still nothing, capture BOTH streams during the attempt:
```bash
/usr/bin/log stream --style compact --info --predicate \
 'process == "fskitd" OR process == "fskit_agent" OR process == "FSKitModuleManagement"' \
 > /tmp/enablement-attempt.log
```
…and stop. That file contains the refusal reason; don't churn further state.

## Evidence diff (optional, after the module works)
```bash
SNAP=.fskit-preboot-snapshot-23NOV2026
diff <(pluginkit -mDAvv | grep -A9 e3742526) <(grep -A9 e3742526 $SNAP/pluginkit-full.txt)
```

## Hardening backlog surfaced by this incident (code, not state)
1. Startup sweep for stale worker dirs / mount-locks in the app-group container
   (this runbook's Phase 1 had to do manually what `FSKitService` never does).
2. `verify_fskit_bundle.sh`: add (a) signed-probe build+check, (b) an
   enumeration assertion (module listed AND `isEnabled`), (c) a version
   monotonicity precheck against the machine's highest-registered version.
3. Mount-time diagnostic (FSKitService.mm " is disabled!" path): distinguish
   not-registered vs registered-disabled vs enabled, and point the user at the
   *category sheet* specifically, where the current message points at the pane.
4. Migration notes should record fskitd enablement state (not PlugInKit
   elections) as the gate metric — today's notes tracked the wrong store for
   three sessions.
