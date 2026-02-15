# Retrospective and Review Cadence

**Version:** 1.0.0
**Last Updated:** 2026-02-15
**Owner:** Project Maintainer(s)

## Overview

This document defines the operational review cadence for the SONIA project. Regular retrospectives ensure continuous improvement, risk mitigation, and incident response maturity.

---

## Weekly Standup (Health Review)

**Frequency:** Weekly (Monday mornings recommended)
**Duration:** 15 minutes
**Participants:** Project maintainers

### Agenda

1. **Service health**: Check EVA-OS /healthz dashboard, review ServiceSupervisor state
2. **DLQ status**: Check dead letter queue size (alert if >500 entries)
3. **Incident triage**: Any new incidents since last standup? (check logs/gateway/*.jsonl)
4. **Action items**: Review open action items from prior week

### Output

- Quick verbal sync or written notes (no formal document required)
- Action items logged in project tracker (if any)

---

## Monthly Retrospective (Incident Review)

**Frequency:** Monthly (first Friday of month recommended)
**Duration:** 60 minutes
**Participants:** Project maintainers, stakeholders

### Agenda

1. **Incident review**: Review all incidents from past month using incident bundles
   - What happened? Root cause? Time to detect? Time to resolve?
   - What went well? What can be improved?
2. **Risk register update**: Review risk-register.yaml
   - Any new risks identified?
   - Any mitigations to update?
   - Any risks to escalate or accept?
3. **Gate summary**: Review promotion gate reports from past month
   - Any gate failures? Why?
   - Any gates skipped? Acceptable?
4. **DLQ patterns**: Review dead letter queue entries
   - Common failure modes?
   - Retry taxonomy coverage gaps?
5. **Action items**: Assign owners and due dates

### Output

- **Retrospective notes**: Brief summary (1-2 pages) in `docs/retrospectives/YYYY-MM.md`
- **Risk register updates**: Commit updated risk-register.yaml if changed
- **Action items**: Logged in project tracker

### Template

```markdown
# Monthly Retrospective: YYYY-MM

## Incidents
- [List incidents, root causes, resolutions]
- [Lessons learned]

## Risk Register
- [Any new risks added]
- [Any risk status changes]

## Gate Summary
- [Promotions this month]
- [Any gate failures or skips]

## DLQ Patterns
- [Common failure modes]
- [Recommendations]

## Action Items
- [ ] Action 1 (Owner: X, Due: DATE)
- [ ] Action 2 (Owner: Y, Due: DATE)
```

---

## Quarterly Review (Deep Audit)

**Frequency:** Quarterly (end of Q1/Q2/Q3/Q4)
**Duration:** 2-3 hours
**Participants:** Project maintainers, security/privacy stakeholders

### Agenda

1. **Dependency audit**: Review requirements-frozen.txt and dependency-lock.json
   - Any known CVEs? (check GitHub Dependabot, safety, or manual scan)
   - Any major version updates available?
   - Any deprecated dependencies?
2. **Security scan**: Run security tooling (bandit, semgrep, or manual review)
   - Any new vulnerabilities?
   - Any secrets leakage?
   - Review log redaction patterns (shared/log_redaction.py)
3. **Privacy review**: Review perception privacy controls
   - Vision-capture privacy gate audit
   - SceneAnalysis confirmation flow audit
   - PerceptionActionGate bypass testing
4. **Backup drill**: Execute backup/restore drill
   - Test backup creation
   - Test SHA-256 manifest verification
   - Test restore from backup
   - Document RTO (Recovery Time Objective)
5. **Risk register refresh**: Full review of all risks
   - Update likelihood/severity based on 3 months of data
   - Close mitigated risks if appropriate
   - Add new risks identified in audit
6. **Runbook validation**: Walk through RUNBOOK.md procedures
   - Any stale procedures?
   - Any gaps in failure mode coverage?

### Output

- **Quarterly audit report**: Comprehensive report (3-5 pages) in `docs/audits/YYYY-QX.md`
- **Risk register updates**: Commit updated risk-register.yaml
- **Dependency updates**: If critical CVEs, create upgrade plan
- **Action items**: Logged in project tracker with quarterly priority

### Template

```markdown
# Quarterly Audit: YYYY-QX

## Dependency Audit
- Total dependencies: X
- Known CVEs: [list or "none"]
- Deprecated packages: [list or "none"]
- Recommended updates: [list or "none"]

## Security Scan
- Tool used: [bandit / semgrep / manual]
- Findings: [list or "none"]
- False positives: [list]
- Remediations: [list]

## Privacy Review
- Vision-capture gate: [PASS / FAIL]
- SceneAnalysis confirmation: [PASS / FAIL]
- PerceptionActionGate bypass test: [PASS / FAIL]
- Findings: [list]

## Backup Drill
- Backup created: [timestamp]
- Backup size: [MB]
- SHA-256 verified: [PASS / FAIL]
- Restore tested: [PASS / FAIL]
- RTO measured: [seconds]
- Findings: [list]

## Risk Register Refresh
- New risks: [count]
- Closed risks: [count]
- Escalated risks: [count]
- Summary: [brief]

## Runbook Validation
- Procedures tested: [count]
- Stale procedures: [list or "none"]
- Gaps identified: [list or "none"]

## Action Items
- [ ] Critical action 1 (Owner: X, Due: DATE)
- [ ] High action 2 (Owner: Y, Due: DATE)
```

---

## Incident Response Tie-In

These ceremonies directly support incident response maturity:

- **Weekly standup**: Early detection (DLQ size, service health)
- **Monthly retrospective**: Post-incident review, lessons learned, risk register updates
- **Quarterly review**: Proactive risk reduction (dependency audit, security scan, backup drill)

All incidents should be logged using the incident bundle export:

```powershell
.\scripts\export-incident-bundle.ps1 -WindowMinutes 60
```

This generates a bundle in `S:\incidents\incident-YYYYMMDD-HHMMSS\` with:
- Correlation traces
- JSONL logs
- Service health snapshots
- DLQ state
- Breaker metrics

---

## Known Limitations / Non-Goals

This cadence does **not** require:

- **Daily standups** (SONIA is not a team project; weekly is sufficient)
- **Formal incident management system** (file-based incident bundles are sufficient)
- **External audit** (internal audit by maintainers is sufficient)
- **SLA tracking** (SONIA is development/research, not production SLA-bound)
- **Change Advisory Board (CAB)** (promotion gates replace formal CAB process)

---

## Review Schedule

| Ceremony | Frequency | Next Due | Owner |
|----------|-----------|----------|-------|
| Weekly Standup | Weekly | [Monday] | Maintainer |
| Monthly Retrospective | Monthly | [First Friday] | Maintainer |
| Quarterly Review | Quarterly | [End of Q1: Mar 31] | Maintainer + Security |

Update this table after each ceremony to track next due dates.
