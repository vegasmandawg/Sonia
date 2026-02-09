"""
Test Suite: Health Quarantine (HQ1-HQ12)
Validates quarantine and recovery logic.
"""

import sys, time
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


from app.health_registry import HealthRegistry, BackendState
from app.routing_engine import RoutingEngine
from app.profiles import ProfileName

print("=" * 60)
print("Test Suite: Health Quarantine (HQ1-HQ12)")
print("=" * 60)

print("\n--- HQ1: Fresh backend is healthy ---")
hr = HealthRegistry()
check("HQ1a", hr.is_healthy("new-backend"), "unknown is healthy")
check("HQ1b", hr.get_state("new-backend") == BackendState.UNKNOWN, "state=unknown")

print("\n--- HQ2: Success transitions to healthy ---")
hr.record_success("b1")
check("HQ2a", hr.get_state("b1") == BackendState.HEALTHY, "healthy after success")

print("\n--- HQ3: Sub-threshold failures stay healthy ---")
hr2 = HealthRegistry(failure_threshold=3)
hr2.record_failure("b2", "err1")
hr2.record_failure("b2", "err2")
check("HQ3a", hr2.is_healthy("b2"), "2 < 3 threshold")

print("\n--- HQ4: Threshold breach triggers quarantine ---")
hr2.record_failure("b2", "err3")
check("HQ4a", hr2.get_state("b2") == BackendState.QUARANTINED, "quarantined")
check("HQ4b", not hr2.is_healthy("b2"), "unhealthy during quarantine")

print("\n--- HQ5: Quarantined backends in list ---")
q = hr2.quarantined_backends()
check("HQ5a", "b2" in q, "in quarantine list")

print("\n--- HQ6: Quarantine auto-expires ---")
hr3 = HealthRegistry(failure_threshold=2, quarantine_s=0.05)
hr3.record_failure("b3", "e1")
hr3.record_failure("b3", "e2")
check("HQ6a", not hr3.is_healthy("b3"), "quarantined")
time.sleep(0.06)
check("HQ6b", hr3.is_healthy("b3"), "healthy after expiry")
check("HQ6c", hr3.get_state("b3") == BackendState.DEGRADED, "degraded state")

print("\n--- HQ7: Recovery probes required ---")
hr4 = HealthRegistry(failure_threshold=2, quarantine_s=0.01, recovery_probes=3)
hr4.record_failure("b4", "e1")
hr4.record_failure("b4", "e2")
time.sleep(0.02)
hr4.is_healthy("b4")  # trigger degraded
hr4.record_success("b4")
check("HQ7a", hr4.get_state("b4") != BackendState.HEALTHY, "1 probe not enough")
hr4.record_success("b4")
check("HQ7b", hr4.get_state("b4") != BackendState.HEALTHY, "2 probes not enough")
hr4.record_success("b4")
check("HQ7c", hr4.get_state("b4") == BackendState.HEALTHY, "3 probes -> healthy")

print("\n--- HQ8: Failure resets consecutive successes ---")
hr5 = HealthRegistry(failure_threshold=5)
hr5.record_success("b5")
hr5.record_success("b5")
hr5.record_failure("b5", "e")
h = hr5.all_health()
check("HQ8a", h["b5"]["consecutive_successes"] == 0, "reset")

print("\n--- HQ9: Rolling window expires old failures ---")
hr6 = HealthRegistry(failure_threshold=3, failure_window_s=0.1)
hr6.record_failure("b6", "old1")
hr6.record_failure("b6", "old2")
time.sleep(0.15)
hr6.record_failure("b6", "new1")
check("HQ9a", hr6.is_healthy("b6"), "old failures expired")

print("\n--- HQ10: Quarantined backend skipped in routing ---")
hr7 = HealthRegistry(failure_threshold=2, quarantine_s=60)
hr7.record_failure("ollama/qwen2:7b", "down")
hr7.record_failure("ollama/qwen2:7b", "down")
engine = RoutingEngine(is_healthy=hr7.is_healthy)
dec = engine.select(ProfileName.CHAT_LOW_LATENCY, trace_id="hq10")
check("HQ10a", dec.selected_backend == "ollama/qwen2:1.5b", f"fallback={dec.selected_backend}")
check("HQ10b", any(s["reason"] == "BACKEND_UNHEALTHY" for s in dec.skipped), "skip logged")

print("\n--- HQ11: Thread safety under load ---")
import threading
hr8 = HealthRegistry(failure_threshold=100)
errors = []
def hammer():
    try:
        for i in range(50):
            hr8.record_success("threaded")
            hr8.record_failure("threaded", f"e{i}")
            hr8.is_healthy("threaded")
    except Exception as e:
        errors.append(str(e))

threads = [threading.Thread(target=hammer) for _ in range(4)]
for t in threads: t.start()
for t in threads: t.join()
h = hr8.all_health()["threaded"]
check("HQ11a", len(errors) == 0, "no errors")
check("HQ11b", h["total_successes"] == 200, f"successes={h['total_successes']}")
check("HQ11c", h["total_failures"] == 200, f"failures={h['total_failures']}")

print("\n--- HQ12: to_dict diagnostics ---")
d = hr7.to_dict()
check("HQ12a", "backends" in d, "backends key")
check("HQ12b", "quarantined" in d, "quarantined key")
check("HQ12c", d["config"]["failure_threshold"] == 2, "config value")

print("\n" + "=" * 60)
total = passed + failed
print(f"Results: {passed}/{total} passed")
if failed:
    print("SOME TESTS FAILED")
    sys.exit(1)
else:
    print("ALL TESTS PASSED")
