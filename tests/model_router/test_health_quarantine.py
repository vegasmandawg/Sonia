"""Pytest suite for model-router health quarantine behaviour."""

import sys
import threading
import time
from pathlib import Path


MODEL_ROUTER_DIR = Path(__file__).resolve().parents[2] / "services" / "model-router"
if str(MODEL_ROUTER_DIR) not in sys.path:
    sys.path.insert(0, str(MODEL_ROUTER_DIR))

from app.health_registry import BackendState, HealthRegistry
from app.profiles import ProfileName
from app.routing_engine import RoutingEngine


def test_hq1_fresh_backend_healthy_unknown():
    hr = HealthRegistry()
    assert hr.is_healthy("new-backend")
    assert hr.get_state("new-backend") == BackendState.UNKNOWN


def test_hq2_success_transitions_to_healthy():
    hr = HealthRegistry()
    hr.record_success("b1")
    assert hr.get_state("b1") == BackendState.HEALTHY


def test_hq3_subthreshold_failures_stay_healthy():
    hr = HealthRegistry(failure_threshold=3)
    hr.record_failure("b2", "err1")
    hr.record_failure("b2", "err2")
    assert hr.is_healthy("b2")


def test_hq4_threshold_triggers_quarantine():
    hr = HealthRegistry(failure_threshold=3)
    hr.record_failure("b2", "err1")
    hr.record_failure("b2", "err2")
    hr.record_failure("b2", "err3")
    assert hr.get_state("b2") == BackendState.QUARANTINED
    assert not hr.is_healthy("b2")


def test_hq5_quarantined_backends_listed():
    hr = HealthRegistry(failure_threshold=1, quarantine_s=60)
    hr.record_failure("b2", "err")
    assert "b2" in hr.quarantined_backends()


def test_hq6_quarantine_auto_expires():
    hr = HealthRegistry(failure_threshold=2, quarantine_s=0.05)
    hr.record_failure("b3", "e1")
    hr.record_failure("b3", "e2")
    assert not hr.is_healthy("b3")
    time.sleep(0.06)
    assert hr.is_healthy("b3")
    assert hr.get_state("b3") == BackendState.DEGRADED


def test_hq7_recovery_probes_required():
    hr = HealthRegistry(failure_threshold=2, quarantine_s=0.01, recovery_probes=3)
    hr.record_failure("b4", "e1")
    hr.record_failure("b4", "e2")
    time.sleep(0.02)
    hr.is_healthy("b4")
    hr.record_success("b4")
    assert hr.get_state("b4") != BackendState.HEALTHY
    hr.record_success("b4")
    assert hr.get_state("b4") != BackendState.HEALTHY
    hr.record_success("b4")
    assert hr.get_state("b4") == BackendState.HEALTHY


def test_hq8_failure_resets_consecutive_successes():
    hr = HealthRegistry(failure_threshold=5)
    hr.record_success("b5")
    hr.record_success("b5")
    hr.record_failure("b5", "e")
    assert hr.all_health()["b5"]["consecutive_successes"] == 0


def test_hq9_rolling_window_expires_old_failures():
    hr = HealthRegistry(failure_threshold=3, failure_window_s=0.1)
    hr.record_failure("b6", "old1")
    hr.record_failure("b6", "old2")
    time.sleep(0.15)
    hr.record_failure("b6", "new1")
    assert hr.is_healthy("b6")


def test_hq10_quarantined_backend_skipped_in_routing():
    hr = HealthRegistry(failure_threshold=2, quarantine_s=60)
    hr.record_failure("ollama/sonia-vlm:32b", "down")
    hr.record_failure("ollama/sonia-vlm:32b", "down")
    engine = RoutingEngine(is_healthy=hr.is_healthy)
    decision = engine.select(ProfileName.CHAT_LOW_LATENCY, trace_id="hq10")
    assert decision.selected_backend == "ollama/qwen2.5:7b"
    assert any(skip["reason"] == "BACKEND_UNHEALTHY" for skip in decision.skipped)


def test_hq11_thread_safety_under_load():
    hr = HealthRegistry(failure_threshold=100)
    errors = []

    def hammer():
        try:
            for i in range(50):
                hr.record_success("threaded")
                hr.record_failure("threaded", f"e{i}")
                hr.is_healthy("threaded")
        except Exception as exc:
            errors.append(str(exc))

    threads = [threading.Thread(target=hammer) for _ in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    health = hr.all_health()["threaded"]
    assert not errors
    assert health["total_successes"] == 200
    assert health["total_failures"] == 200


def test_hq12_to_dict_contains_expected_fields():
    hr = HealthRegistry(failure_threshold=2, quarantine_s=60)
    hr.record_failure("b", "x")
    hr.record_failure("b", "y")
    data = hr.to_dict()
    assert "backends" in data
    assert "quarantined" in data
    assert data["config"]["failure_threshold"] == 2
