# OpenClaw Upstream Gateway: Root Cause Analysis

**Issue:** `npm run gateway:dev` exits immediately with exit code 1 on Windows

**Status:** ✅ RESOLVED (with Sonia-safe fix)

---

## Executive Summary

The OpenClaw gateway fails when invoked via npm/pnpm scripts on Windows because the script uses **Unix shell environment variable syntax** (`VAR=value cmd`), which cmd.exe interprets as a command name instead of variable assignment. Our solution bypasses the npm script wrapper and invokes Node directly with proper PowerShell environment variable handling.

---

## Root Cause Chain

### 1. Package.json Script Definition

```json
"gateway:dev": "OPENCLAW_SKIP_CHANNELS=1 CLAWDBOT_SKIP_CHANNELS=1 node scripts/run-node.mjs --dev gateway"
```

This is valid **on Unix shells** (bash, zsh) but **invalid on Windows cmd.exe**.

### 2. How npm/pnpm Scripts Work

When you run `npm run gateway:dev` or `pnpm gateway:dev`:

**On macOS/Linux:**
```bash
$ bash -c "OPENCLAW_SKIP_CHANNELS=1 CLAWDBOT_SKIP_CHANNELS=1 node scripts/run-node.mjs --dev gateway"
# bash interprets VAR=value as environment assignment ✓
```

**On Windows (cmd.exe):**
```cmd
C:\> cmd.exe /d /c "OPENCLAW_SKIP_CHANNELS=1 CLAWDBOT_SKIP_CHANNELS=1 node scripts/run-node.mjs --dev gateway"
# cmd.exe tries to execute: OPENCLAW_SKIP_CHANNELS=1 (as a program name) ✗
```

### 3. Actual Error Captured

```
> openclaw@2026.2.6-3 gateway:dev ...
> OPENCLAW_SKIP_CHANNELS=1 CLAWDBOT_SKIP_CHANNELS=1 node scripts/run-node.mjs --dev gateway

'OPENCLAW_SKIP_CHANNELS' is not recognized as an internal or external command,
operable program or batch file.
 ELIFECYCLE  Command failed with exit code 1.
```

The npm/pnpm wrapper detected the script failure and propagated exit code 1.

### 4. Secondary Issue

Even if the env var syntax worked, the gateway would immediately fail with:

```
2026-02-08T13:47:01.787Z Gateway auth is set to token, but no token is configured.
Set gateway.auth.token (or OPENCLAW_GATEWAY_TOKEN), or pass --token.
```

The gateway requires a bearer token for authentication.

---

## Why This Happens

### Windows Command-Line Semantics

| OS | Shell | VAR=value behavior |
|----|----|---|
| Linux | bash/zsh | Sets env var, then runs command |
| macOS | zsh/bash | Sets env var, then runs command |
| Windows | cmd.exe | Treats `VAR=value` as a command name |
| Windows (modern) | PowerShell | Supports `$env:VAR = value` syntax |

npm/pnpm always use the system default shell:
- **Unix:** bash/zsh (supports `VAR=value`)
- **Windows:** cmd.exe (does NOT support `VAR=value`)

### The Repository

OpenClaw is a **Unix-primary project** developed on macOS/Linux with GitHub Actions CI. The package.json scripts use Unix conventions that don't translate to Windows.

---

## Solution Architecture

We created **Sonia-safe wrappers** that:

1. **Bypass npm/pnpm script execution** (avoid Windows cmd.exe limitations)
2. **Use PowerShell for proper env var handling**
3. **Invoke Node directly** with required parameters
4. **Integrate with Sonia conventions** (logs, PIDs, caches under S:\)

### The Fix

**Instead of:**
```powershell
pnpm gateway:dev              # ✗ Fails on Windows
npm run gateway:dev           # ✗ Fails on Windows
```

**Use:**
```powershell
$env:OPENCLAW_SKIP_CHANNELS = "1"
$env:CLAWDBOT_SKIP_CHANNELS = "1"
$env:OPENCLAW_GATEWAY_TOKEN = "your-token"
& node.exe scripts/run-node.mjs --dev gateway
```

This is exactly what `S:\scripts\ops\run-openclaw-upstream.ps1` does, with added:
- Dependency installation
- Log rotation
- PID tracking
- Health checks
- Error reporting

---

## Proof of Root Cause

### Test 1: Direct Node (Works ✓)

```powershell
$env:OPENCLAW_SKIP_CHANNELS = "1"
$env:CLAWDBOT_SKIP_CHANNELS = "1"
$env:OPENCLAW_GATEWAY_TOKEN = "test-token"
node scripts/run-node.mjs --dev gateway

# Output:
# 2026-02-08T13:51:13.828Z [gateway] listening on ws://127.0.0.1:19001
# ✓ Gateway running successfully
```

### Test 2: Via pnpm Script (Fails ✗)

```powershell
pnpm gateway:dev

# Output:
# 'OPENCLAW_SKIP_CHANNELS' is not recognized as an internal or external command
# ELIFECYCLE Command failed with exit code 1.
# ✗ Windows cmd.exe syntax error
```

### Test 3: Via npm Script (Fails ✗)

```powershell
npm run gateway:dev

# Same error (npm delegates to cmd.exe on Windows)
```

---

## Implementation Details

### Scripts Created

1. **S:\scripts\ops\run-openclaw-upstream.ps1**
   - Validates prerequisites
   - Installs dependencies (if needed)
   - Sets environment variables properly
   - Starts gateway with logging
   - Detects immediate crashes and explains why

2. **S:\scripts\ops\stop-openclaw-upstream.ps1**
   - Graceful shutdown (SIGTERM, 10s timeout)
   - Force kill if needed
   - Cleans up PID file

3. **S:\scripts\diagnostics\doctor-openclaw-upstream.ps1**
   - Validates Node/npm availability
   - Checks engine compatibility
   - Verifies build artifacts
   - Detects port conflicts with Sonia
   - Reports missing configuration

### Key Behaviors

**Environment Variables (Properly Set):**
```powershell
$env:OPENCLAW_SKIP_CHANNELS = "1"        # Skip WhatsApp/channel startup
$env:CLAWDBOT_SKIP_CHANNELS = "1"        # Skip bot channels
$env:OPENCLAW_GATEWAY_TOKEN = "..."      # Required for auth
$env:npm_config_cache = "S:\cache\npm"   # Keep cache under S:\
$env:PNPM_STORE_PATH = "S:\cache\pnpm"   # Keep pnpm store under S:\
```

**Logging:**
```
S:\logs\services\openclaw-upstream.out.log   # stdout
S:\logs\services\openclaw-upstream.err.log   # stderr
```

**PID Tracking:**
```
S:\state\pids\openclaw-upstream.pid          # Process ID
```

**Build Behavior:**
- First run: Compiles TypeScript (via tsdown) → dist/
- Subsequent runs: Skips build if files are fresh
- Force rebuild: `$env:OPENCLAW_FORCE_BUILD = "1"`

---

## Why Not Fix the Upstream?

The upstream package.json uses Unix-style syntax because:

1. **Cross-platform support:** The repo supports macOS/iOS apps, not just Windows CLI
2. **CI/CD is Unix:** GitHub Actions runners use Linux
3. **Developer base:** OpenClaw is primary macOS/Linux development

A Windows fix would require:
- Use `cross-env` package (adds Windows env var support) → adds dependency
- Or use platform-specific scripts → adds complexity

For Sonia (Windows-only internal use), our wrapper is simpler and safer.

---

## Verification Checklist

- [x] Root cause identified: Unix shell syntax unsupported on Windows cmd.exe
- [x] Proof of concept works: Direct Node invocation succeeds
- [x] Wrapper script created: `run-openclaw-upstream.ps1`
- [x] Stop script created: `stop-openclaw-upstream.ps1`
- [x] Diagnostic tool created: `doctor-openclaw-upstream.ps1`
- [x] Documentation updated: `S:\docs\OPENCLAW_UPSTREAM.md`
- [x] Token requirements documented
- [x] All scripts follow Sonia conventions (S:\ root, logs, PIDs)
- [x] Error messages are actionable
- [x] Gateway starts successfully when invoked correctly

---

## Testing

### To Reproduce the Original Failure

```powershell
cd S:\integrations\openclaw\upstream\src\openclaw_9120249D4287_20260208_065343\openclaw-main
pnpm gateway:dev
# Expected: 'OPENCLAW_SKIP_CHANNELS' is not recognized...
# Exit code: 1
```

### To Verify the Fix Works

```powershell
# Run diagnostics
.\scripts\diagnostics\doctor-openclaw-upstream.ps1

# Set token (required)
$env:OPENCLAW_GATEWAY_TOKEN = "test-token"

# Start gateway
.\scripts\ops\run-openclaw-upstream.ps1

# Expected output:
# === OpenClaw Upstream Gateway (Sonia) ===
# ...
# Gateway is running. Tail logs:
#   Get-Content -Wait -Tail 50 "S:\logs\services\openclaw-upstream.out.log"
```

---

## Files Modified

| File | Purpose | Status |
|------|---------|--------|
| `S:\scripts\ops\run-openclaw-upstream.ps1` | Main wrapper (replace existing) | ✅ Created |
| `S:\scripts\ops\stop-openclaw-upstream.ps1` | Stop wrapper (new) | ✅ Created |
| `S:\scripts\diagnostics\doctor-openclaw-upstream.ps1` | Diagnostics (new) | ✅ Created |
| `S:\secrets\templates\openclaw-gateway.env.template` | Token template (new) | ✅ Created |
| `S:\docs\OPENCLAW_UPSTREAM.md` | User guide (new) | ✅ Created |
| `S:\docs\OPENCLAW_ROOT_CAUSE_ANALYSIS.md` | This document (new) | ✅ Created |

---

## Next Steps for Users

1. **Read the user guide:**
   ```powershell
   Get-Content S:\docs\OPENCLAW_UPSTREAM.md
   ```

2. **Run diagnostics:**
   ```powershell
   .\scripts\diagnostics\doctor-openclaw-upstream.ps1
   ```

3. **Set up token:**
   ```powershell
   $env:OPENCLAW_GATEWAY_TOKEN = "your-secret-token"
   ```

4. **Start gateway:**
   ```powershell
   .\scripts\ops\run-openclaw-upstream.ps1
   ```

5. **Monitor logs:**
   ```powershell
   Get-Content -Wait -Tail 50 S:\logs\services\openclaw-upstream.out.log
   ```

---

## Technical Details for Reference

### Stack Trace Analysis

When pnpm tries to execute the script on Windows:

```
1. pnpm parses package.json
2. Identifies: "gateway:dev": "OPENCLAW_SKIP_CHANNELS=1 ... node ..."
3. On Windows: spawns cmd.exe /d /c "OPENCLAW_SKIP_CHANNELS=1 ..."
4. cmd.exe parser sees: OPENCLAW_SKIP_CHANNELS=1 (no recognized command)
5. Exits with: "not recognized as internal or external command"
6. Exit code propagates through npm/pnpm wrapper: 1
```

### Comparison: Unix vs Windows

**Unix (macOS/Linux):**
```bash
$ bash -c "VAR=value cmd arg"
# Lexer sees: VAR=value → env var assignment
#             cmd arg    → command with args
# Result: ✓ Works
```

**Windows (cmd.exe):**
```cmd
C:\> cmd.exe /c "VAR=value cmd arg"
# Lexer sees: VAR=value (no recognized command prefix)
# Parser tries to execute: VAR=value
# Result: ✗ Fails ("VAR=value is not recognized...")
```

**Windows (PowerShell):**
```powershell
$env:VAR = "value"
cmd arg
# Result: ✓ Works (PowerShell syntax, not cmd.exe)
```

---

**Analysis completed:** 2026-02-08  
**Solution validated:** ✅  
**Ready for production:** Yes
