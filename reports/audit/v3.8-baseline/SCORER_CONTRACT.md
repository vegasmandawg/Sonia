# Scorer Contract -- v3.8

**Locked at:** v3.8 M0 bootstrap
**Date:** 2026-02-15
**Applies to:** All dual-pass reassessments from v3.8 onward

---

## Rubric Structure

| Parameter | Value | Rationale |
|-----------|-------|-----------|
| Sections | A through Y (25 sections) | Full-spectrum audit coverage |
| Points per section | 0--20 | Granular enough for gap detection |
| Total possible | 500 | 25 x 20 |
| Passing floor (per pass) | 390/500 (78%) | Minimum for PROMOTE |
| Section floor | 15/20 on both passes | No section may be critically weak |

---

## Section Index

| # | Section | Focus |
|---|---------|-------|
| A | Governance & Process | Risk register, DoD, retrospectives |
| B | Architecture & Design | Service boundaries, contracts |
| C | Code Quality | Static analysis, style, complexity |
| D | Configuration Mgmt | Config files, secret scanning |
| E | Deployment & Release | Release scripts, promotion gates |
| F | API Design | Schemas, versioning, contracts |
| G | Error Handling | Fallback, retry, circuit breaker |
| H | Logging & Monitoring | Structured logging, redaction |
| I | Auth & Authorization | Auth posture, rate limiting |
| J | Data Management | Migration, schema evolution |
| K | Performance | Latency budgets, SLO targets |
| L | Testing Strategy | Unit + integration coverage |
| M | Data Stores | WAL, backup, durability |
| N | Observability | Health checks, diagnostics |
| O | Operational Readiness | Runbooks, troubleshooting |
| P | Security Controls | Secret scan, input validation |
| Q | Privacy & Data | Redaction, PII handling |
| R | Dependency Mgmt | Frozen deps, lock files |
| S | CI/CD & Automation | Gate scripts, automation |
| T | Documentation Quality | Completeness, accuracy |
| U | Backup & Recovery | Backup drill, RTO |
| V | Incident Response | Severity classification, export |
| W | Operations Docs | Ops documentation suite |
| X | Release Management | Manifests, SHA-256 integrity |
| Y | Compliance & Audit | Control traceability, evidence |

---

## Scoring Rules

### What scores CAN be based on

1. **Artifact-cited evidence only** -- every deduction must reference a specific
   file, gate result, test output, or configuration that is present (or absent)
   in the codebase at the assessed commit
2. **Rubric-defined criteria** -- deductions must map to a specific section
   (A-Y) and a specific sub-criterion within that section
3. **Reproducible assessment** -- the same commit, assessed by the same rubric,
   must produce scores within +/-3 points per section across runs

### What scores CANNOT be based on

1. **Enterprise-grade expectations beyond scope** -- deductions for features
   explicitly listed in the non-goals section of V3_8_SCOPE_LOCK.md are invalid
2. **Out-of-scope tooling** -- penalizing for absence of tools (mypy, CI/CD
   platform, database replication) that are explicitly non-goals
3. **Subjective quality judgments** -- "code doesn't feel production-ready"
   without a specific artifact-cited gap
4. **Future requirements** -- "should have X for when the team grows" without
   a current rubric criterion requiring it
5. **Double-counting** -- the same gap cannot be penalized in more than one section

---

## Dual-Pass Protocol

| Parameter | Standard Scorer | Conservative Scorer |
|-----------|----------------|-------------------|
| Rubric | Identical A-Y, 0-20 | Identical A-Y, 0-20 |
| Bias | Evaluates deliverable presence | Penalizes design choices |
| Independence | Must not see other pass results | Must not see other pass results |
| Output | Section-by-section scores + rationale | Section-by-section scores + rationale |

### Acceptance

| Condition | Threshold |
|-----------|-----------|
| Standard pass | >= 390/500 (78%) |
| Conservative pass | >= 390/500 (78%) |
| Per-section minimum | >= 15/20 on BOTH passes |
| Variance | <= 50 points (10%) between passes |

### Verdict

- **PROMOTE** -- both passes >= 78%, all sections >= 15, variance <= 50
- **PROMOTE WITH EXCEPTION** -- one pass >= 78%, other >= 75%, documented gaps
- **HOLD** -- any pass < 75%, or any section < 12, or variance > 50

---

## Dispute Resolution

If a scorer deducts points for a gap that is:
1. Explicitly listed as a non-goal in V3_8_SCOPE_LOCK.md, OR
2. Not cited with a specific artifact reference, OR
3. Already counted in another section (double-counting)

Then the deduction is **invalid** and must be reversed. The dispute must be
documented in the scorecard with the original score, disputed score, and
resolution rationale.

---

## Contract Immutability

This contract is locked at v3.8 M0 bootstrap. It CANNOT be modified during
the v3.8 development cycle. Any changes require:
1. A new version tag (v3.9+)
2. Explicit documentation of what changed and why
3. Re-baselining of all scores under the new contract

---

*Locked by: v3.8 M0 bootstrap commit on v3.8-dev*
