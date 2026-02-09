# Branch Policy

**Effective**: v2.5.0 GA (2026-02-09)

---

## Branch Roles

| Branch | Purpose | Protection | Merge Source |
|--------|---------|------------|-------------|
| `main` | Protected release branch. Release-only commits. | Protected: no direct push, squash merge only, 12-gate promotion required | `master` (after promotion gate) |
| `master` | Active development integration branch | Semi-protected: no force-push | Feature branches, hotfix branches |
| `hotfix/*` | Emergency patches only | Requires baseline contract reference | Cherry-pick from targeted fix |
| `next` (or `v2.6-dev`) | Next version feature development | Standard | Feature branches |

---

## Rules

### main (Release-Only)
- No direct commits. All changes arrive via merge from `master` after passing the 12-gate promotion checklist (`promotion-gate-v2.ps1`).
- Every merge to `main` must be tagged with a release version (e.g., `v2.5.0`, `v2.5.1`).
- The HEAD of `main` always corresponds to a fully promoted, evidence-backed release.

### master (Integration)
- Active development happens here or in feature branches merged to `master`.
- No force-push. All commits are append-only.
- Stage milestones are tagged here (e.g., `v2.5.0-stage5`, `v2.5.0-rc1`).

### hotfix/* (Emergency Only)
- Created from the `main` branch tag that needs patching.
- Naming: `hotfix/v2.5.1-<description>` (e.g., `hotfix/v2.5.1-breaker-deadlock`).
- Must reference the baseline contract (`baseline-contract.json`) and describe which contract element is violated.
- After fix: run the 12-gate promotion gate, merge to both `main` (tagged) and `master`.

### next / v2.6-dev (Feature Development)
- Long-lived branch for v2.6 scope.
- Feature branches merge here first for integration testing.
- Periodically rebased onto `master` to pick up hotfixes.
- Promoted to `master` only when all v2.6 acceptance gates pass.

---

## Change Control Rule

**Any post-GA change must pass the 12-gate promotion path before merge to `main`.**

This applies to:
- Bug fixes (even single-line)
- Dependency updates
- Configuration changes
- Documentation corrections that affect operational behavior

The only exception is this policy document itself, which may be updated on `master` without promotion (it is not runtime code).

---

## Promotion Flow

```
feature-branch --> master --> [12-gate promotion] --> main (tagged)
hotfix/*       --> [12-gate promotion] --> main (tagged) + master
```

### 12-Gate Checklist (promotion-gate-v2.ps1)

1. Full regression (0 failed)
2. Health supervisor (healthy)
3. Circuit breakers (all closed)
4. Dead letter queue (0 unresolved) [non-blocking]
5. Dependency lock integrity
6. Frozen requirements manifest
7. Chaos suite passes
8. Backup/restore integrity verified
9. Diagnostics snapshot functional
10. Correlation ID in action responses
11. Rollback script exists
12. Incident bundle export script exists
