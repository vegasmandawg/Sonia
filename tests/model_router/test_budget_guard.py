"""
Test Suite: Budget Guard (BG1-BG10)
Validates budget enforcement.
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


from app.profiles import ProfileName, ReasonCode, RoutingProfile
from app.budget_guard import BudgetGuard, BackendCapacity
from app.routing_engine import RoutingEngine

print("=" * 60)
print("Test Suite: Budget Guard (BG1-BG10)")
print("=" * 60)

print("\n--- BG1: Unknown backend passes ---")
bg = BudgetGuard()
profile = RoutingProfile(name=ProfileName.CHAT_LOW_LATENCY, model_prefs=["x"],
                         max_context=4000, latency_ms=3000)
check("BG1a", bg.check("unknown", profile) is None, "unknown allowed")

print("\n--- BG2: Context within limit ---")
bg.register_backend("ok", max_context=8000, avg_latency_ms=500)
check("BG2a", bg.check("ok", profile) is None, "within budget")

print("\n--- BG3: Context exceeded ---")
bg.register_backend("small", max_context=2000, avg_latency_ms=500)
check("BG3a", bg.check("small", profile) == ReasonCode.BUDGET_EXCEEDED_CONTEXT, "context exceeded")

print("\n--- BG4: Latency exceeded ---")
bg.register_backend("slow", max_context=8000, avg_latency_ms=5000)
check("BG4a", bg.check("slow", profile) == ReasonCode.BUDGET_EXCEEDED_LATENCY, "latency exceeded")

print("\n--- BG5: Both exceeded - context first ---")
bg.register_backend("both", max_context=1000, avg_latency_ms=9000)
check("BG5a", bg.check("both", profile) == ReasonCode.BUDGET_EXCEEDED_CONTEXT, "context first")

print("\n--- BG6: EWMA latency update ---")
bg.register_backend("ewma", max_context=8000, avg_latency_ms=1000)
bg.update_latency("ewma", 4000)
cap = bg._capacities["ewma"]
expected = 0.3 * 4000 + 0.7 * 1000  # 1900
check("BG6a", abs(cap.avg_latency_ms - expected) < 1, f"ewma={cap.avg_latency_ms}")
bg.update_latency("ewma", 4000)
expected2 = 0.3 * 4000 + 0.7 * expected  # 2530
check("BG6b", abs(cap.avg_latency_ms - expected2) < 1, f"ewma2={cap.avg_latency_ms}")

print("\n--- BG7: Rejection log ---")
rejections = bg.recent_rejections
check("BG7a", len(rejections) >= 3, f"{len(rejections)} logged")
check("BG7b", all("reason" in r for r in rejections), "all have reason")

print("\n--- BG8: Integration - budget skips in route ---")
bg2 = BudgetGuard()
bg2.register_backend("ollama/qwen2:7b", max_context=4096, avg_latency_ms=800)
bg2.register_backend("ollama/qwen2:1.5b", max_context=2048, avg_latency_ms=300)
# chat_low_latency wants max_context=4000, qwen2:7b has 4096 (pass), qwen2:1.5b has 2048 (fail)
engine = RoutingEngine(check_budget=bg2.check)
dec = engine.select(ProfileName.CHAT_LOW_LATENCY, trace_id="bg8")
check("BG8a", dec.selected_backend == "ollama/qwen2:7b", f"got={dec.selected_backend}")

print("\n--- BG9: Exact boundary ---")
bg3 = BudgetGuard()
bg3.register_backend("exact", max_context=4000, avg_latency_ms=3000)
# Profile wants max_context=4000, latency=3000 -> exactly at boundary (not exceeded)
check("BG9a", bg3.check("exact", profile) is None, "exact boundary passes")

print("\n--- BG10: to_dict ---")
d = bg.to_dict()
check("BG10a", "capacities" in d, "capacities key")
check("BG10b", len(d["capacities"]) >= 4, f"backends={len(d['capacities'])}")

print("\n" + "=" * 60)
total = passed + failed
print(f"Results: {passed}/{total} passed")
if failed:
    print("SOME TESTS FAILED")
    sys.exit(1)
else:
    print("ALL TESTS PASSED")
