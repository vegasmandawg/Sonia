# OpenClaw Upstream Gateway (Sonia)

This document describes running the vendored OpenClaw upstream Node.js gateway service as a Sonia component.

## Quick Start

```powershell
# 1. Verify prerequisites
.\scripts\diagnostics\doctor-openclaw-upstream.ps1

# 2. Set gateway token
$env:OPENCLAW_GATEWAY_TOKEN = "your-secret-token"

# 3. Start gateway
.\scripts\ops\run-openclaw-upstream.ps1

# 4. Stop gateway
.\scripts\ops\stop-openclaw-upstream.ps1
```

## Architecture

### Repository Structure
- **Upstream source:** `S:\integrations\openclaw\upstream\CURRENT.txt` → pointer to extracted repo
- **Current version:** Stored under `S:\integrations\openclaw\upstream\src\openclaw_*\openclaw-main\`
- **Package manager:** pnpm 10.23.0 (with pnpm-lock.yaml)
- **Build system:** tsdown (TypeScript → JavaScript)
- **Gateway script:** `src/cli/gateway-cli/dev.ts` → dev workspace setup + gateway server

### Sonia Integration

The gateway runs as a standalone Node service under these conventions:

```
Logs:    S:\logs\services\openclaw-upstream.{out,err}.log
PID:     S:\state\pids\openclaw-upstream.pid
Caches:  S:\cache\{npm,pnpm-store,node-gyp}/
Config:  Handled by OpenClaw's config system (~/.openclaw/)
```

The gateway listens on loopback by default (no external exposure) and requires a bearer token for API access.

## Root Cause: Why `npm run gateway:dev` Fails on Windows

### The Problem

The `package.json` script uses Unix shell syntax:
```json
"gateway:dev": "OPENCLAW_SKIP_CHANNELS=1 CLAWDBOT_SKIP_CHANNELS=1 node scripts/run-node.mjs --dev gateway"
```

On Windows cmd.exe, `VAR=value` is not environment variable assignment—it's treated as a **command name**, causing:
```
'OPENCLAW_SKIP_CHANNELS' is not recognized as an internal or external command
→ exit code 1
```

### The Solution

Our wrapper scripts **bypass the npm script** and invoke Node directly with environment variables properly set via PowerShell:

```powershell
# ✅ CORRECT (what our wrapper does)
$env:OPENCLAW_SKIP_CHANNELS = "1"
$env:CLAWDBOT_SKIP_CHANNELS = "1"
& node.exe scripts/run-node.mjs --dev gateway

# ❌ WRONG (what fails)
pnpm gateway:dev          # Tries: OPENCLAW_SKIP_CHANNELS=1 (as cmd)
npm run gateway:dev       # Same issue
```

### Proof

```bash
# Direct invocation with env vars set in bash/PowerShell works:
$ OPENCLAW_SKIP_CHANNELS=1 CLAWDBOT_SKIP_CHANNELS=1 \
  OPENCLAW_GATEWAY_TOKEN=test node scripts/run-node.mjs --dev gateway
# ✓ Gateway starts successfully (assuming token is configured)

# Via pnpm script fails on Windows:
$ pnpm gateway:dev
# ✗ 'OPENCLAW_SKIP_CHANNELS' is not recognized (cmd.exe syntax error)
```

## Usage

### Run Gateway (Development Mode)

```powershell
# Start gateway in dev mode (auto-creates dev config)
.\scripts\ops\run-openclaw-upstream.ps1

# Logs are written to:
Get-Content -Wait -Tail 50 S:\logs\services\openclaw-upstream.out.log
Get-Content -Wait -Tail 50 S:\logs\services\openclaw-upstream.err.log
```

### Configuration

The gateway requires a **token** for authentication:

```powershell
# Option 1: Environment variable (best for scripting)
$env:OPENCLAW_GATEWAY_TOKEN = "your-secret-token"
.\scripts\ops\run-openclaw-upstream.ps1

# Option 2: Via command-line parameter
.\scripts\ops\run-openclaw-upstream.ps1 -Token "your-secret-token"

# Option 3: Configuration file (created by gateway on first run)
# ~/.openclaw/config.yml (check docs for structure)
```

### Reset Configuration

```powershell
# Reset dev workspace and config (on start)
.\scripts\ops\run-openclaw-upstream.ps1 -Reset

# This:
#  - Clears dev agent workspace
#  - Recreates AGENTS.md, SOUL.md, IDENTITY.md, etc.
#  - Regenerates config.yml
```

### Stop Gateway

```powershell
# Graceful shutdown (sends SIGTERM, waits 10s)
.\scripts\ops\stop-openclaw-upstream.ps1

# Immediate kill (if hanging)
.\scripts\ops\stop-openclaw-upstream.ps1 -Force
```

### Diagnostics

```powershell
# Full health check
.\scripts\diagnostics\doctor-openclaw-upstream.ps1

# Verbose output
.\scripts\diagnostics\doctor-openclaw-upstream.ps1 -Verbose

# Checks:
#  ✓ Upstream repo exists
#  ✓ Node/npm available
#  ✓ Engine versions match
#  ✓ Build artifacts present
#  ✓ Sonia ports not in use (7000-7040)
#  ✓ Token configured
```

## Common Issues

### "Process exited immediately (exit=1)"

**Cause:** Environment variable not set when running via npm/pnpm.

**Fix:** Use our wrapper script, which properly sets env vars:
```powershell
.\scripts\ops\run-openclaw-upstream.ps1
```

### "Gateway auth is set to token, but no token is configured"

**Cause:** Missing `OPENCLAW_GATEWAY_TOKEN` environment variable.

**Fix:**
```powershell
$env:OPENCLAW_GATEWAY_TOKEN = "your-token"
.\scripts\ops\run-openclaw-upstream.ps1
```

Or:
```powershell
.\scripts\ops\run-openclaw-upstream.ps1 -Token "your-token"
```

### "pnpm install" hangs or fails

**Cause:** Network issue or corrupted cache.

**Fix:**
```powershell
# Force clean reinstall
.\scripts\ops\run-openclaw-upstream.ps1 -Reinstall
```

This deletes `node_modules` and refetches all dependencies.

### "node.exe not found on PATH"

**Cause:** Node.js not installed or not in PATH.

**Fix:**
```powershell
# Verify Node is available
node --version

# If not, install Node.js v22+ from https://nodejs.org/
```

### Port conflict with Sonia services

**Cause:** Another service using ports 7000-7040.

**Check:**
```powershell
.\scripts\diagnostics\doctor-openclaw-upstream.ps1
# Will report which ports are in use
```

## Build System

The gateway uses OpenClaw's **tsdown** builder:

```
scripts/run-node.mjs
  ↓ (checks if dist/ is stale)
  ├→ If stale: pnpm exec tsdown exec
  │  (compiles src/** → dist/**)
  ↓
openclaw.mjs
  ↓ (checks if dist/entry.js exists)
  ↓
src/entry.ts (compiled to dist/entry.js)
  ↓
src/cli/run-main.ts
  ↓
src/cli/gateway-cli/dev.ts
  ↓
Gateway server starts
```

The build is **idempotent**: if `dist/` is fresh, build is skipped.

To force rebuild:
```powershell
$env:OPENCLAW_FORCE_BUILD = "1"
.\scripts\ops\run-openclaw-upstream.ps1
```

## Environment Variables

### Required

| Variable | Purpose | Example |
|----------|---------|---------|
| `OPENCLAW_GATEWAY_TOKEN` | API authentication token | `"sk-1234..."` |
| `OPENCLAW_SKIP_CHANNELS` | Disable channel auto-load | `"1"` |
| `CLAWDBOT_SKIP_CHANNELS` | Disable bot channel auto-load | `"1"` |

### Optional

| Variable | Purpose | Default |
|----------|---------|---------|
| `OPENCLAW_PROFILE` | Config profile (dev/prod) | `"dev"` (in --dev mode) |
| `OPENCLAW_GATEWAY_BIND` | Bind address | `"loopback"` |
| `OPENCLAW_LOG_LEVEL` | Log verbosity | `"info"` |
| `OPENCLAW_NO_RESPAWN` | Skip Node options respawn | (unset) |

All are exported by our wrapper script or can be set beforehand.

## Logs

Two log files capture all output:

```
S:\logs\services\openclaw-upstream.out.log    # stdout (info, warnings)
S:\logs\services\openclaw-upstream.err.log    # stderr (errors, stack traces)
```

**Tail in real-time:**
```powershell
Get-Content -Wait -Tail 50 S:\logs\services\openclaw-upstream.out.log
Get-Content -Wait -Tail 50 S:\logs\services\openclaw-upstream.err.log
```

**Example output (successful start):**
```
--- started 2026-02-08 13:47:01 -08:00 ---
2026-02-08T13:47:01.787Z [openclaw] Building TypeScript (dist is stale).
[openclaw] tsdown exec...
2026-02-08T13:47:05.123Z [openclaw] Dev config ready: ~/.openclaw/config.yml
2026-02-08T13:47:05.456Z [openclaw] Dev workspace ready: ~/.openclaw/workspace-dev
2026-02-08T13:47:05.789Z [openclaw] Gateway listening on http://127.0.0.1:7040
```

## Files Modified for Sonia

- **S:\scripts\ops\run-openclaw-upstream.ps1** — Windows-safe wrapper (env vars, pnpm detection)
- **S:\scripts\ops\stop-openclaw-upstream.ps1** — Graceful shutdown
- **S:\scripts\diagnostics\doctor-openclaw-upstream.ps1** — Prerequisites validator
- **S:\secrets\templates\openclaw-gateway.env.template** — Token configuration template

## Further Reading

- OpenClaw docs: `S:\integrations\openclaw\upstream\CURRENT.txt` → extract → `docs/gateway/`
- Sonia architecture: See `S:\docs\SONIA_ARCHITECTURE.md`
- pnpm reference: https://pnpm.io/

---

**Last updated:** 2026-02-08  
**Status:** Ready for Sonia integration
