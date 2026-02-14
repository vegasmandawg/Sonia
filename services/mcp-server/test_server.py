"""
Test SONIA MCP Server

Validates that the server starts, registers tools, and responds to
MCP protocol messages correctly. Uses stdin/stdout JSON-RPC.

Usage:
    python test_server.py
"""

import json
import subprocess
import sys
import threading
import time

PYTHON = r"S:\envs\sonia-core\python.exe"
SERVER = r"S:\services\mcp-server\server.py"

# Force UTF-8 on Windows
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def send_jsonrpc(proc, method, params=None, msg_id=1):
    """Send a JSON-RPC message."""
    msg = {"jsonrpc": "2.0", "id": msg_id, "method": method}
    if params is not None:
        msg["params"] = params
    line = json.dumps(msg) + "\n"
    proc.stdin.write(line)
    proc.stdin.flush()


def send_notification(proc, method, params=None):
    """Send a JSON-RPC notification (no id)."""
    msg = {"jsonrpc": "2.0", "method": method}
    if params is not None:
        msg["params"] = params
    line = json.dumps(msg) + "\n"
    proc.stdin.write(line)
    proc.stdin.flush()


def read_response(proc, timeout=10.0):
    """Read a JSON-RPC response line."""
    result = [None]
    error = [None]

    def _read():
        try:
            line = proc.stdout.readline()
            if line:
                result[0] = json.loads(line.strip())
        except Exception as e:
            error[0] = str(e)

    t = threading.Thread(target=_read, daemon=True)
    t.start()
    t.join(timeout=timeout)

    if t.is_alive():
        return {"error": "timeout"}
    if error[0]:
        return {"error": error[0]}
    return result[0]


def main():
    passed = 0
    failed = 0
    total = 0

    print("=" * 60)
    print("SONIA MCP Server Test Suite")
    print("=" * 60)
    print()

    # Start server
    print("Starting MCP server...")
    proc = subprocess.Popen(
        [PYTHON, SERVER],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
    )

    time.sleep(2)

    if proc.poll() is not None:
        stderr = proc.stderr.read()
        print(f"[FAIL] Server exited immediately")
        print(f"  stderr: {stderr[:1000]}")
        sys.exit(1)

    try:
        # T1: Initialize
        total += 1
        print("T1: Initialize handshake...", end=" ")
        send_jsonrpc(proc, "initialize", {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "test-client", "version": "1.0.0"},
        }, msg_id=1)

        resp = read_response(proc)
        if resp and "result" in resp:
            result = resp["result"]
            si = result.get("serverInfo", {})
            caps = result.get("capabilities", {})
            print(f"[OK] server={si.get('name', '?')}")
            print(f"    caps: tools={'tools' in caps}, resources={'resources' in caps}, prompts={'prompts' in caps}")
            passed += 1
        else:
            print(f"[FAIL] {resp}")
            failed += 1

        send_notification(proc, "notifications/initialized")
        time.sleep(0.5)

        # T2: tools/list
        total += 1
        print("T2: tools/list...", end=" ")
        send_jsonrpc(proc, "tools/list", {}, msg_id=2)
        resp = read_response(proc)
        if resp and "result" in resp:
            tools = resp["result"].get("tools", [])
            names = [t["name"] for t in tools]
            print(f"[OK] {len(tools)} tools")
            expected = ["sonia_chat", "sonia_memory_search", "sonia_memory_store",
                        "sonia_service_health", "openclaw_execute", "openclaw_list_tools"]
            for exp in expected:
                found = exp in names
                print(f"    {'[OK]' if found else '[MISSING]'} {exp}")
                if not found:
                    failed += 1  # count each missing as a sub-failure
            passed += 1
        else:
            print(f"[FAIL] {resp}")
            failed += 1

        # T3: resources/list
        total += 1
        print("T3: resources/list...", end=" ")
        send_jsonrpc(proc, "resources/list", {}, msg_id=3)
        resp = read_response(proc)
        if resp and "result" in resp:
            resources = resp["result"].get("resources", [])
            print(f"[OK] {len(resources)} resources")
            for r in resources:
                print(f"    {r.get('uri', '?')}")
            passed += 1
        else:
            print(f"[FAIL] {resp}")
            failed += 1

        # T4: prompts/list
        total += 1
        print("T4: prompts/list...", end=" ")
        send_jsonrpc(proc, "prompts/list", {}, msg_id=4)
        resp = read_response(proc)
        if resp and "result" in resp:
            prompts = resp["result"].get("prompts", [])
            print(f"[OK] {len(prompts)} prompts")
            for p in prompts:
                print(f"    {p.get('name', '?')}")
            passed += 1
        else:
            print(f"[FAIL] {resp}")
            failed += 1

        # T5: Call sonia_service_health
        total += 1
        print("T5: tools/call sonia_service_health...", end=" ")
        send_jsonrpc(proc, "tools/call", {
            "name": "sonia_service_health",
            "arguments": {},
        }, msg_id=5)
        resp = read_response(proc, timeout=30.0)
        if resp and "result" in resp:
            content = resp["result"].get("content", [])
            if content:
                text = content[0].get("text", "")
                if "SONIA" in text or "Gateway" in text or "DOWN" in text:
                    print(f"[OK] ({len(text)} chars)")
                    for line in text.split("\n")[:4]:
                        print(f"    {line}")
                    passed += 1
                else:
                    print(f"[FAIL] unexpected: {text[:200]}")
                    failed += 1
            else:
                print(f"[FAIL] no content")
                failed += 1
        elif resp and "error" in resp and resp["error"] == "timeout":
            print("[FAIL] timeout")
            failed += 1
        else:
            print(f"[FAIL] {resp}")
            failed += 1

        # T6: Call openclaw_list_tools (falls back to local catalog)
        total += 1
        print("T6: tools/call openclaw_list_tools...", end=" ")
        send_jsonrpc(proc, "tools/call", {
            "name": "openclaw_list_tools",
            "arguments": {},
        }, msg_id=6)
        resp = read_response(proc, timeout=15.0)
        if resp and "result" in resp:
            content = resp["result"].get("content", [])
            if content:
                text = content[0].get("text", "")
                if "OpenClaw Tools" in text or "filesystem" in text:
                    print(f"[OK] ({len(text)} chars)")
                    for line in text.split("\n")[:4]:
                        print(f"    {line}")
                    passed += 1
                else:
                    print(f"[FAIL] unexpected: {text[:200]}")
                    failed += 1
            else:
                print(f"[FAIL] no content")
                failed += 1
        else:
            print(f"[FAIL] {resp}")
            failed += 1

        # T7: Read config://sonia resource
        total += 1
        print("T7: resources/read config://sonia...", end=" ")
        send_jsonrpc(proc, "resources/read", {
            "uri": "config://sonia",
        }, msg_id=7)
        resp = read_response(proc, timeout=10.0)
        if resp and "result" in resp:
            contents = resp["result"].get("contents", [])
            if contents:
                text = contents[0].get("text", "")
                if "sonia_version" in text or "services" in text:
                    print(f"[OK] config loaded ({len(text)} chars)")
                    passed += 1
                else:
                    print(f"[FAIL] unexpected: {text[:200]}")
                    failed += 1
            else:
                print(f"[FAIL] no contents")
                failed += 1
        else:
            print(f"[FAIL] {resp}")
            failed += 1

        # T8: Read tools://catalog resource
        total += 1
        print("T8: resources/read tools://catalog...", end=" ")
        send_jsonrpc(proc, "resources/read", {
            "uri": "tools://catalog",
        }, msg_id=8)
        resp = read_response(proc, timeout=10.0)
        if resp and "result" in resp:
            contents = resp["result"].get("contents", [])
            if contents:
                text = contents[0].get("text", "")
                if "catalog_version" in text or "filesystem" in text:
                    print(f"[OK] catalog loaded ({len(text)} chars)")
                    passed += 1
                else:
                    print(f"[FAIL] unexpected: {text[:200]}")
                    failed += 1
            else:
                print(f"[FAIL] no contents")
                failed += 1
        else:
            print(f"[FAIL] {resp}")
            failed += 1

        # T9: Get prompt
        total += 1
        print("T9: prompts/get system_check...", end=" ")
        send_jsonrpc(proc, "prompts/get", {
            "name": "system_check",
            "arguments": {},
        }, msg_id=9)
        resp = read_response(proc, timeout=5.0)
        if resp and "result" in resp:
            messages = resp["result"].get("messages", [])
            if messages:
                print(f"[OK] {len(messages)} message(s)")
                passed += 1
            else:
                print(f"[FAIL] no messages")
                failed += 1
        else:
            print(f"[FAIL] {resp}")
            failed += 1

    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()

        stderr = proc.stderr.read()
        if "Traceback" in stderr or "Error" in stderr.split("\n")[-1] if stderr else False:
            print()
            print("Server stderr (errors):")
            for line in stderr.split("\n")[-20:]:
                if line.strip():
                    print(f"  {line}")

    print()
    print("-" * 60)
    print(f"Results: {passed}/{total} passed, {failed} failed")
    if failed == 0:
        print("[ALL TESTS PASSED]")
    else:
        print(f"[{failed} TESTS FAILED]")
    print("-" * 60)

    sys.exit(0 if failed == 0 else 1)


if __name__ == "__main__":
    main()
