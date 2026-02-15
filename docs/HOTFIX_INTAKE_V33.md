# Hotfix Intake Template: release/v3.3.x

**Branch**: `release/v3.3.x`
**Merge bar**: Binary (all criteria must pass)
**Policy**: Hotfix and security patches only. No feature additions.

---

## Intake Template

Copy this template for each hotfix PR against `release/v3.3.x`:

```markdown
## Hotfix: [SHORT_TITLE]

### Severity
- [ ] Critical (service down, data loss, security vulnerability)
- [ ] High (degraded operation, workaround exists)
- [ ] Medium (edge case, no workaround but low frequency)

### User Impact
[Describe who is affected and how. Include frequency if known.]

### Reproduction Steps
1. [Step 1]
2. [Step 2]
3. [Expected vs actual behavior]

### Affected Gate(s)
- [ ] G18 (voice latency)
- [ ] G19 (barge-in replay)
- [ ] G20 (perception dedupe)
- [ ] G21 (confirmation storm)
- [ ] G22 (memory proposal)
- [ ] G23 (memory replay)
- [ ] G24 (ledger edit)
- [ ] G25 (redaction/provenance)
- [ ] G26 (restore integrity)
- [ ] G27 (incident triage)
- [ ] G28 (privacy boundary)
- [ ] G29 (zero-frame/confirmation)
- [ ] None (new edge case not covered by existing gates)

### Minimal Patch Scope
[List only the files that must change. Smaller is better.]

| File | Change Description |
|------|-------------------|
| `path/to/file.py` | [What changes and why] |

### Required Tests
[List new or modified tests that validate this fix.]

| Test File | Test Name | Validates |
|-----------|-----------|-----------|
| `tests/...` | `test_xxx` | [What invariant this proves] |

### Required Evidence Artifacts
- [ ] Patch test output (all pass)
- [ ] Impacted floor gate(s) re-run (all pass)
- [ ] No contract break verified (SONIA_CONTRACT == v3.0.0)
- [ ] Hash-verified patch bundle

### Cherry-Pick Plan
- [ ] Cherry-pick to `main` (if applicable)
- [ ] Cherry-pick to `v3.4-dev` (if applicable)
- [ ] N/A (release-branch-only fix)

Cherry-pick commit(s): `(cherry-picked from <sha>)`
```

---

## Merge Bar (Binary -- ALL must be true)

| # | Criterion | Check |
|---|-----------|-------|
| 1 | Patch tests pass | `python -m pytest <patch_test_files> -v` |
| 2 | Impacted floor gates pass | `python scripts/release/gate-v33.py` (affected gates) |
| 3 | No contract break | `SONIA_CONTRACT == v3.0.0` in `services/shared/version.py` |
| 4 | Hash-verified patch bundle | `python scripts/release/verify-hashes-v33.py` |
| 5 | Minimal scope | No files changed beyond those listed in patch scope |
| 6 | Review approval | At least one reviewer sign-off |

**If any criterion fails, the hotfix is BLOCKED until resolved.**

---

## Patch Tag Convention

After merge to `release/v3.3.x`:
```bash
git tag v3.3.1  # increment for each patch
git push origin v3.3.1
```

Update `S:\releases\v3.3.1\` with patch manifest and evidence.
