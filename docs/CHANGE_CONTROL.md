# Change Control Policy

**Effective**: v2.5.0 GA (2026-02-09)
**Baseline Contract**: `S:\config\baseline-contract.json`

---

## Core Rule

> Any post-GA change must pass the 12-gate promotion path before merge to `main`.

No exceptions for severity, size, or urgency. The promotion gate is the single source of truth for merge readiness.

---

## Change Categories

| Category | Examples | Branch | Gate Required |
|----------|----------|--------|---------------|
| Feature | New endpoint, new capability, new stage | `next` or `master` | Full 12-gate |
| Bug fix | Logic error, crash fix, edge case | `master` or `hotfix/*` | Full 12-gate |
| Dependency update | Package bump, security patch | `master` | Full 12-gate |
| Config change | Port change, timeout tuning, policy update | `master` | Full 12-gate |
| Documentation | Operational docs, runbooks | `master` | 12-gate if affects runtime behavior; direct commit if prose-only |

---

## Change Lifecycle

### 1. Propose
- Describe what contract element is affected (code, deps, model, config, policy).
- Reference baseline contract version.

### 2. Implement
- Work on appropriate branch (see Branch Policy).
- Include tests for any behavioral change.

### 3. Validate
- Run `promotion-gate-v2.ps1` with all services healthy.
- All 12 gates must pass (Gate 4 DLQ is advisory).
- Save promotion gate output as evidence.

### 4. Promote
- Merge to `main` with release tag.
- Update `baseline-contract.json` with new commit hash and any changed checksums.
- Archive promotion evidence in `S:\releases\<version>\`.

### 5. Verify
- Run post-merge health check.
- Verify baseline contract checksums still hold.

---

## Rollback Policy

If a promoted change causes regression:
1. Revert to previous known-good tag using `rollback-to-stage5.ps1` or equivalent.
2. Create incident bundle: `export-incident-bundle.ps1`.
3. Investigate root cause.
4. Fix forward through the standard change lifecycle (do not patch `main` directly).

---

## Evidence Requirements

Every promotion to `main` must produce:
- Promotion gate output (12 gates)
- Test report (pass count, 0 failures)
- Soak report (if behavioral change)
- Updated baseline contract (if any checksums change)

All evidence is archived under `S:\releases\<version>\`.

---

## Steady-State Operating Cadence

| Frequency | Activity | Script/Tool |
|-----------|----------|-------------|
| Daily | Health snapshot + error budget check + breaker anomaly scan | `cadence-daily.ps1` |
| Weekly | Chaos mini-suite + restore dry-run + dependency CVE scan | `cadence-weekly.ps1` |
| Monthly | Full recovery certification + release drill + evidence archival | `cadence-monthly.ps1` |
| Quarterly | Baseline recertification from clean-room rebuild | Manual: clean-room venv + full regression |
