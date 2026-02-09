"""
Test Suite: Profile Selection (PS1-PS12)
Validates deterministic profile mapping and routing.
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


from app.profiles import (
    ProfileName, ReasonCode, RoutingProfile, ProfileRegistry,
    classify_request, default_profiles, RetryPolicy,
)
from app.routing_engine import RoutingEngine, RouteDecision

print("=" * 60)
print("Test Suite: Profile Selection (PS1-PS12)")
print("=" * 60)

print("\n--- PS1: classify_request determinism ---")
for _ in range(3):
    results = [classify_request(hint="analyze image") for _ in range(50)]
    unique = set(r.value for r in results)
    check("PS1a", len(unique) == 1, f"50 calls -> {unique}")

print("\n--- PS2: classify by task_type ---")
check("PS2a", classify_request(task_type="vision") == ProfileName.VISION_ANALYSIS, "vision")
check("PS2b", classify_request(task_type="text", hint="reasoning") == ProfileName.REASONING_DEEP, "reasoning wins")

print("\n--- PS3: classify by hint ---")
check("PS3a", classify_request(hint="execute tool") == ProfileName.TOOL_EXECUTION, "tool")
check("PS3b", classify_request(hint="remember this fact") == ProfileName.MEMORY_OPS, "memory")
check("PS3c", classify_request(hint="quick chat") == ProfileName.CHAT_LOW_LATENCY, "chat")

print("\n--- PS4: default classification ---")
check("PS4a", classify_request() == ProfileName.CHAT_LOW_LATENCY, "empty -> chat")
check("PS4b", classify_request(hint="xyz unknown") == ProfileName.CHAT_LOW_LATENCY, "unknown -> chat")

print("\n--- PS5: all 6 profiles in registry ---")
reg = ProfileRegistry()
check("PS5a", len(reg.names) == 6, f"{len(reg.names)} profiles")
for pn in ProfileName:
    check(f"PS5b_{pn.value}", reg.get(pn) is not None, f"{pn.value} exists")

print("\n--- PS6: profile validation ---")
good = reg.get(ProfileName.CHAT_LOW_LATENCY)
check("PS6a", good.validate() == [], "valid profile")
bad = RoutingProfile(name=ProfileName.SAFE_FALLBACK, model_prefs=[], fallbacks=[],
                     latency_ms=-1, max_context=-1)
errs = bad.validate()
check("PS6b", len(errs) >= 3, f"{len(errs)} errors")

print("\n--- PS7: dispatch_chain dedup ---")
p = RoutingProfile(name=ProfileName.TOOL_EXECUTION,
                   model_prefs=["a", "b"], fallbacks=["b", "c", "a"])
chain = p.dispatch_chain()
check("PS7a", chain == ["a", "b", "c"], f"deduped: {chain}")

print("\n--- PS8: routing engine selects first healthy ---")
engine = RoutingEngine()
dec1 = engine.select(ProfileName.CHAT_LOW_LATENCY, trace_id="ps8")
dec2 = engine.select(ProfileName.CHAT_LOW_LATENCY, trace_id="ps8b")
check("PS8a", dec1.selected_backend == dec2.selected_backend, "same backend twice")
check("PS8b", dec1.reason_code == "PROFILE_MATCH", f"reason={dec1.reason_code}")

print("\n--- PS9: routing engine with unhealthy primary ---")
engine2 = RoutingEngine(is_healthy=lambda b: "1.5b" in b)
dec = engine2.select(ProfileName.CHAT_LOW_LATENCY, trace_id="ps9")
check("PS9a", dec.selected_backend == "ollama/qwen2:1.5b", f"fallback={dec.selected_backend}")
check("PS9b", dec.reason_code == "FALLBACK_USED", f"reason={dec.reason_code}")

print("\n--- PS10: routing engine all unhealthy ---")
engine3 = RoutingEngine(is_healthy=lambda b: False)
dec = engine3.select(ProfileName.REASONING_DEEP, trace_id="ps10")
check("PS10a", dec.selected_backend is None, "no backend")
check("PS10b", dec.reason_code == "NO_BACKEND_AVAILABLE", f"reason={dec.reason_code}")

print("\n--- PS11: route_request end-to-end ---")
engine4 = RoutingEngine()
dec = engine4.route_request(task_type="vision", hint="screenshot", trace_id="ps11")
check("PS11a", dec.profile_name == "vision_analysis", f"profile={dec.profile_name}")
check("PS11b", dec.selected_backend is not None, f"backend={dec.selected_backend}")

print("\n--- PS12: RouteDecision serialisation ---")
d = dec.to_dict()
check("PS12a", "trace_id" in d, "trace_id")
check("PS12b", "fallback_chain" in d, "fallback_chain")
check("PS12c", "reason_code" in d, "reason_code")
check("PS12d", "skipped" in d, "skipped")

print("\n" + "=" * 60)
total = passed + failed
print(f"Results: {passed}/{total} passed")
if failed:
    print("SOME TESTS FAILED")
    sys.exit(1)
else:
    print("ALL TESTS PASSED")
