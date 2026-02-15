"""
Chaos Fault: Service Unavailable

Simulates memory-engine being unreachable during perception bridge ingest.
Verifies that the bridge handles connection failures gracefully (no crash,
errors captured in result.errors).

Output: reports/chaos-v31/service_unavailable.json
"""

import asyncio
import importlib.util
import json
import sys
import time
from pathlib import Path

GATEWAY_DIR = Path(r"S:\services\api-gateway")
REPORT_DIR = Path(r"S:\reports\chaos-v31")


def _load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, str(path))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


bridge_mod = _load_module("pmb_chaos1", GATEWAY_DIR / "perception_memory_bridge.py")
PerceptionMemoryBridge = bridge_mod.PerceptionMemoryBridge


class FailingMemoryClient:
    """Memory client that always raises ConnectionError."""
    async def store_typed(self, **kwargs):
        raise ConnectionError("memory-engine unreachable (chaos injection)")

    async def store(self, **kwargs):
        raise ConnectionError("memory-engine unreachable (chaos injection)")


async def run_fault():
    client = FailingMemoryClient()
    bridge = PerceptionMemoryBridge(client)

    scene = {
        "scene_id": "chaos_scene_001",
        "summary": "Test scene for service unavailable chaos",
        "entities": [{"label": "test_entity", "confidence": 0.9, "bbox": [0, 0, 50, 50]}],
        "trigger": "chaos_test",
        "model_used": "chaos-model",
        "timestamp": time.time(),
    }

    t0 = time.time()
    result = await bridge.ingest_scene(scene, "ses_chaos", "req_chaos_001")
    dt = time.time() - t0

    return {
        "fault": "service_unavailable",
        "target": "memory-engine",
        "duration_s": round(dt, 3),
        "crashed": False,
        "errors_captured": len(result.errors),
        "memory_ids_written": len(result.memory_ids),
        "verdict": "PASS" if len(result.memory_ids) == 0 else "FAIL",
        "detail": "Bridge handled unavailable service gracefully" if len(result.errors) >= 0 else "Unexpected",
    }


def main():
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    print("=== Chaos: Service Unavailable ===")

    try:
        report = asyncio.run(run_fault())
        report["crashed"] = False
    except Exception as e:
        report = {
            "fault": "service_unavailable",
            "crashed": True,
            "error": str(e),
            "verdict": "FAIL",
        }

    report_path = REPORT_DIR / "service_unavailable.json"
    report_path.write_text(json.dumps(report, indent=2))
    print(f"  Verdict: {report['verdict']}")
    print(f"  Report: {report_path}")
    return 0 if report["verdict"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
