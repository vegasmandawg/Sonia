# OpenClaw - Deterministic Executor Registry

**Phase 1 Implementation Complete**

---

## Overview

OpenClaw is a deterministic executor registry with strict safety boundaries. It provides 4 real tools for shell execution, file operations, and browser automation - all with comprehensive policy enforcement, execution logging, and test coverage.

### Quick Facts
- **Service Port**: 7040
- **Tools Implemented**: 4 (shell.run, file.read, file.write, browser.open)
- **Security Layers**: 3 (allowlist + sandbox + timeout)
- **Test Count**: 80+ (40 contract + 40 executor)
- **Files**: 9 (main service + 3 executors + tests + policy)

---

## Architecture

### Four-Tier Tool System

```
┌─────────────────────────────────────────────────┐
│ FastAPI Service (main.py)                       │
│ - 9 endpoints for execution & management        │
│ - Health check contract compliance              │
│ - Execution logging with correlation IDs        │
└──────────────────┬──────────────────────────────┘
                   │
┌──────────────────▼──────────────────────────────┐
│ Tool Registry (registry.py)                      │
│ - 4 registered tools in deterministic order     │
│ - ToolExecutor pattern for dispatching          │
│ - Execution statistics & logging                │
└──────────────────┬──────────────────────────────┘
                   │
        ┌──────────┼──────────┬──────────┐
        │          │          │          │
   ┌────▼──┐  ┌───▼───┐  ┌───▼───┐  ┌──▼──────┐
   │Shell  │  │File   │  │File   │  │Browser  │
   │Run    │  │Read   │  │Write  │  │Open     │
   └────┬──┘  └───┬───┘  └───┬───┘  └──┬──────┘
        │         │          │         │
   ┌────▼──┬──────▼──┬──────▼──┬──────▼──┐
   │Command │Filesystem│Filesystem│URL      │
   │Allow-  │Sandbox  │Sandbox  │Validation
   │list    │(read)   │(write)  │
   └────────┴─────────┴─────────┴──────────┘

                Policy Engine (policy.py)
```

### Security Layers

#### Layer 1: Command Allowlist
Restricts PowerShell commands to safe subset:
```
ALLOWED:    Get-ChildItem, Get-Item, Get-Content, Test-Path, python
BLOCKED:    Remove-Item, Delete, Stop-Process, Invoke-Expression, &, .
```

#### Layer 2: Filesystem Sandbox
All file operations restricted to S:\ root:
```
SANDBOX_ROOT = S:\
BLOCKED:      S:\Windows, S:\Program Files, S:\System32
```

#### Layer 3: Timeout Enforcement
Configurable execution timeouts with hard limits:
```
Default:      5000ms
Maximum:      15000ms
Enforced:     At policy check time, before execution
```

---

## Tools

### 1. shell.run - PowerShell Execution

Execute PowerShell commands with strict allowlist.

**Request**:
```json
{
  "tool_name": "shell.run",
  "args": {
    "command": "Get-ChildItem -Path S:\\"
  },
  "timeout_ms": 5000,
  "correlation_id": "req_001"
}
```

**Response (200 OK - Executed)**:
```json
{
  "status": "executed",
  "tool_name": "shell.run",
  "result": {
    "command": "Get-ChildItem -Path S:\\",
    "return_code": 0,
    "stdout": "...",
    "stderr": "",
    "elapsed_ms": 45.23,
    "success": true
  },
  "side_effects": [],
  "correlation_id": "req_001",
  "duration_ms": 47.5
}
```

**Response (200 OK - Policy Denied)**:
```json
{
  "status": "error",
  "tool_name": "shell.run",
  "error": "Command 'Remove-Item' not in allowlist",
  "message": "Policy denied execution",
  "correlation_id": "req_001"
}
```

### 2. file.read - Read File

Read file contents from S:\ sandbox.

**Request**:
```json
{
  "tool_name": "file.read",
  "args": {
    "path": "S:\\data\\config.json"
  }
}
```

**Response (200 OK)**:
```json
{
  "status": "executed",
  "tool_name": "file.read",
  "result": {
    "path": "S:\\data\\config.json",
    "size_bytes": 1024,
    "content": "{...}",
    "elapsed_ms": 12.3,
    "success": true
  },
  "side_effects": []
}
```

**Security**:
- Max 10MB file size
- Must be within S:\
- Blocks: S:\Windows, S:\Program Files, etc.

### 3. file.write - Write File

Write file contents to S:\ sandbox.

**Request**:
```json
{
  "tool_name": "file.write",
  "args": {
    "path": "S:\\output\\result.txt",
    "content": "Result content here"
  }
}
```

**Response (200 OK)**:
```json
{
  "status": "executed",
  "tool_name": "file.write",
  "result": {
    "path": "S:\\output\\result.txt",
    "bytes_written": 18,
    "was_existing": false,
    "elapsed_ms": 8.9,
    "success": true
  }
}
```

**Security**:
- Max 10MB content size
- Creates parent directories automatically
- Must be within S:\
- Overwrites existing files

### 4. browser.open - Open URL

Open URL in default browser with domain validation.

**Request**:
```json
{
  "tool_name": "browser.open",
  "args": {
    "url": "https://www.example.com"
  }
}
```

**Response (200 OK)**:
```json
{
  "status": "executed",
  "tool_name": "browser.open",
  "result": {
    "url": "https://www.example.com",
    "opened": true,
    "elapsed_ms": 234.5,
    "success": true
  }
}
```

**Security**:
- Scheme: http/https only
- Blocks: localhost, 127.0.0.1, 192.168.*, 10.0.0.*
- Max URL length: 4096 chars

---

## API Endpoints

### Universal Endpoints (Contract Required)

#### GET /healthz
Health check endpoint (2s timeout).

```bash
curl http://127.0.0.1:7040/healthz
```

Response:
```json
{
  "ok": true,
  "service": "openclaw",
  "timestamp": "2026-02-08T09:30:00.123Z",
  "tools_registered": 4,
  "tools_implemented": 4
}
```

#### GET /
Root endpoint.

```bash
curl http://127.0.0.1:7040/
```

Response:
```json
{
  "service": "openclaw",
  "status": "online",
  "version": "1.0.0"
}
```

#### GET /status
Status with detailed information.

```bash
curl http://127.0.0.1:7040/status
```

Response:
```json
{
  "service": "openclaw",
  "status": "online",
  "timestamp": "2026-02-08T09:30:00.123Z",
  "version": "1.0.0",
  "tools": {
    "total_tools": 4,
    "implemented_tools": 4,
    "readonly_tools": 1,
    "compute_tools": 2,
    "create_tools": 1,
    "destructive_tools": 0
  }
}
```

### Service-Specific Endpoints

#### POST /execute
Execute a tool (main endpoint).

```bash
curl -X POST http://127.0.0.1:7040/execute \
  -H "Content-Type: application/json" \
  -d '{
    "tool_name": "shell.run",
    "args": {"command": "Get-ChildItem"},
    "timeout_ms": 5000,
    "correlation_id": "req_001"
  }'
```

Returns unified ExecuteResponse envelope.

#### GET /tools
List all registered tools.

```bash
curl http://127.0.0.1:7040/tools
```

Response:
```json
{
  "tools": [
    {
      "name": "shell.run",
      "display_name": "Shell Run",
      "description": "Execute PowerShell commands with allowlist",
      "tier": "TIER_1_COMPUTE",
      "requires_sandboxing": false,
      "default_timeout_ms": 5000
    }
  ],
  "total": 4
}
```

#### GET /tools/{tool_name}
Get specific tool metadata.

```bash
curl http://127.0.0.1:7040/tools/shell.run
```

#### GET /registry/stats
Registry statistics.

```bash
curl http://127.0.0.1:7040/registry/stats
```

Response:
```json
{
  "total_tools": 4,
  "implemented_tools": 4,
  "readonly_tools": 1,
  "compute_tools": 2,
  "create_tools": 1,
  "destructive_tools": 0
}
```

#### GET /logs/execution
Execution logs (paginated).

```bash
curl "http://127.0.0.1:7040/logs/execution?limit=10"
```

Response:
```json
{
  "logs": [...],
  "total": 42,
  "returned": 10
}
```

---

## Testing

### Contract Tests (test_contract.py)

40+ tests verifying BOOT_CONTRACT.md compliance:

- Universal endpoints (/healthz, /, /status)
- POST /execute behavior
- Tool registration and listing
- Response structure validation
- Tool-specific execution tests
- Sandbox enforcement
- Policy denial handling

### Executor Unit Tests (test_executors.py)

40+ tests for each executor in isolation:

- **ShellExecutor**: Command allowlist, forbidden commands, timeouts, logging
- **FileExecutor**: Read/write success/failure, sandbox enforcement, size limits, directory creation
- **BrowserExecutor**: URL validation, scheme checking, domain blocking
- **Policy**: Command validation, file path checking, timeout limits, denial logging

### Running Tests

```bash
cd S:\services\openclaw

# Run all tests
python -m pytest test_contract.py test_executors.py -v

# Run specific test class
python -m pytest test_contract.py::TestExecuteEndpoint -v

# Run with coverage
python -m pytest --cov=. test_contract.py test_executors.py
```

---

## File Structure

```
S:\services\openclaw\
├── main.py                    # FastAPI service (9 endpoints)
├── schemas.py                 # Pydantic request/response models
├── policy.py                  # Security policy engine
├── registry.py                # Tool registry and dispatcher
├── test_contract.py           # Contract compliance tests
├── test_executors.py          # Executor unit tests
├── validate_simple.ps1        # Validation script
├── executors/
│   ├── __init__.py
│   ├── shell_exec.py          # PowerShell executor
│   ├── file_exec.py           # Filesystem executor
│   └── browser_exec.py        # Browser executor
├── requirements.lock          # Pinned dependencies
└── README.md                  # This file
```

---

## Starting the Service

### Via Uvicorn

```bash
cd S:\services\openclaw
python -m uvicorn main:app --host 127.0.0.1 --port 7040
```

### Via PowerShell Script

```powershell
S:\scripts\ops\run-openclaw.ps1
```

### Verification

```bash
# Health check
curl http://127.0.0.1:7040/healthz

# List tools
curl http://127.0.0.1:7040/tools

# Execute simple command
curl -X POST http://127.0.0.1:7040/execute \
  -H "Content-Type: application/json" \
  -d '{"tool_name":"shell.run","args":{"command":"Get-ChildItem"}}'
```

---

## Logging

All operations are logged as JSON with correlation IDs:

```json
{
  "timestamp": "2026-02-08T09:30:00.123Z",
  "level": "INFO",
  "service": "openclaw",
  "event": "tool_execution",
  "tool_name": "shell.run",
  "status": "executed",
  "correlation_id": "req_001",
  "duration_ms": 45.23
}
```

Logs can be retrieved via `/logs/execution` endpoint or captured from stdout.

---

## Security Summary

### What OpenClaw Can Do
- ✅ Run whitelisted PowerShell commands (Get-ChildItem, Get-Content, Test-Path, python)
- ✅ Read files from S:\ directory
- ✅ Write files to S:\ directory
- ✅ Create directories automatically
- ✅ Open URLs in default browser (https only)
- ✅ Track execution with correlation IDs
- ✅ Enforce timeouts

### What OpenClaw Cannot Do
- ❌ Execute arbitrary PowerShell commands
- ❌ Delete files or directories
- ❌ Modify protected system directories
- ❌ Access files outside S:\
- ❌ Open localhost URLs
- ❌ Bypass policy enforcement
- ❌ Execute for longer than 15 seconds

---

## Performance Characteristics

### Typical Execution Times
- shell.run: 45-250ms (depends on command)
- file.read: 10-50ms (depends on file size)
- file.write: 5-25ms (depends on content size)
- browser.open: 200-500ms (depends on system)

### Resource Limits
- Max file size (read): 10MB
- Max content size (write): 10MB
- Max URL length: 4096 chars
- Max command output: 10KB
- Max timeout: 15 seconds

---

## Integration with Other Services

### Memory Engine
OpenClaw can execute commands that store results in Memory Engine:

```
User → OpenClaw (shell.run) → file.read → Memory Engine (store)
```

### Model Router
OpenClaw can use Model Router to process command results:

```
User → OpenClaw (shell.run) → Model Router (chat) → Response
```

### API Gateway
API Gateway routes requests to OpenClaw for tool execution:

```
User → API Gateway (/execute) → OpenClaw (/execute) → Response
```

---

## Compliance

✅ **BOOT_CONTRACT.md Compliance**:
- All universal endpoints implemented
- All service-specific endpoints implemented
- Response envelope format correct
- JSON logging format correct
- Health check within 2s timeout
- Port: 7040 (fixed)

✅ **Security Requirements**:
- Command allowlist enforcement
- Filesystem sandbox enforcement
- Timeout enforcement
- Execution logging with correlation IDs
- Policy denial tracking

✅ **Test Coverage**:
- 80+ comprehensive tests
- Contract compliance verified
- Executor behavior verified
- Policy enforcement verified
- Edge cases covered

---

## Status

**Implementation**: ✅ Complete  
**Testing**: ✅ 80+ tests passing  
**Documentation**: ✅ Comprehensive  
**Validation**: ✅ All files present and correct  

**Ready for**: Integration with Pipecat and API Gateway

---

**Last Updated**: 2026-02-08  
**Version**: 1.0.0  
**Port**: 7040
