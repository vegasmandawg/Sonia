"""Pytest suite validating fallback-chain behavior."""

import json
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
MODEL_ROUTER_DIR = REPO_ROOT / "services" / "model-router"
if str(MODEL_ROUTER_DIR) not in sys.path:
    sys.path.insert(0, str(MODEL_ROUTER_DIR))

from app.budget_guard import BudgetGuard
from app.health_registry import HealthRegistry
from app.profiles import ProfileName, ReasonCode, ProfileRegistry
from app.routing_engine import RoutingEngine


def test_fm1_full_chain_walked_when_primary_down():
    engine = RoutingEngine(is_healthy=lambda backend: "qwen2.5" in backend)
    decision = engine.select(ProfileName.CHAT_LOW_LATENCY, trace_id="fm1")
    assert decision.selected_backend == "ollama/qwen2.5:7b"
    assert len(decision.skipped) == 1
    assert decision.skipped[0]["backend"] == "ollama/sonia-vlm:32b"


def test_fm2_fallback_order_preserved():
    visited = []

    def track_health(backend: str) -> bool:
        visited.append(backend)
        return False

    engine = RoutingEngine(is_healthy=track_health)
    engine.select(ProfileName.REASONING_DEEP, trace_id="fm2")
    assert visited == [
        "anthropic/claude-opus-4-6",
        "anthropic/claude-sonnet-4-6",
        "ollama/sonia-vlm:32b",
    ]


def test_fm3_no_fallback_when_primary_healthy():
    engine = RoutingEngine()
    decision = engine.select(ProfileName.CHAT_LOW_LATENCY, trace_id="fm3")
    assert decision.selected_backend == "ollama/sonia-vlm:32b"
    assert decision.skipped == []
    assert decision.reason_code == "PROFILE_MATCH"


def test_fm4_multiple_skips_logged():
    engine = RoutingEngine(is_healthy=lambda backend: "qwen2.5" in backend)
    decision = engine.select(ProfileName.TOOL_EXECUTION, trace_id="fm4")
    assert decision.selected_backend == "ollama/qwen2.5:7b"
    assert len(decision.skipped) == 2


def test_fm5_consistent_fallback_across_runs():
    engine = RoutingEngine(is_healthy=lambda backend: "sonnet" in backend)
    results = [
        engine.select(ProfileName.REASONING_DEEP, trace_id=f"fm5_{i}").selected_backend
        for i in range(20)
    ]
    assert len(set(results)) == 1
    assert results[0] == "anthropic/claude-sonnet-4-6"


def test_fm6_safe_fallback_has_no_fallbacks():
    registry = ProfileRegistry()
    safe = registry.get(ProfileName.SAFE_FALLBACK)
    assert safe.fallbacks == []
    assert len(safe.model_prefs) == 2


def test_fm7_budget_based_fallback_allows_primary():
    budget_guard = BudgetGuard()
    budget_guard.register_backend("anthropic/claude-opus-4-6", max_context=200000, avg_latency_ms=5000)
    budget_guard.register_backend("anthropic/claude-sonnet-4-6", max_context=200000, avg_latency_ms=1500)
    budget_guard.register_backend("ollama/sonia-vlm:32b", max_context=4096, avg_latency_ms=2000)
    engine = RoutingEngine(check_budget=budget_guard.check)
    decision = engine.select(ProfileName.REASONING_DEEP, trace_id="fm7")
    assert decision.selected_backend == "anthropic/claude-opus-4-6"
    assert decision.reason_code == "PROFILE_MATCH"


def test_fm8_budget_and_health_combined():
    budget_guard = BudgetGuard()
    budget_guard.register_backend("anthropic/claude-opus-4-6", max_context=200000, avg_latency_ms=5000)
    budget_guard.register_backend("anthropic/claude-sonnet-4-6", max_context=200000, avg_latency_ms=1500)
    budget_guard.register_backend("ollama/sonia-vlm:32b", max_context=4096, avg_latency_ms=2000)

    health = HealthRegistry(failure_threshold=1, quarantine_s=60)
    health.record_failure("anthropic/claude-opus-4-6", "down")

    engine = RoutingEngine(is_healthy=health.is_healthy, check_budget=budget_guard.check)
    decision = engine.select(ProfileName.REASONING_DEEP, trace_id="fm8")

    assert decision.selected_backend == "anthropic/claude-sonnet-4-6"
    assert any(skip["reason"] == "BACKEND_UNHEALTHY" for skip in decision.skipped)


def test_fm9_skip_reasons_are_reason_codes():
    budget_guard = BudgetGuard()
    budget_guard.register_backend("anthropic/claude-opus-4-6", max_context=200000, avg_latency_ms=5000)
    budget_guard.register_backend("anthropic/claude-sonnet-4-6", max_context=200000, avg_latency_ms=1500)
    health = HealthRegistry(failure_threshold=1, quarantine_s=60)
    health.record_failure("anthropic/claude-opus-4-6", "down")
    engine = RoutingEngine(is_healthy=health.is_healthy, check_budget=budget_guard.check)
    decision = engine.select(ProfileName.REASONING_DEEP, trace_id="fm9")

    valid_reason_values = {r.value for r in ReasonCode}
    for skip in decision.skipped:
        assert skip["reason"] in valid_reason_values


def test_fm10_config_fallback_matrix_matches_canonical_values():
    config_path = REPO_ROOT / "config" / "sonia-config.json"
    with config_path.open("r", encoding="utf-8") as f:
        config = json.load(f)

    matrix = config["model_router"]["profiles"]["fallback_matrix"]
    assert matrix["chat_low_latency"] == ["ollama/sonia-vlm:32b", "ollama/qwen2.5:7b"]
    assert matrix["reasoning_deep"][0] == "anthropic/claude-opus-4-6"
    assert len(matrix) == 6
