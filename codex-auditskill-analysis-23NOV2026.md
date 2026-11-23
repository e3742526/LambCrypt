# Agent-skills audit adaptation record

Date: 23 November 2026  
Code revision: `271c85a58b4a7151c65149634db33f0a23ff7243`

The request required a full agent-skills audit, source-only evidence, no playtest, no code changes, and two reports. The catalog was searched against the FSKit branch worktree. Its exhaustive selection returned thirteen required lenses and standalone candidates. Retrieval used deterministic fallback because the semantic index was stale. The initial search with a limit of 30 was rejected because the server permits at most 20. The valid retry returned the selection.

This is a record of **adaptation and incomplete coverage**, not certification that each skill's exhaustive completion criteria were met. Skills and shared instructions are instructions, while all repository observations in the companion report come from source and Git metadata. Existing logs and previous audit reports were not inspected. No runtime tests, network scans, dependency advisory scans, fuzzing, GUI playtest, or target execution were performed.

## Required lens adaptations

| Catalog lens | Adaptation to a native encrypted filesystem | Findings or result |
|---|---|---|
| `audit-architecture-seam` | Followed the caller, worker, FSKit extension, Disk Images and subprocess ownership boundaries. | F1, F2 and F5 expose ownership and teardown seams. |
| `audit-dataflow-cascade` | Followed a failed inventory or helper through worker state and cleanup. | F1 and F2. Full cascade inventory remains open. |
| `audit-compliance-posture` | Examined source-visible signing, entitlement and release controls. No regulatory or certification claim was inferred. | Release gates described in the main report. Compliance requirements were not supplied. |
| `audit-dataflow-concurrency` | Treated per-volume locks, two backend processes and recycled BSD numbers as concurrency boundaries. | F5 and F6 are conditional hypotheses. |
| `audit-dataflow-integrity` | Followed writes through the socket to sector write and sync, and inventory through detach. | F1, F3, F5 and F6. End-to-end integrity is unverified. |
| `audit-dataflow-input-output` | Read protocol framing, size and offset checks, socket peer validation and subprocess return paths. | Controls documented in the coverage table. Complete input inventory is open. |
| `audit-invariant-sync` | Compared intended worker retention and generation checks across startup, eject and error paths. | F1 and F2. |
| `audit-negative-space` | Looked for missing cleanup, missing retry and missing common backend reservation. | F1, F2, F4 and F5. |
| `audit-reliability` | Traced timeout, helper failure and incomplete-inventory behavior statically. | F1–F4. |
| `audit-security` | Applied authorization, local IPC, subprocess and supply-chain questions to a native desktop app. | Same-UID trust boundary and CI archive checks documented. No penetration test was performed. |
| `audit-dataflow-state-transition` | Mapped attachment pending, media known, auxiliary absent and worker exit conditions. | F1, F2 and F4. |
| `audit-dataflow-temporal` | Traced delayed publication and the interval between media-ID confirmation and subprocess execution. | F4 and F6. |
| `audit-workflow-gui` | Restricted to source-visible mount/dismount and incomplete-cleanup reporting. No interactive GUI exercise. | Recovery visibility is part of F2 and F4. GUI coverage remains incomplete. |

## Standalone skills loaded for applicable source lenses

The following catalog skills were loaded and used selectively. Their full checklists were not exhausted: `audit-security-code`, `audit-security-owasp`, `audit-dependency-criticality`, `audit-failsafe-readiness`, `audit-contract-internalapi`, `audit-memory-lifecycle`, `audit-resource-lifecycle`, `audit-recovery-idempotency`, `audit-security-repo-triage`, `audit-deadcode-cleanup`, `audit-architecture-drift`, and `audit-operator-signal`.

The security-code and OWASP skills emphasize web and managed-language examples. Their applicable ideas were translated to native Unix socket peer identity, path ownership, cryptographic state and subprocess boundaries. This contributed the socket trust-boundary and CI archive analysis. Web session, HTTP route and database-specific checks were not represented as passed.

The resource, dependency, failsafe and recovery lenses were mapped to worker process lifetime, disk inventory authority, attachment reconciliation, key retention and actionable operator state. This contributed F1–F4. Managed-heap accumulation was not measured and no runtime resource-growth claim is made.

The internal contract, architecture drift and dead-code lenses informed the source comparison and caller tracing. No whole-repository reachability proof or dead-code removal inventory was completed. The operator-signal lens informed the missing recovery-handle assessment in F4.

## Other standalone candidates triaged

- `audit-contract-crossrepo` requires a separately identified producer/consumer repository and was not completed. The upstream dependency was not audited as a second repository.
- `audit-equation-sourcebase`, `audit-graphdb-design`, `audit-security-supabase`, `audit-flutter-ios`, `audit-kotlin-app`, `audit-go-repo-hardening`, `audit-architecture-nodejs`, `audit-security-nodejs`, `audit-mcp-server`, `audit-agent-orchestration-code`, `audit-security-llm`, and `audit-llm-config-drift` target stacks or services not established as relevant to the reviewed native FSKit paths. They were not claimed as completed audits.
- `audit-pipeline-externalapi` and `audit-dataflow-pipeline-graph` were only adapted conceptually to Disk Images and build boundaries. No randomized end-to-end pipeline testing or third-party service assessment was run.
- `audit-optimization-opportunities`, `audit-performance-profile`, and `audit-testsuite-economics` need measured workloads. A source-only audit cannot substantiate their performance claims.
- `audit-design-webapp` and `audit-design-handheld` target unrelated visual surfaces. `audit-playtest-app` was expressly excluded by the user.
- `audit-security-vuln-harness` calls for independent multi-agent and validation phases. This report does not claim those phases occurred.
- `audit-security-repo-posture` requires additional operational coverage. Source-level CI and release observations were included without claiming a full posture audit.
- `audit-repo-state-reconciliation` depends on logs and prior reports, which the user excluded. `audit-repo-path-consistency` was limited to recording the actual worktree and revision.
- The four `audit-secops-*` candidates depend on telemetry, incidents or detection infrastructure. They were not applicable to this code-only request.
- The catalog's optional `audit-multiagent-consensus` overlay was not selected by the catalog and no independent consensus is claimed.

## Catalog access and limits

Twenty-five selected skill bodies loaded successfully, along with individual common audit and engagement contracts. Two catalog entries representing shared directories, `000_common/checklists/appsec-hardening/` and `000_common/checklists/appsec-hardening/cheatsheets/`, could not be loaded as files. The individual security index and named documents were returned. The complete set of domain-specific references and taxonomies was not walked, so the requested exhaustive skill-level coverage remains incomplete.

The companion report gives source locations, static reproduction steps, hypotheses and proposed mitigations. Runtime reproduction steps are clearly identified as future tests. No source code was modified during this audit.
