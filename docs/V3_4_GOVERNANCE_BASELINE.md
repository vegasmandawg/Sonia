# SONIA v3.4 Governance Baseline

## 1. Severity Classification

| Severity | Label | Description | Response SLA | Resolution SLA |
|----------|-------|-------------|-------------|----------------|
| S1 | Critical | Service down, data loss risk, security breach | 15 min ack | 4 hours |
| S2 | High | Major feature broken, degraded for >50% users | 30 min ack | 8 hours |
| S3 | Medium | Minor feature broken, workaround exists | 4 hours | 48 hours |
| S4 | Low | Cosmetic, documentation, minor UX issues | 24 hours | 1 week |

## 2. Escalation Path

1. **On-call engineer** detects via EVA-OS supervision alerts or manual report
2. **S1/S2**: Immediate page to service owner; if no ack in SLA, escalate to project lead
3. **S3/S4**: Filed in issue tracker, triaged in next planning cycle

## 3. Sign-Off Roles

| Role | Responsibility | Required For |
|------|---------------|-------------|
| **Service Owner** | Approves changes to their service | Any service modification |
| **Release Manager** | Runs promotion gate, stamps releases | RC and GA releases |
| **Security Reviewer** | Reviews auth, redaction, path security changes | P-section changes |
| **Test Lead** | Validates test coverage meets floor | Gate G12 (test count) |

## 4. Change Control Process

### 4.1 Standard Change (P3/P4)
1. Branch from `main` or current dev branch
2. Implement with tests
3. Self-review + automated gate
4. Merge

### 4.2 Significant Change (P1/P2)
1. Branch from `main`
2. Implement with tests
3. Peer review required
4. Promotion gate must pass
5. Service owner sign-off
6. Merge

### 4.3 Emergency Change (S1)
1. Hotfix branch from latest release tag
2. Minimal fix with regression test
3. Fast-track review (1 reviewer)
4. Tag and deploy
5. Post-incident review within 48 hours

## 5. Issue Register

Active issues are tracked in the git repository. Each issue must include:

- **ID**: Sequential (e.g., `SONIA-001`)
- **Severity**: S1-S4
- **Status**: Open | In Progress | Resolved | Closed
- **Owner**: Assigned engineer
- **Description**: Root cause and impact
- **Resolution**: Fix applied and verification

### Current Issue Register

| ID | Severity | Status | Summary |
|----|----------|--------|---------|
| SONIA-001 | S4 | Resolved | Starlette/sse-starlette version mismatch (soft, non-blocking) |
| SONIA-002 | S4 | Resolved | Torch 2.8.0+cpu vs 2.10.0+cu128 environment mismatch |
| SONIA-003 | S3 | Open | Pipecat ASR/TTS/VAD backends not yet configured (stubs in place) |

## 6. Release Cadence

- **Dev builds**: Continuous on dev branches
- **Release Candidates**: When promotion gate passes (all gates green)
- **GA releases**: After RC soak test (minimum 200 operations, 0 SLO violations)
- **Hotfixes**: As needed for S1/S2 issues

## 7. Quality Gates

All releases must pass the promotion gate checklist:

1. **G1-G29**: Inherited from v3.0 floor (regression, health, breakers, DLQ, deps, manifest, chaos, backup, diagnostics, correlation, rollback, incident bundle)
2. **G30**: Test count floor (current: 565+ integration tests)
3. **G31**: Soak test pass (0 SLO violations)
4. **G32**: Clean-room parity verification
5. **G33**: Security scan (bandit + pip-audit, 0 high/critical findings)
6. **G34**: Log redaction verification (no PII in sample logs)
7. **G35**: Dependency lock integrity (SHA-256 match)

## 8. Audit Trail

All gate runs produce JSON reports stored in `S:\releases\<version>\`:
- `gate-report.json`: Per-gate pass/fail with timing
- `soak-report.json`: Latency percentiles and violation counts
- `release-manifest.json`: SHA-256 hashes of all release artifacts

## 9. Rollback Policy

- Every GA release has a corresponding rollback script
- Rollback scripts support `-DryRun` for validation
- Maximum RTO target: 60 seconds
- Rollback must be tested as part of promotion gate
