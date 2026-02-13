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

## Policy for Future Releases

1. All GA tags are immutable once created
2. Release branches freeze after GA tag (no direct pushes)
3. Hotfixes branch from the GA tag, not the release branch
4. Dev branches (`v2.9.2-dev`) are the only mutable working branches
