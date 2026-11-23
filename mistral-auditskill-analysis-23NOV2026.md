# Agent-Skills Adaptation Analysis — VeraCrypt Full Audit

**Report ID:** `mistral-auditskill-analysis-23NOV2026`
**Date:** 23 November 2026
**Companion to:** `mistral-audit-all-23NOV2026.md`
**Purpose:** Per the audit mandate, this report documents (1) how the agent-skills catalog was used, (2) which skills were **designed for a different stack/surface and had to be adapted**, exactly how each adaptation was made, and (3) **which findings the adaptations produced that the native skills would not have surfaced** (or would have scored differently).

---

## 1. Catalog Usage

`search_skills` (via the `agent-skills` MCP connector) was called with an exhaustive-audit intent and the repo path. The catalog itself returned an **audit-suite selection**: 13 required lens skills, ~40 standalone candidates to triage with applicability gates, zero repository exclusions, and an optional consensus overlay (not requested). Each selected skill was loaded with `load_skill` plus its `000_common/audit-base/*` shared contracts via `load_skill_file`. **Every audit in this engagement ran under read-only authority** — skills carrying repair authority (`governance-code-polish`, deadcode-cleanup's cleanup stage) had their action phases clamped to inventory/report-only per the user's "Report only" mandate. Skills structurally inapplicable to a C/C++ desktop/driver codebase were excluded with reasons recorded in the coverage matrix of the main report (§2.4).

Retrieval-context note: the catalog's semantic index reported `index_stale`, so discovery ran in deterministic fallback mode ("deterministic_preserved: true") — selection was therefore reproducible from authored scoring, not on a live embedding.

---

## 2. The Two Layers of Adaptation

Even the *natively applicable* skills were written against web/managed-stack examples (Python/TS/Node, ORMs, pytest suites, web services). Two adaptation layers were therefore applied:

### 2.1 Universal adaptations (applied by all 20 audit agents)

| Skill language | Adapted to (VeraCrypt) |
|---|---|
| "Service boundary / route handler" | Core/Volume mutation functions; driver-vs-core module edges |
| "Transaction atomicity" | Crash-window analysis of multi-write on-disk header sequences (primary/backup header offsets, `Flush()` boundaries) |
| "Tenant isolation / multi-user web app" | Multi-user mount isolation (FUSE `allow_other`, FSKit per-user app-group containers, `getpeereid` socket gates, fast-user-switching sessions) |
| "Batch/N+1/queue" | Per-1 MB AF_UNIX socket connect/teardown; enumeration loops over mount tables; retry loops (`10×500 ms` control reads) |
| "Isolation level / pessimistic locking" | `flock` / `O_EXCL` / mount-slot and volume reservation lock files (and their `#if 0` compiled-out state) |
| "ORM/deserialization" | C++ `Serializer` wire format, volume-header `Deserialize`, FSKit C++↔Swift protocol frames |
| "Health endpoint / readiness probe" | FUSE/FSKit IPC surface, control-file reads, `WaitForServiceExit` handshakes |
| "Config/env drift" | `Tcdefs.h` version strings vs `.rc`/plist copies; `VERACRYPT_MOUNT_PREFIX`; build-flag matrices (`WITHFUSET`/`WITHFSKIT`) |
| "Discarded-entity/database records" | Mount-table entries, reservation locks, temp/aux mount dirs |
| "Test framework cost model" | The repo's raw-`main()` C++/Python harnesses, in-test compilation, `--wrap` fault injection |
| **Static mandate** | Every skill that mandates execution/measurement (timed runs, drills, PoCs) ran at its **static ceiling**; runtime-dependent confidence capped at Likely/Plausible per each skill's own calibration; magnitudes were never fabricated |

### 2.2 Explicit out-of-domain adaptations (the user-requested "adapt unrelated skills")

Three skills whose *entire declared surface* does not exist in this repository were deliberately adapted rather than excluded. For completeness: the catalog also offered other non-matching skills (`audit-security-supabase`, `audit-llm-config-drift`, `audit-graphdb-design`, `audit-go-repo-hardening`, `audit-kotlin-app`, `audit-mcp-server`, the `audit-secops-*` SOC family, `audit-playtest-app` — the latter excluded explicitly per the user's "don't run playtest"). Those were excluded, not adapted, because no faithful translation of their checks existed (no Supabase, no LLM config, no SOC telemetry, no Android/Flutter surface in this codebase); the three below had genuine analogues and produced real findings.

---

## 3. `audit-security-code` — web-backend flaw classes → C/C++ system code

**Designed for:** Python/Node/PostgreSQL/SQLite/Supabase backends (authorization, injection, privileged functions, unsafe parsing, secrets in logs, auth/session mistakes, tenant isolation).

**Adaptation map (per its CSEC-001..074 taxonomy):**

| Web class | C/C++ translation used |
|---|---|
| SQL injection (CSEC-011–014) | Non-literal `sprintf`/`strcpy`/`gets`, buffer copies with unparsed length fields, **language-pack strings used as printf format strings** |
| Command injection (CSEC-015) | `Process::Execute`/`ExecuteBounded`/`popen`/`execvp` with string args; PATH resolution in root-running code; `/sbin/mount -o` assembly |
| Tenant isolation (CSEC-001–006) | Multi-user mount isolation, app-group container boundaries, elevated-service client trust |
| Privileged functions / SECURITY DEFINER (CSEC-021–025) | Root CoreService loop, sudo/doas helper, `mount`/`umount`/`hdiutil`/`SetFileOwner` from root context |
| Unsafe deserialization (CSEC-026–030) | `VolumeHeader::Deserialize`, `Serializer` string ops, EMV TLV parser, XML; XXE declared a non-class (no DTD resolver) and replaced with hand-rolled-parser robustness |
| Secrets/log leakage (CSEC-041–045) | Password/PIM in exception strings/logs; `RLIMIT_CORE`/`PR_SET_DUMPABLE` exposure |
| Auth/session (CSEC-047–052) | Password caches, generation identifiers, `SUDO_UID` session identity, credential lifetime |
| Crypto (CSEC-055–057) | RNG sources, XTS key split — **plus "bespoke key material" remapped to RAM-encryption IDs** |
| Dropped: SSRF, redirects, JWT/cookies, CSRF, RLS | No equivalents exist |

**Findings the adaptation produced** (native lenses scored them lower or missed them):

1. **SEC-VC-001 (MED)** — FUSE volume ownership trusts a caller-influenced `SUDO_UID` env var with a silent `catch()` in the *root* service, feeding `-o allow_other` (`FuseService.cpp:1730-1741` vs the strict `GetRequesterIdentity` at `RequesterAccess.cpp:95-100`). The web-authn framing ("session identity established from client-supplied context in a privileged process") is what surfaced it; the native lenses treated SUDO_UID parsing as a logging/ownership nit.
2. **SEC-VC-002 (LOW)** — the root CoreService **mutates its own safety policy from request payload fields** (`AllowInsecureMount`, `UserEnvPATH`, `UseDummySudoPassword`, `CoreService.cpp:1231-1233`) — the "client controls the authorization config" pattern from web authz.
3. **SEC-VC-006 (INFO)** — language-pack strings passed **directly as printf format strings** (`StringCbPrintfW(szTmp, ..., GetString("PASSWORD_WRONG"))`, `Dlgcode.c:5942`) — the "untrusted template" injection analog.
4. **SEC-VC-004 (INFO)** — **RAM-encryption ID for cached passwords derived from heap pointer values** (`Cache.c:38-49`) — "bespoke crypto" class remapped to memory-obfuscation keys.
5. Plus the cross-user `lambcryptfs` mount-table filter gap (`MountedFilesystem.h:26-36`), `%n`-in-language-pack crash surface, `GetRealUserId` env-trust mirror.
6. Its strict non-finding inventory (serializer caps, TLV nesting caps, trusted-binary resolution, pipe-transported admin password) *also* raised the audited baseline confidence for the security claim set — a finding-of-absence the native security lens had partially, but not fully, enumerated with CSEC class bearings.

## 4. `audit-security-owasp` — OWASP Top 10 / API Top 10 → desktop + driver crypto app

**Designed for:** web apps/APIs (routes, headers, CORS, XSS, GraphQL, SSRF). **Adaptation:** each A01–A10 category was confirmed-or-dismissed against the desktop/driver surface; SSRF → local AF_UNIX IPC (`getpeereid` as the "auth at the binding" surface); A08 deserialization → `Serializer`/header/keyfile/zip-rescue-disk parsing; ASVS chapters V2/V3/V5/V6/V7/V14 walked statically. Dropped with cause: XSS/DOM/SQL/CORS/CSRF/security-header/typosquatting checks.

**Findings the adaptation produced:**

1. **SEC-VC-001-owasp (LOW)** — **PIM cached in cleartext in the unencrypted boot sector of system-encrypted volumes** (`BootConfig.cpp:70-77`) — a "sensitive data exposure at rest" determination no native lens made, because only an OWASP A02 walk asks "what secret lives in plaintext storage".
2. **SEC-VC-002-owasp (LOW/MED multi-user)** — `--password`/`--pim` on the command line exposed to `ps` for all local users (`CommandLineInterface.cpp:116,542-548`; the CI itself runs `--password test` at `build-linux.yml:212`) — "credentials in transit/storage" analog to arg leakage.
3. **SEC-VC-005-owasp (INFO design-risk)** — the FSKit worker grants **any same-uid process raw read/write of the whole decrypted volume** (`VolumeProtocol.cpp:230-236`, initial-Inspect all-zero generation always accepted) — expressed in API-security terms (object-level authorization within the trust boundary) this became an explicit, documented blast-radius decision instead of an unstated assumption.
4. The per-category coverage matrix itself (all 10 categories covered; only the BOLA-equivalent of the API Top 10 applicable) converted "we didn't check the web stuff" into **evidence that the right threat classes were systematically dismissed with reasons**, and named the residual blind spots (A04 business-logic mount-state machines, A06 vendored-CVE posture without a CVE database).

## 5. `audit-design-webapp` — web UI heuristics → wxWidgets desktop GUI

**Designed for:** six web gates (workflow/IA, design handoff, web standards/semantic HTML, WCAG accessibility, device/browser resilience, production readiness). **Adaptation map:** wizard-page flow → forms; `AskYesNo` **default-button semantics** → "destructive action confirmation" gate; semantic-HTML control types → wxGauge/validator appropriateness; WCAG → statically-verifiable subset only (mnemonics — verified present; single-input-modality entropy collection); design-token gate **dropped as meaningless** (wxFB-generated desktop app); production readiness → progress honesty/"lying status". Confirmation-dialog defaults are a web-UX heuristic that has a near-perfect desktop analog (Enter = default button), which is what made the run productive.

**Findings the adaptation produced** (17 findings; the native workflow-gui lens overlapped on ~4):

1. **WFG-VC-003 (HIGH)** — destructive confirmations **default to Yes**: header restore, force unmount, and `FORMAT_ABORT` all pass `AskYesNo(..., true, true)` so Enter accepts them — inconsistent with the wizard's own overwrite prompts that use safe defaults. This is precisely the class web-UX reviews call "dangerous default action"; the native GUI lens (operator-truthfulness framing) had skipped default-button semantics entirely.
2. **WFG-VC-001 (HIGH)** — mkfs executed inside the wx event handler on the GUI thread (Unity-of-thread/"long tasks block interaction" heuristic).
3. **WFG-VC-007 (MED)** — **security ceremony has a mouse-motion-only entropy input** — no keyboard/pointer-alternative path in `RandomPoolEnrichmentDialog.cpp:50-83`, `KeyfileGeneratorDialog.cpp`, or the creation wizard: the WCAG 2.1.1 keyboard-operability rule applied to the product's *core security ritual*; motor-impaired and eye-tracker users are structurally disadvantaged filling the 2,560-bit gauge.
4. **WFG-VC-010 (MED)** — "Next" on the *completion* page restarts the creation wizard on the same path with cleared credentials and an already-latched device-warning — a web-flow analysis ("affordance set of a final step") caught what the state lens saw as mere label choice.
5. WFG-VC-004/005/011/013–017 (MED/LOW): silent invalid-PIM dead-end, uncancellable/uninformative WaitDialog, brand split in dialog copy (286 "LambCrypt" vs 146 "VeraCrypt" strings), Busy-flag leak, partial-keyfile-success, unnamed `TC_WINDOWS` checkbox label.
6. It also produced the audit's strongest **positive** GUI finding by testing the heuristic rather than assuming: `VolumeSnapshot.h:36-46` + `MainFrame.cpp:1961-1982` staleness machinery judged "the strongest anti-lying-status design in the repo".

## 6. What the Adaptations Changed in the Aggregate

| Dimension | Effect of adaptations |
|---|---|
| Findings added | ~30 findings not produced (or produced at Info level) by the native lens set — incl. 2 of the engagement's High items (destructive-default prompts, GUI-thread mkfs) and the PIM-boot-sector exposure |
| Threat classes opened | secrets-at-rest in plaintext boot config; ps-visible argv credentials; sure default-button risk; a11y of crypto input; pointer-address-derived crypto IDs; language-pack format-string surfaces |
| Confidence discipline | the OWASP variant forced an explicit per-category confirm/dismiss matrix with named dismissals; the web-app variant's six-gate walk forced the a11y and flow checks to be *attempted and declared not-statically-checkable* rather than silently omitted |
| Cost | Each adaptation required a documented remap table (§3–5) before scanning; ~1 extra agent per adapted skill; no false positives traced to the adaptations (each adapted finding cites native code evidence and would be re-derivable from the remapped definition) |

## 7. Lessons for Future Runs Against This Repo

1. Keep the adaptation-as-documentation pattern: an adaptation table written *before* scanning both prevents semantic drift (web terms misapplied to C) and makes findings re-derivable.
2. `audit-playtest-app`, the `audit-secops-*` family, `audit-security-supabase`, and `audit-llm-config-drift` remain unadaptable here (no telemetry, no Supabase, no LLM config in-tree; playtest explicitly forbidden). If a SOC telemetry surface is ever added, reconsider the secops family.
3. `audit-multiagent-consensus` was not requested; this run nevertheless achieved de-facto cross-lens corroboration by running all lenses independently on the same tree and cross-checking at synthesis time (§5 of the main report) — a future run could load the consensus skill deliberately if formally scored corroboration is wanted.
4. Three catalog/tooling frictions to carry forward: the stale semantic index (fallback is fine but slower to justify), 16 k inline capture limits on `load_skill_file` (page the contracts), and `audit-security-code`'s missing `appsec-hardening/INDEX.md` (catalog supply gap — substituted with the CSEC taxonomy).

*End of companion report.*
