# v3.4 Scope Lock

**Status**: M0 SCAFFOLD -- version bumped, gate inherited, epics TBD
**Branch**: `v3.4-dev`
**Base**: v3.3.0 GA (`5a65f45` on main)
**Contract**: SONIA_CONTRACT pinned at `v3.0.0` (no breaking changes)

---

## 1. Inherited Floor

v3.4 inherits the full v3.3 test floor (157 tests across G18-G29).

| Gate | Suite | Tests | Origin |
|------|-------|-------|--------|
| G18 | Voice latency budget | 4 | v3.2 |
| G19 | Barge-in replay determinism | 20 | v3.2 |
| G20 | Perception dedupe correctness | 15 | v3.2 |
| G21 | Confirmation storm integrity | 8 | v3.2 |
| G22 | Memory proposal governance | 16 | v3.2 |
| G23 | Memory replay integrity | 14 | v3.2 |
| G24 | Ledger edit governance | 16 | v3.3 Epic A |
| G25 | Redaction + provenance slicing | 14 | v3.3 Epic A |
| G26 | Restore integrity | 13 | v3.3 Epic B |
| G27 | Incident triage automation | 13 | v3.3 Epic B |
| G28 | Privacy boundary enforcement | 14 | v3.3 Epic C |
| G29 | Zero-frame + confirmation hardening | 10 | v3.3 Epic C |

**Inherited floor total: 157 tests**

---

## 2. Planned Epics (TBD)

Candidate themes (to be refined and locked):

| Epic | Working Name | Candidate Gates | Theme |
|------|-------------|-----------------|-------|
| A | Operator Recovery Ergonomics | G30/G31 | Reliability: operator experience under stress, drill UX, alert fatigue reduction |
| B | Incident Root-Cause Pathways | G32/G33 | Observability: faster root-cause analysis, structured incident timelines, correlation enrichment |
| C | Bounded Capability Extension | G34/G35 | Capability: no contract break, heavily gateable, incremental feature |

**Epics will be formally defined and locked in a subsequent M0 LOCK commit.**

---

## 3. Non-Goals (hard exclusions)

- **No contract breaking changes**: SONIA_CONTRACT stays at `v3.0.0`
- **No v3.3 module modifications**: bugfixes go to `release/v3.3.x` only
- **No new external dependencies** without frozen/mirrored reproduction
- **No changes to core boot sequence**
- **No unbounded UI scope**
- **No data migrations without rollback**
- **No toolchain upgrades**

---

## 4. Contract Policy

`SONIA_CONTRACT` remains pinned at `v3.0.0`. Any contract bump requires
a separate scope item with migration path documented before approval.

---

## 5. Promotion Criteria (binary)

- [ ] **Inherited floor**: G18-G29 all PASS (157/157)
- [ ] **Delta gates**: G30+ all PASS (TBD)
- [ ] **Combined floor**: >= 157 + delta tests, 0 failures
- [ ] **Cross-epic soak**: all invariants ZERO
- [ ] **Clean-room parity**: all gates PASS from tagged RC
- [ ] **Release bundle**: all artifacts present, SHA-256 verified
- [ ] **No SONIA_CONTRACT bump** unless separately approved
- [ ] **No SLO violations**

---

## Changelog

| Date | Change |
|------|--------|
| 2026-02-15 | M0 scaffold: v3.4-dev created, version bumped to 3.4.0-dev, gate-v34.py scaffolded with 157-test inherited floor |
