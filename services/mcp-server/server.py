"""
SONIA MCP Server (v1.0)

Exposes SONIA's turn pipeline and OpenClaw tool catalog as an MCP server.
Implements the Model Context Protocol (JSON-RPC over stdio) so that
Claude Desktop, other MCP clients, or any MCP-compatible host can:

  - Chat with Sonia  (sonia_chat tool)
  - Execute OpenClaw tools  (filesystem.*, process.*, shell.*, http.*)
  - Search Sonia's memory  (sonia_memory_search tool)
  - Read memory-engine stats  (memory://stats resource)
  - Read service health  (health://services resource)

Usage:
    python server.py                   # stdio transport (default)
    python server.py --sse --port 8080 # SSE transport for web clients

All logging goes to stderr (never stdout -- that's the JSON-RPC channel).
"""

import asyncio
import json
import logging
import re
import sys
import time
from pathlib import Path
from typing import Any, Dict, Optional

import httpx
from mcp.server.fastmcp import FastMCP

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

CONFIG_PATH = Path(r"S:\config\sonia-config.json")

# Defaults (overridden by config file if present)
GATEWAY_URL = "http://127.0.0.1:7000"
MEMORY_URL = "http://127.0.0.1:7020"
OPENCLAW_URL = "http://127.0.0.1:7040"
MODEL_ROUTER_URL = "http://127.0.0.1:7010"

TOOL_CATALOG_PATH = Path(r"S:\services\openclaw\tool_catalog.json")

# Logging to stderr only
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    stream=sys.stderr,
)
logger = logging.getLogger("sonia-mcp")


def _load_config() -> Dict[str, Any]:
    """Load sonia-config.json if present."""
    if CONFIG_PATH.exists():
        try:
            return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        except Exception as e:
            logger.warning("Failed to load config: %s", e)
    return {}


def _load_tool_catalog() -> Dict[str, Any]:
    """Load OpenClaw tool catalog."""
    if TOOL_CATALOG_PATH.exists():
        try:
            return json.loads(TOOL_CATALOG_PATH.read_text(encoding="utf-8"))
        except Exception as e:
            logger.warning("Failed to load tool catalog: %s", e)
    return {"tools": {}}


# ---------------------------------------------------------------------------
# HTTP client (shared)
# ---------------------------------------------------------------------------

_http: Optional[httpx.AsyncClient] = None


def _get_http() -> httpx.AsyncClient:
    global _http
    if _http is None or _http.is_closed:
        _http = httpx.AsyncClient(timeout=30.0)
    return _http


# ---------------------------------------------------------------------------
# OpenClaw execution helper
# ---------------------------------------------------------------------------

async def _execute_openclaw(tool_name: str, args: Dict[str, Any]) -> str:
    """Execute a tool via OpenClaw /execute endpoint. Returns formatted result."""
    client = _get_http()
    try:
        resp = await client.post(
            f"{OPENCLAW_URL}/execute",
            json={
                "tool_name": tool_name,
                "args": args,
                "timeout_ms": 30000,
            },
            timeout=35.0,
        )
        if resp.status_code == 200:
            data = resp.json()
            status = data.get("status", "unknown")
            result = data.get("result", {})

            if status == "executed":
                if isinstance(result, dict):
                    return json.dumps(result, indent=2, default=str)
                return str(result)
            elif status == "policy_denied":
                msg = data.get("message", "Policy denied execution")
                return f"[Policy Denied] {msg}"
            elif status == "requires_approval":
                action_id = data.get("action_id", "?")
                return (
                    f"[Approval Required] This tool requires explicit approval.\n"
                    f"Action ID: {action_id}\n"
                    f"Approve: POST {OPENCLAW_URL}/actions/{action_id}/approve"
                )
            elif status == "not_implemented":
                return f"[Not Implemented] Tool {tool_name} is registered but not yet implemented."
            else:
                return f"[{status}] {data.get('message', json.dumps(result, default=str))}"
        else:
            return f"[OpenClaw error {resp.status_code}]: {resp.text[:500]}"
    except httpx.ConnectError:
        return f"[Error] Cannot reach OpenClaw at {OPENCLAW_URL}"
    except Exception as e:
        return f"[Error] {type(e).__name__}: {e}"


# ---------------------------------------------------------------------------
# MCP Server
# ---------------------------------------------------------------------------

mcp = FastMCP(
    "sonia",
    instructions=(
        "SONIA is a local AI companion running on the user's machine. "
        "Use sonia_chat to have a conversation with Sonia. "
        "Use openclaw_execute to run system tools (file operations, process management, shell commands). "
        "Use sonia_memory_search to query Sonia's long-term memory. "
        "Use sonia_memory_store to save new information."
    ),
)


# ---------------------------------------------------------------------------
# Tool: sonia_chat
# ---------------------------------------------------------------------------

@mcp.tool()
async def sonia_chat(message: str, user_id: str = "mcp_user") -> str:
    """Send a message to Sonia and get her response.

    This routes through the full SONIA turn pipeline:
    memory recall -> model inference -> tool execution -> memory write.

    Args:
        message: The text message to send to Sonia.
        user_id: Optional user identifier (default: mcp_user).
    """
    client = _get_http()
    try:
        resp = await client.post(
            f"{GATEWAY_URL}/v1/turn",
            json={
                "input_text": message,
                "user_id": user_id,
            },
            timeout=60.0,
        )
        if resp.status_code == 200:
            data = resp.json()
            text = data.get("assistant_text", "")
            turn_id = data.get("turn_id", "?")
            duration = data.get("duration_ms", 0)
            ok = data.get("ok", False)
            if ok and text:
                return f"{text}\n\n[turn_id={turn_id}, {duration:.0f}ms]"
            elif not ok:
                err = data.get("error", {})
                return f"[Error] {err.get('code', 'UNKNOWN')}: {err.get('message', 'No details')}"
            else:
                return "[Sonia returned an empty response]"
        else:
            return f"[Gateway error {resp.status_code}]: {resp.text[:500]}"
    except httpx.ConnectError:
        return "[Error] Cannot reach SONIA API Gateway at " + GATEWAY_URL
    except Exception as e:
        return f"[Error] {type(e).__name__}: {e}"


# ---------------------------------------------------------------------------
# Tool: sonia_memory_search
# ---------------------------------------------------------------------------

@mcp.tool()
async def sonia_memory_search(query: str, limit: int = 10) -> str:
    """Search Sonia's long-term memory for relevant information.

    Returns memory entries matching the query, ranked by relevance.

    Args:
        query: Search query text.
        limit: Maximum number of results (default 10, max 50).
    """
    client = _get_http()
    limit = min(max(1, limit), 50)
    try:
        resp = await client.post(
            f"{MEMORY_URL}/search",
            json={"query": query, "limit": limit},
            timeout=10.0,
        )
        if resp.status_code == 200:
            data = resp.json()
            results = data.get("results", [])
            if not results:
                return f"No memories found for: {query}"
            parts = [f"Found {len(results)} memory entries:\n"]
            for i, r in enumerate(results, 1):
                content = r.get("content", "")[:300]
                mem_type = r.get("type", "?")
                score = r.get("score", 0)
                parts.append(f"{i}. [{mem_type}] (score={score:.2f}) {content}")
            return "\n".join(parts)
        else:
            return f"[Memory search error {resp.status_code}]: {resp.text[:300]}"
    except httpx.ConnectError:
        return "[Error] Cannot reach Memory Engine at " + MEMORY_URL
    except Exception as e:
        return f"[Error] {type(e).__name__}: {e}"


# ---------------------------------------------------------------------------
# Tool: sonia_memory_store
# ---------------------------------------------------------------------------

@mcp.tool()
async def sonia_memory_store(
    content: str,
    memory_type: str = "fact",
    tag: str = "",
) -> str:
    """Store a new memory in Sonia's long-term memory.

    Args:
        content: The text content to store.
        memory_type: Memory type (fact, preference, project_state, stable_constraint).
        tag: Optional tag for grouping.
    """
    client = _get_http()
    payload: Dict[str, Any] = {
        "type": memory_type,
        "content": content,
    }
    if tag:
        payload["metadata"] = {"tag": tag}

    try:
        resp = await client.post(
            f"{MEMORY_URL}/store",
            json=payload,
            timeout=10.0,
        )
        if resp.status_code == 200:
            data = resp.json()
            mem_id = data.get("id", "?")
            return f"Stored memory: {mem_id} (type={memory_type})"
        else:
            return f"[Store error {resp.status_code}]: {resp.text[:300]}"
    except httpx.ConnectError:
        return "[Error] Cannot reach Memory Engine at " + MEMORY_URL
    except Exception as e:
        return f"[Error] {type(e).__name__}: {e}"


# ---------------------------------------------------------------------------
# Tool: sonia_service_health
# ---------------------------------------------------------------------------

@mcp.tool()
async def sonia_service_health() -> str:
    """Check the health of all SONIA services.

    Returns status of each microservice (api-gateway, model-router,
    memory-engine, pipecat, openclaw, eva-os, vision-capture, perception).
    """
    client = _get_http()
    services = [
        ("API Gateway", GATEWAY_URL),
        ("Model Router", MODEL_ROUTER_URL),
        ("Memory Engine", MEMORY_URL),
        ("Pipecat", "http://127.0.0.1:7030"),
        ("OpenClaw", OPENCLAW_URL),
        ("EVA-OS", "http://127.0.0.1:7050"),
        ("Vision Capture", "http://127.0.0.1:7060"),
        ("Perception", "http://127.0.0.1:7070"),
    ]

    lines = ["SONIA Service Health:\n"]
    for name, url in services:
        try:
            resp = await client.get(f"{url}/healthz", timeout=3.0)
            if resp.status_code == 200:
                data = resp.json()
                ok = data.get("ok", False)
                lines.append(f"  [{'OK' if ok else 'DEGRADED'}] {name} ({url})")
            else:
                lines.append(f"  [WARN] {name} ({url}) -- HTTP {resp.status_code}")
        except httpx.ConnectError:
            lines.append(f"  [DOWN] {name} ({url}) -- not reachable")
        except Exception as e:
            lines.append(f"  [ERR] {name} ({url}) -- {e}")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Tool: openclaw_execute (unified OpenClaw gateway)
# ---------------------------------------------------------------------------

@mcp.tool()
async def openclaw_execute(tool_name: str, arguments_json: str = "{}") -> str:
    """Execute any tool from the OpenClaw tool catalog.

    Available tools and their arguments:

    TIER 0 - Read Only (no approval needed):
      - filesystem.list_directory: {path: str, recursive?: bool}
      - filesystem.read_file: {path: str, encoding?: str}
      - filesystem.stat: {path: str}
      - process.list: {filter_name?: str}
      - http.get: {url: str, timeout_seconds?: int}
      - web.search: {query: str, max_results?: int}
      - web.fetch: {url: str, max_chars?: int}

    TIER 1 - Low Risk:
      - filesystem.create_directory: {path: str, recursive?: bool}
      - filesystem.write_file: {path: str, content: str, encoding?: str, mode?: "write"|"append"}
      - filesystem.append_file: {path: str, content: str}
      - notification.send: {title: str, body?: str}

    TIER 2 - Medium Risk:
      - filesystem.move: {source: str, destination: str}
      - filesystem.copy: {source: str, destination: str, recursive?: bool}
      - process.start: {command: str, args?: str[], working_directory?: str}
      - process.stop: {pid: int, timeout_seconds?: int}
      - shell.run_powershell_script: {script: str, timeout_seconds?: int}

    TIER 3 - Destructive (requires approval):
      - filesystem.delete: {path: str, recursive?: bool, move_to_trash?: bool}
      - process.kill: {pid: int}
      - shell.run_command: {command: str, timeout_seconds?: int}

    Args:
        tool_name: The OpenClaw tool name (e.g., 'filesystem.read_file').
        arguments_json: JSON string of tool arguments (e.g., '{"path": "S:\\\\config"}').
    """
    try:
        args = json.loads(arguments_json) if arguments_json else {}
    except json.JSONDecodeError as e:
        return f"[Error] Invalid JSON in arguments_json: {e}"

    return await _execute_openclaw(tool_name, args)


# ---------------------------------------------------------------------------
# Tool: openclaw_list_tools
# ---------------------------------------------------------------------------

@mcp.tool()
async def openclaw_list_tools() -> str:
    """List all available tools in the OpenClaw catalog with their tiers and descriptions."""
    client = _get_http()
    try:
        resp = await client.get(f"{OPENCLAW_URL}/tools", timeout=5.0)
        if resp.status_code == 200:
            data = resp.json()
            tools = data.get("tools", [])
            if not tools:
                return "No tools registered in OpenClaw."
            lines = [f"OpenClaw Tools ({len(tools)} registered):\n"]
            for t in tools:
                name = t.get("name", "?")
                desc = t.get("description", "")
                tier = t.get("tier", "?")
                lines.append(f"  [{tier}] {name}: {desc}")
            return "\n".join(lines)
        else:
            return f"[Error {resp.status_code}]: {resp.text[:300]}"
    except httpx.ConnectError:
        # Fall back to local catalog
        catalog = _load_tool_catalog()
        tools = catalog.get("tools", {})
        if not tools:
            return "No tools found (OpenClaw not reachable, local catalog empty)."
        lines = [f"OpenClaw Tools ({len(tools)} in local catalog):\n"]
        for name, tdef in tools.items():
            tier = tdef.get("tier", "?")
            desc = tdef.get("description", "")
            lines.append(f"  [{tier}] {name}: {desc}")
        return "\n".join(lines)
    except Exception as e:
        return f"[Error] {type(e).__name__}: {e}"


# ---------------------------------------------------------------------------
# Resources
# ---------------------------------------------------------------------------

@mcp.resource("memory://stats")
async def memory_stats() -> str:
    """Memory-engine statistics including total memories, types, and search index info."""
    client = _get_http()
    try:
        resp = await client.get(f"{MEMORY_URL}/query/stats", timeout=5.0)
        if resp.status_code == 200:
            return json.dumps(resp.json(), indent=2)
        return f"Error fetching stats: HTTP {resp.status_code}"
    except Exception as e:
        return f"Error: {e}"


@mcp.resource("health://services")
async def health_overview() -> str:
    """Aggregated health status of all SONIA services."""
    return await sonia_service_health()


@mcp.resource("config://sonia")
async def sonia_config_resource() -> str:
    """Current SONIA configuration (read-only view, secrets redacted)."""
    config = _load_config()
    safe = json.dumps(config, indent=2, default=str)
    for key_pattern in ["api_key", "secret", "token", "password"]:
        safe = re.sub(
            rf'("{key_pattern}[^"]*":\s*)"[^"]*"',
            rf'\1"***REDACTED***"',
            safe,
            flags=re.IGNORECASE,
        )
    return safe


@mcp.resource("tools://catalog")
async def tool_catalog_resource() -> str:
    """Full OpenClaw tool catalog with schemas and safety tiers."""
    catalog = _load_tool_catalog()
    return json.dumps(catalog, indent=2, default=str)


# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------

@mcp.prompt()
def chat_with_sonia(topic: str = "") -> str:
    """Start a conversation with Sonia about a specific topic.

    Args:
        topic: What you want to talk about with Sonia.
    """
    if topic:
        return (
            f"Use the sonia_chat tool to have a conversation with Sonia about: {topic}\n\n"
            f"Sonia is a local AI companion with access to memory and tools. "
            f"She can recall previous conversations and take actions on your behalf."
        )
    return (
        "Use the sonia_chat tool to greet Sonia and start a conversation.\n\n"
        "Sonia is a local AI companion with access to memory and tools. "
        "She can recall previous conversations and take actions on your behalf."
    )


@mcp.prompt()
def system_check() -> str:
    """Run a comprehensive SONIA system health check."""
    return (
        "Please run a comprehensive SONIA system check:\n\n"
        "1. Use sonia_service_health to check all services\n"
        "2. Use sonia_memory_search with query 'status' to verify memory is working\n"
        "3. Use openclaw_list_tools to check available tools\n"
        "4. Read the memory://stats resource for memory statistics\n\n"
        "Report the results in a clear summary."
    )


# ---------------------------------------------------------------------------
# Startup
# ---------------------------------------------------------------------------

logger.info("SONIA MCP Server initialized")


def main():
    """Entry point."""
    import argparse

    parser = argparse.ArgumentParser(description="SONIA MCP Server")
    parser.add_argument("--sse", action="store_true", help="Use SSE transport instead of stdio")
    parser.add_argument("--port", type=int, default=8080, help="Port for SSE transport")
    args = parser.parse_args()

    if args.sse:
        logger.info("Starting SONIA MCP Server (SSE on port %d)", args.port)
        mcp.run(transport="sse")
    else:
        logger.info("Starting SONIA MCP Server (stdio)")
        mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
