# SECURITY MODEL

Security posture and threat mitigation for SONIA production system.

## Threat Model Summary

### Deployment Context
- Network: Internal network only, localhost (127.0.0.1) bindings
- Access: Single-user system, local machine access required
- Exposure: No internet-facing services, no external API access
- Trust Boundary: Physical machine boundary (S:\ drive, local processes)

### Assumed Threats (In Scope)
1. Malicious Tool Execution: User-triggered actions that could harm system
2. Path Traversal: Tool calls attempting to escape S:\ root contract
3. Credential Leakage: API keys or secrets written to logs or memory
4. Resource Exhaustion: Unbounded requests causing DoS
5. Injection Attacks: SQL injection, command injection in tool args
6. Dependency Vulnerabilities: Outdated packages with known CVEs

### Out of Scope Threats
1. Network Attacks: No remote access, no MITM, no packet sniffing
2. Privilege Escalation: Single-user system, no multi-tenancy
3. Physical Access: Assumes trusted physical access to machine
4. Browser XSS: Electron UI runs locally, not web-hosted
5. Supply Chain: Assumes trusted PyPI, npm packages (mitigated by lock files)

## Secrets Handling

### Environment Variables
API keys stored in environment variables, loaded at service startup.
Protection: Never log, never write to config, never commit to git, never return in API responses.

### Config File Secrets
S:\config\sonia-config.json stores non-sensitive config only.
Excluded: API keys, database passwords, SSH keys, personal tokens.

### .gitignore Coverage
Excluded: .env, *.local.json, state/, data/, backups/, logs/, incidents/, **/*secret*, **/*credential*, **/*token*, **/*.key, **/*.pem

### Secrets Rotation
Frequency: Every 90 days recommended, or immediately if compromised.
Process: Generate new key, update env var, restart services, verify health, revoke old key.

## Auth Mechanism

### API Key Authentication
Status: Disabled by default (auth.enabled: false in config)
Implementation: services/api-gateway/auth.py
Exempt Paths: /healthz, /status, /docs, /openapi.json
Limitations: Single static token, no expiry, no per-token rate limiting, no audit trail.

### Why Disabled by Default?
SONIA is single-user, local-only. All services bind to 127.0.0.1 with no network exposure.

## Rate Limiting

### Token Bucket Per-Client
Location: services/shared/rate_limiter.py
Configuration: 100 token capacity, 10 tokens/second refill rate
Behavior: 429 Too Many Requests when empty
Exemptions: /healthz, /status, internal service-to-service calls

## CORS Policy

Configuration: Permissive localhost origins (http://localhost:*, http://127.0.0.1:*)
Allowed Methods: GET, POST, PUT, DELETE, OPTIONS
Allowed Headers: Authorization, Content-Type, X-Request-ID

## Log Redaction

### PII Patterns Redacted
Implementation: services/shared/log_redaction.py
Patterns: Email, SSN, Credit Card, Phone, API Keys
Redacted to: [EMAIL_REDACTED], [SSN_REDACTED], [CC_REDACTED], [PHONE_REDACTED], [API_KEY_REDACTED]

## Path Traversal Prevention

### Root Contract Enforcement
Location: services/openclaw/tool_catalog.json
Configuration: root_contract = S:\, deny_escaping_root = true
Validation: Normalize to absolute, resolve symlinks, check S:\ prefix, reject if outside.
Blocked: C:\Windows paths, UNC paths, traversal attempts.

## Tool Safety Tiers

### 4-Tier Policy
Location: services/api-gateway/tool_policy.py
1. safe_read: Auto-approve (file.read, window.list)
2. guarded_low: Confirm if >5 calls/session (clipboard.read)
3. guarded_medium: Always confirm (file.write, keyboard.type)
4. guarded_high: Always confirm + audit (shell.run, app.launch)

Blocked: file.delete, shell.run with admin, unknown capabilities
Confirmation TTL: 120 seconds

## Static Analysis

### Bandit (Python)
Location: bandit.yaml
Run: .\scripts\security-scan.ps1
Checks: Debug mode, pickle, weak hashing, crypto randomness, subprocess, SQL injection, eval/exec

### Pre-Commit Hooks
Location: .pre-commit-config.yaml
Hooks: bandit, black, flake8, mypy
Install: pip install pre-commit; pre-commit install

## Dependency Scanning

### pip-audit (CVE Scanning)
Included in: scripts/security-scan.ps1
Severity: CVSS >= 9.0 block release, 7.0-8.9 fix within 7 days, 4.0-6.9 fix within 30 days.

### Dependency Lock Files
Files: requirements-frozen.txt, dependency-lock.json
Purpose: Reproducible builds, detect tampering, supply chain mitigation.

## Known Limitations / Non-Goals

1. No Encryption at Rest: Database and logs stored plaintext.
2. No Network Encryption: All traffic localhost (no TLS/SSL needed).
3. No Audit Log Signatures: JSONL logs can be modified post-write.
4. No WAF: No web application firewall.
5. No Intrusion Detection: No IDS/IPS monitoring.
6. No Sandboxing: Tool execution runs in same process/user context.
7. No Role-Based Access: Single-user system, no RBAC.
8. No Security Headers: Not applicable to localhost.
9. No Password Policy: No user accounts.
10. No Penetration Testing: Manual security review only.

## Security Checklist

### Before Deployment
- Review sonia-config.json for exposed secrets
- Set API keys in environment variables
- Run security scan
- Verify auth disabled if single-user
- Check .gitignore coverage
- Confirm services bind to 127.0.0.1

### Monthly Maintenance
- Run pip-audit for CVE scan
- Update dependencies with security patches
- Rotate API keys (if enabled)
- Review tool execution audit log
- Check for path traversal attempts

### Incident Response
1. Stop all services
2. Export incident bundle
3. Review JSONL logs for attack pattern
4. Identify compromised capability
5. Patch vulnerability
6. Regenerate API keys if leaked
7. Restart with fix
8. Monitor for 24h
