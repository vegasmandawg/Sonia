# Branch & Tag Protection Policy

**Effective:** v2.9.1 GA (2026-02-13)

## Protected Tags

| Tag | Protection | Reason |
|-----|-----------|--------|
| `v2.9.1` | No force-update, no delete | GA release tag |
| `v2.9.1-rc1` | No force-update, no delete | RC reference for audit trail |
| `v2.9.0` | No force-update, no delete | Prior GA release |
| `v2.8.0` | No force-update, no delete | Prior GA release |
| `v2.5.0*` | No force-update, no delete | Stage milestones |

## Protected Branches

| Branch | Protection | Reason |
|--------|-----------|--------|
| `v2.9.1-runtime-hardening` | No force push, no rebase | GA release branch |
| `fix/sonia-system-audit-20260209` | No force push | v2.9.0 base branch |

## Enforcement

### Local Git Hook

A `pre-push` hook is installed at `S:/.git/hooks/pre-push` that:
1. Blocks force-push (`--force`, `--force-with-lease`) to protected branches
2. Blocks tag deletion for protected tags

### Manual Verification

Before any destructive git operation:
```bash
# Verify tag integrity
git tag -v v2.9.1 2>/dev/null || git log --oneline -1 v2.9.1

# Verify branch HEAD hasn't moved
git log --oneline -1 v2.9.1-runtime-hardening
# Expected: bb4ff78b chore(release): promote rc1 to v2.9.1 GA metadata
```

## CI / Remote Policy (v2.9.2+)

Local git hooks are necessary but not sufficient — they only apply to the
machine where they're installed. The following CI conditions must be
enforced at the remote/CI level to guarantee protection across all
contributors and agents.

### Required CI Conditions

| Condition | Purpose |
|-----------|---------|
| Blocking gate must pass before merge to main | `pytest -m "not legacy_v26_v28 and not infra_flaky"` = 0 failures |
| Legacy lane must run (non-blocking) | `pytest -m "legacy_v26_v28 or infra_flaky"` — results reported but don't block |
| No direct push to `main` | All changes via PR or verified dev branch merge |
| Tag creation requires passing gate | No GA tag without green gate + artifacts |
| Force-push blocked on release branches | `v*-runtime-hardening`, `fix/sonia-*` |

### GitHub Actions / CI Template

```yaml
# .github/workflows/gate.yml (conceptual — adapt to actual CI)
name: Promotion Gate
on:
  push:
    branches: [main, 'v*-dev']
  pull_request:
    branches: [main]

jobs:
  blocking-gate:
    runs-on: self-hosted
    steps:
      - uses: actions/checkout@v4
      - run: python -m pytest tests/integration/ -m "not legacy_v26_v28 and not infra_flaky" -q
        env:
          SONIA_ROOT: S:\

  legacy-lane:
    runs-on: self-hosted
    continue-on-error: true  # non-blocking
    steps:
      - uses: actions/checkout@v4
      - run: python -m pytest tests/integration/ -m "legacy_v26_v28 or infra_flaky" -q
        env:
          SONIA_ROOT: S:\
```

### Branch Protection Rules (GitHub Settings)

- **main**: Require status checks (blocking-gate), require PR, no force push
- **v*-dev**: No protection (working branches)
- **Tags v***: Require `blocking-gate` pass, no delete

### Marker Lifecycle

When a legacy/flaky issue is resolved:
1. Remove the marker (`legacy_v26_v28` or `infra_flaky`) from the test
2. The test moves into the blocking lane automatically
3. Verify the blocking gate still passes with the newly-unblocked test
4. Close the tracked issue in `S:\issues\`

## Policy for Future Releases

1. All GA tags are immutable once created
2. Release branches freeze after GA tag (no direct pushes)
3. Hotfixes branch from the GA tag, not the release branch
4. Dev branches (`v2.9.2-dev`) are the only mutable working branches
