"""
Test Suite: Fallback Matrix (FM1-FM10)
Validates ordered failover behaviour.
"""

import sys
sys.path.insert(0, r"S:\services\model-router")

passed = failed = 0

def check(tag, cond, msg=""):
    global passed, failed
    if cond:
        passed += 1
        print(f"  [PASS] {tag}: {msg}")
    else:
        failed += 1
        print(f"  [FAIL] {tag}: {msg}")


from app.profiles import ProfileName, ReasonCode, RoutingProfile, ProfileRegistry
from app.routing_engine import RoutingEngine

print("=" * 60)
print("Test Suite: Fallback Matrix (FM1-FM10)")
print("=" * 60)

print("\n--- FM1: Full chain walked when primary down ---")
# chat_low_latency: prefs=[ollama/qwen2:7b], fallbacks=[ollama/qwen2:1.5b]
engine = RoutingEngine(is_healthy=lambda b: "1.5b" in b)
dec = engine.select(ProfileName.CHAT_LOW_LATENCY, trace_id="fm1")
check("FM1a", dec.selected_backend == "ollama/qwen2:1.5b", f"got={dec.selected_backend}")
check("FM1b", len(dec.skipped) == 1, f"skipped={len(dec.skipped)}")
check("FM1c", dec.skipped[0]["backend"] == "ollama/qwen2:7b", "primary skipped")

print("\n--- FM2: Fallback order preserved ---")
# reasoning_deep: prefs=[opus, sonnet], fallbacks=[qwen2:7b]
skip_order = []
def track_health(backend):
    skip_order.append(backend)
    return False
engine2 = RoutingEngine(is_healthy=track_health)
engine2.select(ProfileName.REASONING_DEEP, trace_id="fm2")
expected_order = ["anthropic/claude-opus-4-6", "anthropic/claude-sonnet-4-6", "ollama/qwen2:7b"]
check("FM2a", skip_order == expected_order, f"order={skip_order}")

print("\n--- FM3: No fallback when primary healthy ---")
engine3 = RoutingEngine()
dec = engine3.select(ProfileName.CHAT_LOW_LATENCY, trace_id="fm3")
check("FM3a", dec.selected_backend == "ollama/qwen2:7b", "primary selected")
check("FM3b", dec.skipped == [], "no skips")
check("FM3c", dec.reason_code == "PROFILE_MATCH", "match reason")

print("\n--- FM4: Multiple skips logged ---")
# tool_execution: prefs=[qwen2:7b, sonnet], fallbacks=[qwen2:1.5b]
engine4 = RoutingEngine(is_healthy=lambda b: "1.5b" in b)
dec = engine4.select(ProfileName.TOOL_EXECUTION, trace_id="fm4")
check("FM4a", dec.selected_backend == "ollama/qwen2:1.5b", f"got={dec.selected_backend}")
check("FM4b", len(dec.skipped) == 2, f"skipped={len(dec.skipped)}")

print("\n--- FM5: Consistent fallback across repeated runs ---")
engine5 = RoutingEngine(is_healthy=lambda b: "sonnet" in b)
results = [engine5.select(ProfileName.REASONING_DEEP, trace_id=f"fm5_{i}").selected_backend
           for i in range(20)]
check("FM5a", len(set(results)) == 1, f"consistent: {set(results)}")
check("FM5b", results[0] == "anthropic/claude-sonnet-4-6", "sonnet selected")

print("\n--- FM6: safe_fallback has no external fallbacks ---")
reg = ProfileRegistry()
safe = reg.get(ProfileName.SAFE_FALLBACK)
check("FM6a", safe.fallbacks == [], "no fallbacks defined")
check("FM6b", len(safe.model_prefs) == 2, "2 local models")

print("\n--- FM7: Budget-based fallback ---")
from app.budget_guard import BudgetGuard
bg = BudgetGuard()
bg.register_backend("anthropic/claude-opus-4-6", max_context=200000, avg_latency_ms=5000)
bg.register_backend("anthropic/claude-sonnet-4-6", max_context=200000, avg_latency_ms=1500)
bg.register_backend("ollama/qwen2:7b", max_context=4096, avg_latency_ms=800)
# reasoning_deep has latency_ms=30000 so all pass latency, but budget check context
engine6 = RoutingEngine(check_budget=bg.check)
dec = engine6.select(ProfileName.REASONING_DEEP, trace_id="fm7")
check("FM7a", dec.selected_backend == "anthropic/claude-opus-4-6", f"got={dec.selected_backend}")
check("FM7b", dec.reason_code == "PROFILE_MATCH", "direct match")

print("\n--- FM8: Budget + health combined ---")
from app.health_registry import HealthRegistry
hr = HealthRegistry(failure_threshold=1, quarantine_s=60)
hr.record_failure("anthropic/claude-opus-4-6", "down")
engine7 = RoutingEngine(is_healthy=hr.is_healthy, check_budget=bg.check)
dec = engine7.select(ProfileName.REASONING_DEEP, trace_id="fm8")
check("FM8a", dec.selected_backend == "anthropic/claude-sonnet-4-6", f"got={dec.selected_backend}")
check("FM8b", dec.reason_code == "PROFILE_MATCH", f"reason={dec.reason_code} (sonnet is in model_prefs)")
check("FM8c", any(s["reason"] == "BACKEND_UNHEALTHY" for s in dec.skipped), "health skip logged")

print("\n--- FM9: Skipped reasons are accurate ---")
for skip in dec.skipped:
    check(f"FM9_{skip['backend'][:10]}", skip["reason"] in [r.value for r in ReasonCode],
          f"{skip['backend']} -> {skip['reason']}")

print("\n--- FM10: Config-defined fallback matrix preserved ---")
import json
with open(r"S:\config\sonia-config.json", "r") as f:
    cfg = json.load(f)
fm = cfg["model_router"]["profiles"]["fallback_matrix"]
check("FM10a", fm["chat_low_latency"] == ["ollama/qwen2:7b", "ollama/qwen2:1.5b"], "chat matrix")
check("FM10b", fm["reasoning_deep"][0] == "anthropic/claude-opus-4-6", "reasoning primary")
check("FM10c", len(fm) == 6, "6 profiles in matrix")

print("\n" + "=" * 60)
total = passed + failed
print(f"Results: {passed}/{total} passed")
if failed:
    print("SOME TESTS FAILED")
    sys.exit(1)
else:
    print("ALL TESTS PASSED")
