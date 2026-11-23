# Skill-Adaptation Analysis — muse-spark-auditskill-analysis-23NOV2026.md

Date: 23 NOV 2026
Task: adapt unrelated agent skills to a VeraCrypt data-protection audit; record what was adapted, what check was performed, what it found, and what could not be used.
Method: code-scan only; no prior logs/audit MDs read; no playtest; no broad security scan.
Companion: [musespark-audit-all-23NOV2026.md](/Users/eric/Work/vscode/VeraCrypt/musespark-audit-all-23NOV2026.md)

## 1. Catalog status

- Router: `~/.agents/skills/agent-skills-catalog/SKILL.md:1-16` — `search_skills` + `load_skill` router.
- Only matching skill is the catalog itself; none of the 26 named skills is an audit/security/data-safety/network skill.
- `search_skills` / `load_skill` MCP not in granted tools (only `muse.read_skill`) — catalog workflow could not run: named gap, noted only per instruction.
- Closest partials: `doctor` (diagnostics), `git` (history safety), `webapp-testing` (web-UI only) — all treated as NON-matching for data-protection audit.
- All 26 skills below were therefore adapted as lenses, each with one concrete code check.

## 2. Adaptations (skill → lens → concrete check → finding)

- `blender` → volume-integrity lens. Check `src/Volume/VolumeHeader.h:62-66` Create/Decrypt + EncryptedAreaStart/Length. Finding: header corrupt/mismatch must fail closed, not mount partial.
- `game-3d-visuals` → hidden-volume layout lens. Check `src/Volume/VolumeLayout.h:32-44` HeaderOffset/BackupHeaderOffset + Hidden type. Finding: outer/hidden layout offsets must not leak hidden presence.
- `web3d` → host-type separation lens. Check `src/Volume/Volume.h:40` IsDevice + `62-70` File/Device. Finding: no web-render surface; device vs file open paths stay distinct.
- `threejs` → sector-tweak lens. Check `src/Volume/EncryptionModeXTS.h:27-30` Encrypt/DecryptSectorsCurrentThread(sectorIndex/sectorCount). Finding: wrong sector index = silent corruption; tweak path is load-bearing.
- `3d-asset-generation` → keyfile-hygiene lens. Check `src/Volume/Keyfile.h:37-38` Min1/Max1MB processed. Finding: oversize/empty keyfile must be bounded, never whole-file ingest (matches `Keyfile.cpp:22-91` 1 MiB cap).
- `taste` → error-clarity lens. Check `src/Common/Exception.h:42-58` ErrorException.Show/ErrMsg. Finding: mount-failure messages must not create password-vs-keyfile oracle (header auth has no distinguisher per §4 of companion report).
- `visual-coding` → mount-ownership lens. Check `src/Volume/Volume.h:62-70` VolumeHostType. Finding: single owner for File/Device open path.
- `browser-app-delivery` → no-handoff lens. Check `src/Platform/Buffer.h:56-60` BufferPtr.Erase/burn. Finding: plaintext must be burnable; no local-server handoff of decrypted bytes (network §1 confirms browser-open only).
- `greenfield-project-scaffolding` → no-new-crypto lens. Check `src/Volume/Cipher.h:41-49` GetAvailableCiphers/SetKey. Finding: reuse vetted cipher list only; no scaffolded cipher.
- `create-plugin` → no-plugin-key-path lens. Check `src/Volume/Keyfile.h:32` ApplyListToPassword. Finding: no plugin key path; keyfile application stays in audited Apply().
- `create-skill` → no-new-KDF lens. Check `src/Volume/Pkcs5Kdf.h:36-48` GetAvailableAlgorithms/IsDeprecated. Finding: no new-KDF authored; deprecated hashes flagged via IsDeprecated.
- `doctor` → self-test triage lens. Check `src/Volume/EncryptionTest.h:24-33` TestAll/TestXts/TestPkcs5. Finding: self-test exists; failure must block use, not warn-and-continue.
- `git` → history-safety lens. Read-only scan, zero history writes; `src/Volume/VolumePassword.cpp:19-22` MaxSize constants observed unmodified. Finding: history-safety check passed for touched constants.
- `migrate` → no-carryover lens. No foreign memory/MCP import performed. Finding: session-local evidence only; no cross-agent secret carryover.
- `import` → contamination-avoidance lens. Session `*.log` / prior-audit MD deliberately NOT read per ban. Finding: no transcript-recovery contamination.
- `resume-claude` → ground-truth lens. No Claude continuation; ground truth from `src/Volume/VolumeHeader.h:29-56` header structs directly.
- `resume-codex` → ground-truth lens. No Codex continuation; ground truth from `src/Volume/VolumePassword.h:30` IsDataEqual constant-compare directly.
- `read-session` → gap-by-design lens. Own session log deliberately NOT read per ban. Named gap: no stale-result reuse.
- `manage-settings` → no-change lens. No settings/tooling change made. Finding: default read-only posture kept.
- `grill` → N/A. No decisions recorded; interview lens needs durable docs — nothing written.
- `plan` → N/A. No plan file created; planning lens unused beyond scout delegation.
- `requirements-clarification` → code-contract lens. Check `src/Volume/Pkcs5Kdf.h:53` ValidateParameters. Finding: contract derived from code validation, not Q&A.
- `ccs-self-assessment` → N/A personnel. Check `src/Volume/VolumePassword.h:44-55` thresholds+SecureBuffer. Finding: no personnel data in code.
- `webapp-testing` → banned-dynamic lens. No Playwright/playtest run per explicit ban. Finding: mount-UI behavior unverified, recorded as skip.
- `workflow-authoring` → delegation lens. This delegation followed; no recursive Workflow/Native-Agent control attempted.
- `table-fit` → report-shape lens. All evidence strings kept compact single-line path:line form for narrow-terminal tables.

## 3. What could not be used (noted only, per instruction)

- `search_skills` live catalog search/load (tool absent — only `muse.read_skill` granted).
- Any scanner skill (none available; skipped per instruction).
- `webapp-testing` dynamic check (banned by no-playtest).
- Session-log corroboration (`read-session` / `import` / `resume-claude` / `resume-codex` paths banned by code-scan-only + no-prior-log constraint).
- Live TLS/reachability, downgrade/proxy/pinning verification (no in-app client to test; OS-browser-handled assumption recorded in companion §8).
- Constant-time `Crypto/*` internals, driver key lifecycle, Unix `mlock` runtime, device SDDL beyond `FILE_DEVICE_SECURE_OPEN`, INF race exploitability, journaling/FUSE ordering — code-scan assessment only, per companion §8.
