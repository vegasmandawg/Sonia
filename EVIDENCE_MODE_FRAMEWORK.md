# Evidence Mode Framework - Phase 3 Production Hardening

**Effective Date**: 2026-02-09  
**Mode**: Evidence (all outcomes auditable, zero simulation)  
**Contract**: BOOT_CONTRACT.md v1.0.0 (immutable unless version-bumped)

---

## Core Principles

### 1. No Simulated Pass Documents
- ✗ Cannot claim success without real execution
- ✗ Cannot use placeholder metrics or estimates
- ✓ Must have actual JSON evidence from real runs
- ✓ Must have measurable, timestamped results

### 2. Hard Gates (No Partial Passes)
- ✗ 9/10 cycles is not acceptable (Gate 1)
- ✗ 0.6% error rate is not acceptable (Gate 2)
- ✗ One policy test failure fails entire Gate 3
- ✓ All-or-nothing: 10/10, <0.5%, all adversarial tests pass
- ✓ If gate fails: stop, fix, restart from gate beginning

### 3. No Gate Advancement with Unresolved Blocker
- ✗ Cannot proceed to Gate 2 if Gate 1 has outstanding issue
- ✗ Cannot proceed to release if any gate incomplete
- ✓ Must document blocker, fix, rerun, verify before advancing
- ✓ Blocker resolution must be part of evidence trail

### 4. Contract Immutability
- ✗ BOOT_CONTRACT.md cannot drift outside versioning
- ✗ Port mappings, endpoint specs, health timeout cannot change
- ✓ If contract needs change: explicit version bump required
- ✓ All evidence must reference current contract version

### 5. Artifact Hash Set & Sign-Off Trail
- ✗ Cannot release without SHA256 manifest
- ✗ Cannot GA without sign-off in RELEASE_CHECKLIST.md
- ✓ Every artifact must be hashed
- ✓ Hash manifest must be signed (if crypto available)
- ✓ Release requires explicit director/VP sign-off

---

## Evidence Artifacts Structure

```
S:\artifacts\phase3\
├── evidence\              # Raw execution evidence
│   ├── gate1-*.log
│   ├── gate2-metrics-minute-*.json
│   ├── gate3-auth-tests-*.json
│   ├── gate4-recovery-*.json
│   ├── gate5-run1-*.json
│   └── PREREQUISITES_COMPLETED_*.txt
│
├── gate-results\          # Gate summary JSON files
│   ├── gate1-summary-*.json
│   ├── gate2-summary-*.json
│   ├── gate3-summary-*.json
│   ├── gate4-summary-*.json
│   ├── gate5-summary-*.json
│   └── release-bundle-*.json
│
├── manifests\             # SHA256 manifests
│   ├── gate1-manifest-*.sha256
│   ├── gate2-manifest-*.sha256
│   ├── gate3-manifest-*.sha256
│   ├── gate4-manifest-*.sha256
│   ├── gate5-manifest-*.sha256
│   └── RELEASE_CANDIDATE_1_MANIFEST.sha256
│
├── PHASE_3_EXECUTION_LOG.md      # Daily status log
└── GATE_EXECUTION_PREREQUISITES.md
```

---

## Gate Execution Workflow

### Gate Execution Sequence
```
[Prerequisites Validation]
        ↓
   [Gate 1 Run]
        ↓
  [Gate 1 Pass?]
   /         \
  NO         YES
  |           ↓
  |      [Gate 2 Run]
  |           ↓
  |      [Gate 2 Pass?]
  |       /         \
  |      NO         YES
  |      |           ↓
  |      |      [Gate 3 Run]
  |      |           ↓
  |      |      [Gate 3 Pass?]
  |      |       /         \
  |      |      NO         YES
  |      |      |           ↓
  |      |      |      [Gate 4 Run]
  |      |      |           ↓
  |      |      |      [Gate 4 Pass?]
  |      |      |       /         \
  |      |      |      NO         YES
  |      |      |      |           ↓
  |      |      |      |      [Gate 5 Run]
  |      |      |      |           ↓
  |      |      |      |      [Gate 5 Pass?]
  |      |      |      |       /         \
  |      |      |      |      NO         YES
  |      |      |      |      |           ↓
  |      |      |      |      |    [Release Ceremony]
  |      |      |      |      |           ↓
  |      |      |      |      |    [GA Declaration]
  |      |      |      |      |
  └──────┴──────┴──────┴──────┤
                    [STOP & FIX BLOCKER]
```

### For Each Gate Failure
```
[Gate Execution]
        ↓
   [Results]
        ↓
  [Pass/Fail?]
        ↓
      FAIL
        ↓
  [Document Blocker]
        ↓
  [Investigate Root Cause]
        ↓
  [Fix Root Cause]
        ↓
  [Document Fix in Evidence]
        ↓
  [Rerun Gate from Beginning]
        ↓
   [Verify Pass]
        ↓
   [Continue to Next Gate]
```

---

## Daily Execution Cadence

### Each Day
1. **Morning**: Review PHASE_3_EXECUTION_LOG.md for status
2. **Execute**: Run scheduled gate(s) with strict hard block enforcement
3. **Document**: Capture all results in JSON summary + SHA256 manifest
4. **Evening**: Update PHASE_3_EXECUTION_LOG.md with pass/fail + blocker (if any)

### Upon Gate Completion
1. **Generate JSON**: `gate-N-summary-TIMESTAMP.json` with all metrics
2. **Create Manifest**: `gate-N-manifest-TIMESTAMP.sha256` with all artifact hashes
3. **Sign**: If cryptographic signing available, sign manifest
4. **Update Log**: PHASE_3_EXECUTION_LOG.md with gate status + evidence links

### Upon Any Failure
1. **STOP immediately** - Do not proceed to next gate
2. **Document**: Blocker description, root cause investigation
3. **Fix**: Code change, config update, or environment fix
4. **Document**: Fix details in evidence
5. **Rerun**: Full gate from cycle 1 (no partial credit)
6. **Verify**: Confirm root cause resolved before advancing

### Weekly Boundary (If Needed)
- If gate fails twice: pause rollout, convene remediation sprint
- Document decision timeline
- Add remediation artifacts to evidence
- Only retry after documented root cause fix

---

## Evidence Requirements by Gate

### Gate 1: 10 Consecutive Cycles
**JSON Summary Must Include**:
```json
{
  "gate": 1,
  "timestamp": "2026-02-DD HH:MM:SS",
  "status": "PASSED or FAILED",
  "cycles_completed": 10,
  "cycles_passed": 10,
  "cycles_failed": 0,
  "zombie_pids_detected": 0,
  "health_checks_total": 2160,
  "health_checks_passed": 2160,
  "health_checks_failed": 0,
  "services": {
    "api-gateway": { "status": "up", "pid": 1234, "healthz": 200 },
    "model-router": { "status": "up", "pid": 1235, "healthz": 200 },
    "memory-engine": { "status": "up", "pid": 1236, "healthz": 200 },
    "pipecat": { "status": "up", "pid": 1237, "healthz": 200 },
    "openclaw": { "status": "up", "pid": 1238, "healthz": 200 },
    "eva-os": { "status": "up", "pid": 1239, "healthz": 200 }
  }
}
```

### Gate 2: 48-Hour Soak
**JSON Summary Must Include**:
```json
{
  "gate": 2,
  "duration_hours": 48,
  "timestamp_start": "2026-02-DD HH:MM:SS",
  "timestamp_end": "2026-02-DD HH:MM:SS",
  "error_rate_percent": 0.25,
  "error_rate_threshold": 0.5,
  "errors_total": 120,
  "requests_total": 48000,
  "memory_growth_percent": 2.5,
  "latency_p95_ms": 245,
  "latency_p99_ms": 512,
  "service_restarts": 0,
  "deadlocks_detected": 0,
  "pass_fail": "PASSED"
}
```

### Gate 3: Security Hardening
**JSON Summary Must Include**:
```json
{
  "gate": 3,
  "auth_tests_total": 10,
  "auth_tests_passed": 10,
  "policy_tests_total": 8,
  "policy_tests_passed": 8,
  "sandbox_adversarial_tests_total": 12,
  "sandbox_adversarial_tests_passed": 12,
  "secrets_found": 0,
  "config_validation": "PASS",
  "pass_fail": "PASSED"
}
```

### Gate 4: Durability & Recovery
**JSON Summary Must Include**:
```json
{
  "gate": 4,
  "backup_timestamp": "2026-02-DD HH:MM:SS",
  "restore_timestamp": "2026-02-DD HH:MM:SS",
  "rpo_minutes": 3,
  "rto_minutes": 8,
  "data_integrity": "PASS",
  "wal_consistency": "PASS",
  "services_after_restore": 6,
  "services_healthy_after_restore": 6,
  "pass_fail": "PASSED"
}
```

### Gate 5: Determinism
**JSON Summary Must Include**:
```json
{
  "gate": 5,
  "run1_timestamp": "2026-02-DD HH:MM:SS",
  "run1_pass_count": 152,
  "run1_fail_count": 3,
  "run2_timestamp": "2026-02-DD HH:MM:SS",
  "run2_pass_count": 152,
  "run2_fail_count": 3,
  "deterministic": true,
  "pass_count_match": true,
  "fail_count_match": true,
  "failed_tests_match": true,
  "pass_fail": "PASSED"
}
```

---

## SHA256 Manifest Format

```
# Phase 3 Gate N Evidence Manifest
# Generated: 2026-02-DD HH:MM:SS
# Gate Status: PASSED

gate-N-summary-TIMESTAMP.json          SHA256HASHHERE
gate-N-execution-log-TIMESTAMP.txt     SHA256HASHHERE
gate-N-manifest-TIMESTAMP.sha256       SHA256HASHHERE
[additional-artifact-file]              SHA256HASHHERE

# Signature (if crypto available)
-----BEGIN SIGNED MESSAGE-----
[Base64 signature content]
-----END SIGNED MESSAGE-----
```

---

## Release Sign-Off Matrix

**Location**: `S:\RELEASE_CHECKLIST.md`

```markdown
# Release Candidate 1 Sign-Off

| Gate | Objective | Result | Evidence | Approver | Date |
|------|-----------|--------|----------|----------|------|
| 1 | 10/10 cycles, zero zombies, 2160/2160 checks | ✓ PASS | gate1-summary-*.json | [Name] | [Date] |
| 2 | 48h soak, <0.5% error, no deadlock | ✓ PASS | gate2-summary-*.json | [Name] | [Date] |
| 3 | Auth, policy, sandbox, secrets hardening | ✓ PASS | gate3-summary-*.json | [Name] | [Date] |
| 4 | Backup/restore, RPO/RTO, data integrity | ✓ PASS | gate4-summary-*.json | [Name] | [Date] |
| 5 | Determinism Run1 === Run2 | ✓ PASS | gate5-summary-*.json | [Name] | [Date] |

## Release Approval

**Release Candidate 1 Approved for GA**

- Approved by: [Director/VP Name]
- Title: [Director/VP Title]
- Date: [YYYY-MM-DD HH:MM:SS]
- Signature: [Cryptographic or digital signature]

**Artifact Bundle Hash**:
```
RELEASE_CANDIDATE_1_MANIFEST.sha256
```

**All evidence is immutable and auditable.**
```

---

## Non-Negotiables (Absolute Rules)

1. ✗ No simulated pass documents
   - ✓ All evidence must be from real execution
   - ✓ All metrics must be timestamped and measured

2. ✗ No gate advancement with unresolved blocker
   - ✓ Must document, fix, and rerun from gate start
   - ✓ No workarounds or partial passes

3. ✗ No contract drift outside explicit versioning
   - ✓ BOOT_CONTRACT.md locked at v1.0.0
   - ✓ Any changes require version bump + documented approval

4. ✗ No release without artifact hash set and sign-off trail
   - ✓ All artifacts must be SHA256 hashed
   - ✓ Release checklist must be complete and signed
   - ✓ GA declaration must be in RELEASE_CANDIDATE_1_APPROVED.txt

5. ✗ No gate advancement if prerequisites not satisfied
   - ✓ Python must be installed and in PATH
   - ✓ All dependencies must be installed
   - ✓ Preflight validator must pass
   - ✓ Single service startup must succeed

---

## Operational Status

**Current Phase**: Prerequisite validation  
**Blocker**: Python not in system PATH  
**Mode**: Evidence (all outcomes auditable)  
**Contract**: Locked (BOOT_CONTRACT.md v1.0.0)  
**Next Step**: Install Python 3.10+, complete prerequisites, begin Gate 1

**Timeline**: 7-10 days estimated (Gates 1-5 + release)

---

## Appendix: Artifact Checklist

### Before Gate 1
- [ ] PHASE_3_EXECUTION_LOG.md created
- [ ] GATE_EXECUTION_PREREQUISITES.md completed
- [ ] Evidence directories created
- [ ] Manifest template in place
- [ ] All prerequisites satisfied and documented

### After Each Gate
- [ ] JSON summary generated with all metrics
- [ ] SHA256 manifest created with all artifact hashes
- [ ] Execution log updated with status
- [ ] Evidence links documented

### Before Release
- [ ] All 5 gates have JSON summaries
- [ ] All 5 gates have SHA256 manifests
- [ ] All 5 gates are marked PASSED
- [ ] RELEASE_CHECKLIST.md fully populated
- [ ] Release sign-off obtained
- [ ] RELEASE_CANDIDATE_1_APPROVED.txt created

---

**Framework Established**: 2026-02-09  
**Status**: Ready for execution  
**Mode**: Evidence (zero simulation, 100% audit trail)
