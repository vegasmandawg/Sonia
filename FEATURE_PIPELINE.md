# Sonia Feature Pipeline

**Effective:** 2026-02-08 (post-RC1)

## Change Control Rules

1. **Never commit directly to `master`**. Always use `feat/<name>` branches.
2. **Every change must pass `qualify-change.ps1`** before merge.
3. **Evidence artifact required** per feature under `S:\reports\feature_<name>_<timestamp>\`.
4. **Contracts are immutable** unless explicitly coordinated (see below).

## Immutable Contracts

| Contract | Value | Change Requires |
|---|---|---|
| Ports | 7000/7010/7020/7030/7040/7050 | Coordinated config+smoke+runbook update in same commit |
| Health endpoint | `/healthz` only | Same |
| Start script | `start-sonia-stack.ps1` | Same |
| Stop script | `stop-sonia-stack.ps1` | Same |
| Python env | `S:\envs\sonia-core\python.exe` | Same |

## Feature Branch Workflow

```powershell
# 1. Create branch
git checkout -b feat/<name>

# 2. Implement changes
# ... edit files ...

# 3. Run qualification gate
.\scripts\qualify-change.ps1

# 4. Run feature-specific test (if applicable)
.\scripts\qualify-change.ps1 -FeatureTest ".\tests\<name>\test-<name>.ps1"

# 5. Commit
git add <specific-files>
git commit -m "feat(<scope>): <description>"

# 6. Merge to master
git checkout master
git merge feat/<name>

# 7. Re-run qualification on master
.\scripts\qualify-change.ps1

# 8. Clean up
git branch -d feat/<name>
```

## Gate Requirements (All Must Pass)

| Gate | What | Blocks On |
|---|---|---|
| Static checks | Python compile, PS1 parse | Any syntax error |
| Restart cycle | Cold stop/start | Any service fails to start |
| Health smoke | 6/6 `/healthz` | Any service unhealthy |
| Feature test | Feature-specific script | Non-zero exit code |
| Secret leak | Regex scan for tokens/keys | Any match |
| Dependency drift | Compare to RC pip-freeze | Unapproved new dependency |
| Error log scan | Service stderr logs | Any WARNING/ERROR/CRITICAL |

## Feature Priority Order

| # | Feature | Scope | Acceptance Criteria |
|---|---|---|---|
| 1 | Voice loop hardening | Pipecat | Wake/interrupt/respond 20 consecutive runs, no deadlock. No dropped health in 10-min run. |
| 2 | Action safety layer | OpenClaw/EVA-OS | Explicit approval before destructive actions. Policy intercept logged and test-covered. |
| 3 | Model-router profiles | Model Router | Deterministic routing by task class. Route audit log with reason codes. |
| 4 | Memory-engine reliability | Memory Engine | Schema validation, migration guard, replay safety. Data survives restart. |
| 5 | UI shell polish | UI/API Gateway | Visual identity. No backend contract changes. |

## RC Promotion

After completing a feature set:

```powershell
# Requires 3 consecutive green cycles
.\scripts\promote-rc.ps1 -Version "RC1.1" -Message "feat: voice loop hardening"
```

### RC Promotion Criteria

- 3 clean restart cycles
- Health smoke 6/6 pass
- 0 P0/P1 open issues
- Feature-specific smoke 100% pass
- Updated manifest + hashes + evidence

### RC Artifact Structure

```
S:\baselines\Sonia-RC1.1-<date>\
  RC_MANIFEST.md          Qualification summary
  pip-freeze.txt          Pinned dependencies
  filehashes.txt          SHA256 of critical files
  diff-from-RC1.txt       Changes since last RC
  scripts/                Script snapshot
  config/                 Config snapshot
  services/               Service .py snapshot
```

## Commands Quick Reference

```powershell
# Health check (fast)
.\scripts\health-smoke.ps1

# Full qualification (includes restart)
.\scripts\qualify-change.ps1

# Qualification without restart
.\scripts\qualify-change.ps1 -SkipRestart

# Qualification with feature test
.\scripts\qualify-change.ps1 -FeatureTest ".\tests\pipecat\test-voice.ps1"

# Promote to new RC
.\scripts\promote-rc.ps1 -Version "RC1.1" -Message "description"

# Start/stop stack
.\start-sonia-stack.ps1
.\stop-sonia-stack.ps1
```
