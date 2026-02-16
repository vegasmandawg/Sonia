# v4.0 Scope Lock

**Branch:** `v4.0-dev`
**Base:** `main` at v3.9.0 GA (eef3818)
**Created:** 2026-02-16
**Locked:** 2026-02-16

---

## Program Intent

v4.0 adds capability depth while preserving audit determinism. The objective is
not score inflation; it is zero-regression with higher evidence depth.

### Success Targets

| Metric | Target |
|--------|--------|
| Gates | 37/37 PASS (placeholders replaced with real checks) |
| Unit test floor | >= 613 (minimum +90 from 523; target +105 = 628) |
| Dual-pass floor | >= 490/500 on both scorers |
| Inter-pass gap | <= 6 points |
| Deterministic failures | Zero unresolved in final matrix |

---

## Inherited Floor

All 33 gates from v3.9.0 are inherited as non-negotiable baseline:
- 24 v3.7 inherited gates
- 4 v3.8 delta gates
- 4 v3.9 delta gates (coverage-completeness, data-durability, deduction-sweep, test-strategy)
- 1 unit test floor (523 tests)

### Score Floor

| Scorer | Floor |
|--------|-------|
| Standard | 496/500 (99.2%) |
| Conservative | 496/500 (99.2%) |

No section may regress below its v3.9.0 score.

---

## Epics (LOCKED)

### Epic 1 -- Session & Memory Governance Hardening

- **Branch:** `v4.0-e1-session-memory`
- **Section impact:** H, J, Q, W, A
- **Primary outcomes:** deterministic session isolation, cross-session memory leak prevention, policy-driven memory mutation controls, stronger redaction lineage
- **Gate:** `v40-epic1-gate.py` (10 real checks)
- **Test budget:** minimum 30, target 36

Gate check themes:
1. Session namespace isolation
2. Persona memory silo boundaries
3. Mutation authorization paths
4. Redaction replay integrity
5. Memory version conflict handling
6. Retention policy enforcement
7. Import/export safety invariants
8. Audit trail completeness
9. Incident snapshot memory fields
10. Deterministic rerun parity

### Epic 2 -- Recovery, Incident Lineage, Determinism

- **Branch:** `v4.0-e2-recovery-lineage`
- **Section impact:** O, N, V, M, T
- **Primary outcomes:** restore path integrity, DLQ replay determinism, incident lineage completeness, retry/fallback reproducibility
- **Gate:** `v40-epic2-gate.py` (10 real checks)
- **Test budget:** minimum 30, target 34

Gate check themes:
1. Restore preconditions
2. Post-restore verification
3. DLQ dry-run/real-run divergence controls
4. Breaker state transitions deterministic
5. Retry taxonomy completeness
6. Fallback contract consistency
7. Incident bundle artifact completeness
8. Correlation lineage continuity
9. Rollback script readiness
10. Reproducibility hash stability

### Epic 3 -- Runtime QoS, Contract Fidelity, Release Discipline

- **Branch:** `v4.0-e3-runtime-qos`
- **Section impact:** K, L, S, C, D
- **Primary outcomes:** budget enforcement under load, contract conformance, coverage/test strategy enforcement, release evidence completeness
- **Gate:** `v40-epic3-gate.py` (10 real checks)
- **Test budget:** minimum 30, target 35

Gate check themes:
1. Latency budget invariants
2. Output token budget invariants
3. Sustained-load profile thresholds
4. Contract field completeness
5. Trace propagation continuity
6. Config schema strict validation
7. Code quality policy enforcement
8. Automation coverage proof
9. Test-strategy completeness
10. Release package integrity hooks

---

## Non-Goals

Inherited from v3.9.0:
- CI/CD platform integration
- Database replication/PITR
- Enterprise SSO/RBAC
- Load testing at scale
- GDPR right-to-deletion
- mypy/pylint/black in CI

---

## Test Budgets

| Epic | Minimum Tests | Target | Floor Enforced |
|------|--------------|--------|----------------|
| E1: Session & Memory Governance | 30 | 36 | Yes |
| E2: Recovery, Incident Lineage | 30 | 34 | Yes |
| E3: Runtime QoS, Contract Fidelity | 30 | 35 | Yes |
| Evidence Integrity | 10 | 15 | Yes |
| **Inherited** | **523** | **523** | **Yes** |
| **Total minimum new** | **100** | **120** | -- |

No feature merge is permitted without gate ownership and test targets.

---

## Promotion Criteria

1. All inherited gates (33) remain green
2. All delta gates pass (3 epic + 1 evidence integrity)
3. Standard >= 490/500
4. Conservative >= 490/500
5. No section below 15
6. Inter-pass gap <= 6
7. Release bundle with SHA-256 manifest
8. Per-epic test budget met (>= minimum)
9. Per-pass floor mandatory (both scorers must meet threshold)
10. Zero unresolved deterministic failures

---

## Gate Architecture (schema v7.0)

| Class | Count | Description |
|-------|-------|-------------|
| A | 32 + 1 test floor | Inherited baseline (fail-fast, always_retry, backoff jitter) |
| B | 3 | Epic delta gates (per-epic ownership, 10 checks each) |
| C | 1 | Cross-cutting (evidence integrity, non-bypassable) |

Gate runner: `scripts/release/gate-v40.py`

---

## Branch and Merge Choreography

1. `v4.0-e1-session-memory` from `v4.0-dev`
2. `v4.0-e2-recovery-lineage` from updated `v4.0-dev` after E1 merge
3. `v4.0-e3-runtime-qos` from updated `v4.0-dev` after E2 merge
4. Merge each with `--no-ff` and run full matrix after each merge
5. No parallel long-lived divergence unless explicit integration sync points

---

## Machine-Checkable Contracts

- `docs/governance/V4_0_EPIC_MAP.json` -- epic definitions, test budgets, rules
- `docs/governance/V4_0_PROMOTION_CRITERIA.json` -- promotion criteria with thresholds
- `docs/governance/V4_0_NON_GOALS.json` -- inherited non-goals with review policy
