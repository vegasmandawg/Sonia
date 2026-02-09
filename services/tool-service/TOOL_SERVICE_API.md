"""
Tool Service API Documentation

Complete guide to tool management, execution, and integration.
"""

# Tool Service API Documentation

## Overview

The Tool Service provides a centralized platform for:
- **Tool Discovery**: Browse and filter available tools
- **Tool Execution**: Execute tools with risk-based approval
- **Catalog Management**: Import/export tool definitions
- **Statistics & Monitoring**: Track tool usage and health
- **Rate Limiting**: Prevent abuse and manage resources
- **Approval Workflow**: Risk-tiered execution policies

## Architecture

### Core Components

1. **ToolRegistry** (512 lines)
   - Central catalog of all tools
   - Metadata and parameter validation
   - Usage statistics tracking
   - Alias resolution

2. **ToolExecutor** (450 lines)
   - Executes tools with timeout protection
   - Risk-based approval policies
   - Rate limiting enforcement
   - Execution history management

3. **Standard Tools** (618 lines)
   - Filesystem operations (read, write, list)
   - Computation (evaluate, search, parse)
   - System information
   - Network operations (fetch, resolve)

4. **Tool Service** (463 lines)
   - FastAPI application
   - RESTful API endpoints
   - Health monitoring
   - Catalog management

## Risk Tiers

### TIER_0: No Risk
- Read-only operations
- No side effects
- No approval required
- Examples: read_file, list_directory, get_file_info

### TIER_1: Low Risk
- Local file I/O with side effects
- Limited scope operations
- May require approval for sensitive paths
- Examples: write_file, append_file

### TIER_2: Medium Risk
- Network operations
- External API calls
- Rate limited
- Examples: fetch_url, resolve_hostname

### TIER_3: High Risk
- Destructive operations
- System modifications
- Admin actions
- Always requires approval
- Examples: delete_directory, system_reboot (when added)

## Tool Categories

- **filesystem**: File and directory operations
- **network**: HTTP, DNS, and network operations
- **computation**: Math, text processing, parsing
- **media**: Image, audio, video operations
- **database**: Database operations
- **system**: System information and control
- **communication**: Email, messaging, etc.
- **development**: Build, testing, deployment
- **monitoring**: Metrics, logging, diagnostics
- **security**: Authentication, encryption, etc.

## API Endpoints

### Tool Discovery

#### GET /api/v1/tools

List available tools with optional filtering.

**Query Parameters:**
```
category: filesystem|network|computation|media|database|system|communication|development|monitoring|security
risk_tier: tier_0|tier_1|tier_2|tier_3
tag: string (matches any tag)
```

**Response:**
```json
{
  "success": true,
  "total_tools": 12,
  "tools": [
    {
      "name": "read_file",
      "description": "Read file contents",
      "category": "filesystem",
      "risk_tier": "tier_0",
      "parameters": [
        {
          "name": "path",
          "type": "string",
          "required": true,
          "description": "File path"
        }
      ],
      "returns": "File contents as string",
      "requires_approval": false,
      "timeout_seconds": 30
    }
  ]
}
```

**Example:**
```bash
curl http://localhost:7040/api/v1/tools?category=filesystem&risk_tier=tier_0
```

---

#### GET /api/v1/tools/{tool_name}

Get specific tool definition.

**Response:**
```json
{
  "success": true,
  "tool": { /* tool definition */ }
}
```

**Example:**
```bash
curl http://localhost:7040/api/v1/tools/read_file
```

---

### Tool Execution

#### POST /api/v1/tools/{tool_name}/execute

Execute a single tool.

**Path Parameters:**
```
tool_name: string (tool name or alias)
```

**Query Parameters:**
```
user_id: string (optional, user identifier)
approved: boolean (whether execution is pre-approved)
```

**Body:**
```json
{
  "parameter_name": "value",
  "another_param": 123
}
```

**Response (Success):**
```json
{
  "success": true,
  "result": {
    "request_id": "uuid",
    "tool_name": "read_file",
    "status": "completed",
    "result": "File contents...",
    "execution_time_ms": 45.2,
    "timestamp": "2024-01-15T10:30:45.123Z"
  }
}
```

**Response (Requires Approval):**
```json
{
  "success": false,
  "result": {
    "status": "requires_approval",
    "error": "Tool 'write_file' requires approval"
  }
}
```

**Example:**
```bash
curl -X POST http://localhost:7040/api/v1/tools/read_file/execute \
  -H "Content-Type: application/json" \
  -d '{"path": "/path/to/file.txt"}'
```

---

#### POST /api/v1/tools/batch-execute

Execute multiple tools sequentially or in parallel.

**Query Parameters:**
```
user_id: string (optional)
approved: boolean (pre-approve all executions)
parallel: boolean (execute in parallel, default: false)
```

**Body:**
```json
[
  {
    "tool_name": "read_file",
    "parameters": {"path": "/file1.txt"}
  },
  {
    "tool_name": "search_text",
    "parameters": {
      "text": "content",
      "pattern": "error.*"
    }
  }
]
```

**Response:**
```json
{
  "success": true,
  "total_requests": 2,
  "completed": 2,
  "failed": 0,
  "results": [
    { /* execution result 1 */ },
    { /* execution result 2 */ }
  ]
}
```

**Example:**
```bash
curl -X POST http://localhost:7040/api/v1/tools/batch-execute?parallel=true \
  -H "Content-Type: application/json" \
  -d '[
    {"tool_name": "get_system_info", "parameters": {}},
    {"tool_name": "get_current_time", "parameters": {}}
  ]'
```

---

### Execution History

#### GET /api/v1/executions

Get execution history.

**Query Parameters:**
```
tool_name: string (filter by tool)
limit: integer (max results, default: 100)
```

**Response:**
```json
{
  "success": true,
  "total_results": 5,
  "executions": [
    { /* execution result */ }
  ]
}
```

---

#### GET /api/v1/executions/{request_id}

Get specific execution result.

**Response:**
```json
{
  "success": true,
  "result": { /* execution result */ }
}
```

---

#### DELETE /api/v1/executions/history

Clear execution history.

**Response:**
```json
{
  "success": true,
  "cleared_entries": 150
}
```

---

### Statistics & Monitoring

#### GET /api/v1/stats

Get aggregate statistics.

**Response:**
```json
{
  "success": true,
  "health": {
    "status": "healthy",
    "total_tools": 12,
    "total_calls": 1250,
    "successful_calls": 1200,
    "failed_calls": 50,
    "overall_success_rate": 96.0,
    "problematic_tools": []
  },
  "tools": {
    "read_file": {
      "tool_name": "read_file",
      "total_calls": 250,
      "successful_calls": 248,
      "failed_calls": 2,
      "success_rate": 99.2,
      "average_execution_time_ms": 23.5
    }
  }
}
```

---

#### GET /api/v1/tools/{tool_name}/stats

Get tool-specific statistics.

**Response:**
```json
{
  "success": true,
  "stats": {
    "tool_name": "read_file",
    "total_calls": 250,
    "successful_calls": 248,
    "success_rate": 99.2
  }
}
```

---

#### GET /health

Health check endpoint.

**Response:**
```json
{
  "status": "healthy",
  "total_tools": 12,
  "total_calls": 1250,
  "successful_calls": 1200,
  "failed_calls": 50,
  "overall_success_rate": 96.0
}
```

---

### Catalog Management

#### GET /api/v1/catalog/export

Export complete tool catalog.

**Response:**
```json
{
  "success": true,
  "catalog": {
    "timestamp": "2024-01-15T10:30:45.123Z",
    "total_tools": 12,
    "tools": {
      "read_file": { /* tool definition */ }
    },
    "stats": {
      "read_file": { /* tool stats */ }
    }
  }
}
```

---

#### POST /api/v1/catalog/import

Import tools from catalog file.

**Body:**
```json
{
  "catalog_path": "/path/to/catalog.json"
}
```

**Response:**
```json
{
  "success": true,
  "total_tools": 12,
  "message": "Imported tools from /path/to/catalog.json"
}
```

---

## Standard Tools

### Filesystem Tools

#### read_file
```json
{
  "tool_name": "read_file",
  "parameters": {
    "path": "/path/to/file.txt",
    "encoding": "utf-8"
  }
}
```

#### write_file (TIER_1, requires approval)
```json
{
  "tool_name": "write_file",
  "parameters": {
    "path": "/path/to/file.txt",
    "content": "File content",
    "encoding": "utf-8"
  }
}
```

#### list_directory
```json
{
  "tool_name": "list_directory",
  "parameters": {
    "path": "/path/to/directory",
    "recursive": false
  }
}
```

#### get_file_info
```json
{
  "tool_name": "get_file_info",
  "parameters": {
    "path": "/path/to/file.txt"
  }
}
```

### Computation Tools

#### evaluate_expression
```json
{
  "tool_name": "evaluate_expression",
  "parameters": {
    "expression": "2 * 3 + (4 / 2)"
  }
}
```

#### search_text
```json
{
  "tool_name": "search_text",
  "parameters": {
    "text": "Large text to search...",
    "pattern": "error.*",
    "case_sensitive": false
  }
}
```

#### parse_json
```json
{
  "tool_name": "parse_json",
  "parameters": {
    "json_string": "{\"key\": \"value\"}"
  }
}
```

### System Tools

#### get_system_info
```json
{
  "tool_name": "get_system_info",
  "parameters": {}
}
```

#### get_current_time
```json
{
  "tool_name": "get_current_time",
  "parameters": {}
}
```

### Network Tools

#### fetch_url
```json
{
  "tool_name": "fetch_url",
  "parameters": {
    "url": "https://api.example.com/data",
    "timeout": 30
  }
}
```

#### resolve_hostname
```json
{
  "tool_name": "resolve_hostname",
  "parameters": {
    "hostname": "example.com"
  }
}
```

---

## Approval Workflow

### Automatic Approval (TIER_0)
- No approval required
- Executes immediately

### Manual Approval (TIER_1, TIER_2, TIER_3)

**Step 1: Check if approval required**
```bash
curl http://localhost:7040/api/v1/tools/write_file
# See: "requires_approval": true
```

**Step 2: Request execution (will return requires_approval status)**
```bash
curl -X POST http://localhost:7040/api/v1/tools/write_file/execute \
  -H "Content-Type: application/json" \
  -d '{"path": "/file.txt", "content": "data"}'
# Returns: {"status": "requires_approval"}
```

**Step 3: Execute with approval**
```bash
curl -X POST http://localhost:7040/api/v1/tools/write_file/execute?approved=true \
  -H "Content-Type: application/json" \
  -d '{"path": "/file.txt", "content": "data"}'
# Executes and returns result
```

---

## Configuration

### Environment Variables

```bash
# Service Configuration
TOOL_SERVICE_PORT=7040
TOOL_SERVICE_HOST=0.0.0.0
LOG_LEVEL=INFO

# Catalog
TOOL_CATALOG_PATH=/path/to/catalog.json  # Optional
```

### Tool Parameters

Parameters are strongly typed with validation:

| Type | Validation | Example |
|------|-----------|---------|
| string | Length, pattern (regex) | "hello", "/path/to/file" |
| integer | Min/max values | 5, -10 |
| number | Min/max values | 3.14, 0.5 |
| boolean | true/false | true |
| array | Item type | ["item1", "item2"] |
| object | Schema (optional) | {"key": "value"} |

---

## Error Handling

### Status Codes

| Status | Meaning | Example |
|--------|---------|---------|
| 200 | Success | Tool executed successfully |
| 202 | Accepted | Execution pending approval |
| 400 | Bad Request | Invalid parameters |
| 404 | Not Found | Tool or execution not found |
| 500 | Server Error | Internal error |

### Error Response Format

```json
{
  "detail": "Error description",
  "request_id": "uuid"
}
```

---

## Performance

### Latency Targets (p99)
- Tool lookup: <1ms
- Parameter validation: <1ms
- Tool execution: 10-5000ms (depends on tool)
- Batch execution: Linear with tool count

### Throughput
- Sequential execution: 10-100 tools/second
- Parallel execution: 20-50 concurrent
- Rate limiting: Per-tool limits enforced

### Rate Limiting
- Default: 10 calls per minute (for TIER_2 tools)
- Configurable per tool
- Resets on minute boundary

---

## Integration Examples

### Python Client

```python
import aiohttp
import json

async def execute_tool(tool_name, parameters):
    async with aiohttp.ClientSession() as session:
        url = f"http://localhost:7040/api/v1/tools/{tool_name}/execute"
        async with session.post(url, json=parameters) as resp:
            return await resp.json()

# Execute a tool
result = await execute_tool("read_file", {"path": "/etc/hostname"})
print(result["result"]["result"])
```

### JavaScript/Node.js

```javascript
async function executeTool(toolName, parameters) {
  const response = await fetch(
    `http://localhost:7040/api/v1/tools/${toolName}/execute`,
    {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(parameters)
    }
  );
  return response.json();
}

const result = await executeTool('get_system_info', {});
console.log(result.result);
```

### cURL

```bash
# List all filesystem tools
curl "http://localhost:7040/api/v1/tools?category=filesystem"

# Execute a tool
curl -X POST http://localhost:7040/api/v1/tools/read_file/execute \
  -H "Content-Type: application/json" \
  -d '{"path": "/path/to/file"}'

# Batch execution
curl -X POST http://localhost:7040/api/v1/tools/batch-execute?parallel=true \
  -H "Content-Type: application/json" \
  -d '[
    {"tool_name": "get_current_time", "parameters": {}},
    {"tool_name": "get_system_info", "parameters": {}}
  ]'
```

---

## Best Practices

1. **Always validate tool existence** before execution
2. **Check approval requirements** before user-facing execution
3. **Use batch execution** for related operations
4. **Monitor rate limits** to avoid blocking
5. **Cache tool definitions** to reduce API calls
6. **Handle timeouts gracefully** with retry logic
7. **Track execution history** for auditing
8. **Implement rollback** for multi-step operations

---

## API Version

- **Current Version**: 1.0.0
- **Service Port**: 7040
- **Last Updated**: 2024-01-15
