# Definition of Done

**Version:** 1.0.0
**Last Updated:** 2026-02-15
**Applies To:** All operational changes (code, config, deployment, runbook updates)

## Overview

A change is considered **DONE** when all applicable items in this checklist are complete. This ensures quality, safety, and operational readiness before promotion to main or production.

---

## Code

- [ ] **Tests pass**: All integration tests green (pytest exit code 0)
- [ ] **No regressions**: Smoke scripts for all prior stages execute without error
- [ ] **Coverage maintained**: New code has corresponding test coverage
- [ ] **Reviewed**: Code reviewed by at least one other person (or self-review documented for solo work)
- [ ] **Linting clean**: No new linter warnings introduced (if linter in use)
- [ ] **Dependencies locked**: If new deps added, requirements-frozen.txt and dependency-lock.json updated

---

## Configuration

- [ ] **Documented**: Config changes documented in relevant docs (SONIA_CONFIG.md, ports.yaml, .env.example)
- [ ] **Validated**: Config schema validated (if schema enforcement exists)
- [ ] **Backward compatible**: Existing configs still valid, or migration path documented
- [ ] **Secrets safe**: No secrets committed; .env patterns gitignored
- [ ] **Default safe**: Default values are safe-by-default (e.g., privacy=hard_gate, not permissive)

---

## Operations

- [ ] **Runbook updated**: RUNBOOK.md reflects new failure modes, recovery procedures, or operational procedures
- [ ] **Backup verified**: If change affects state (SQLite, DLQ, etc.), backup/restore tested
- [ ] **Gates pass**: Promotion gate script (gate-vXX.py or promotion-gate-vXX.ps1) passes all gates
- [ ] **Rollback tested**: Rollback script dry-run succeeds; rollback path documented
- [ ] **Health checks**: Service /healthz endpoints reflect new components (if applicable)
- [ ] **Observability**: Logs, metrics, or correlation IDs capture new flows

---

## Documentation

- [ ] **DEPLOYMENT.md updated**: If deployment steps change (new service, new port, new env var)
- [ ] **RUNBOOK.md updated**: If new failure modes, alarms, or recovery procedures introduced
- [ ] **SECURITY.md updated**: If security posture changes (new secrets, new attack surface, new mitigations)
- [ ] **Changelog updated**: High-level summary in CHANGELOG.md (or stage-specific doc)
- [ ] **ADR written**: If architectural decision made, ADR in docs/adr/ (if ADR practice adopted)

---

## Evidence

- [ ] **Audit binder updated**: Test results, soak reports, gate reports committed to audit/ or releases/
- [ ] **Gate report committed**: promotion-gate JSON report checked into releases/vX.Y.Z/
- [ ] **Release manifest**: If release, release-manifest.json with SHA-256 hashes created
- [ ] **Tag applied**: If release, git tag vX.Y.Z applied and pushed

---

## Known Limitations / Non-Goals

This Definition of Done does **not** require:

- **External code review** for solo maintainer projects (self-review documented is sufficient)
- **Automated CI/CD** (SONIA uses manual promotion gates, not CI/CD pipelines)
- **Performance benchmarks** for every change (only for performance-sensitive milestones)
- **User acceptance testing** (SONIA is developer-operated; smoke/soak scripts are acceptance tests)
- **Security audit** for every change (quarterly security scan is sufficient; see retrospective-cadence.md)

---

## Compliance Check

Before marking a change as DONE, run:

```powershell
# Smoke test for regressions
.\scripts\smoke_stage4_multimodal.ps1

# Promotion gate (use latest version)
python scripts\release\gate-v30.py

# Verify tests
pytest tests\integration\ -v
```

If all pass, the change is DONE and eligible for merge/promotion.
