"""Pytest suite for deterministic profile selection."""

import sys
from pathlib import Path


MODEL_ROUTER_DIR = Path(__file__).resolve().parents[2] / "services" / "model-router"
if str(MODEL_ROUTER_DIR) not in sys.path:
    sys.path.insert(0, str(MODEL_ROUTER_DIR))

from app.profiles import (
    ProfileName,
    ProfileRegistry,
    RoutingProfile,
    classify_request,
)
from app.routing_engine import RoutingEngine


def test_ps1_classify_request_is_deterministic():
    results = [classify_request(hint="analyze image") for _ in range(50)]
    assert len({r.value for r in results}) == 1


def test_ps2_classify_by_task_type_and_hint():
    assert classify_request(task_type="vision") == ProfileName.VISION_ANALYSIS
    assert classify_request(task_type="text", hint="reasoning") == ProfileName.REASONING_DEEP


def test_ps3_classify_by_hint_patterns():
    assert classify_request(hint="execute tool") == ProfileName.TOOL_EXECUTION
    assert classify_request(hint="remember this fact") == ProfileName.MEMORY_OPS
    assert classify_request(hint="quick chat") == ProfileName.CHAT_LOW_LATENCY


def test_ps4_default_classification_is_chat():
    assert classify_request() == ProfileName.CHAT_LOW_LATENCY
    assert classify_request(hint="xyz unknown") == ProfileName.CHAT_LOW_LATENCY


def test_ps5_registry_contains_all_profiles():
    registry = ProfileRegistry()
    assert len(registry.names) == 6
    for name in ProfileName:
        assert registry.get(name) is not None


def test_ps6_profile_validation():
    registry = ProfileRegistry()
    valid_profile = registry.get(ProfileName.CHAT_LOW_LATENCY)
    assert valid_profile.validate() == []
    invalid = RoutingProfile(
        name=ProfileName.SAFE_FALLBACK,
        model_prefs=[],
        fallbacks=[],
        latency_ms=-1,
        max_context=-1,
    )
    assert len(invalid.validate()) >= 3


def test_ps7_dispatch_chain_dedupes_fallbacks():
    profile = RoutingProfile(
        name=ProfileName.TOOL_EXECUTION,
        model_prefs=["a", "b"],
        fallbacks=["b", "c", "a"],
    )
    assert profile.dispatch_chain() == ["a", "b", "c"]


def test_ps8_routing_engine_selects_first_healthy():
    engine = RoutingEngine()
    decision_1 = engine.select(ProfileName.CHAT_LOW_LATENCY, trace_id="ps8a")
    decision_2 = engine.select(ProfileName.CHAT_LOW_LATENCY, trace_id="ps8b")
    assert decision_1.selected_backend == decision_2.selected_backend
    assert decision_1.reason_code == "PROFILE_MATCH"


def test_ps9_routing_engine_uses_fallback_when_primary_unhealthy():
    engine = RoutingEngine(is_healthy=lambda backend: "qwen2.5" in backend)
    decision = engine.select(ProfileName.CHAT_LOW_LATENCY, trace_id="ps9")
    assert decision.selected_backend == "ollama/qwen2.5:7b"
    assert decision.reason_code == "FALLBACK_USED"


def test_ps10_all_unhealthy_returns_no_backend():
    engine = RoutingEngine(is_healthy=lambda backend: False)
    decision = engine.select(ProfileName.REASONING_DEEP, trace_id="ps10")
    assert decision.selected_backend is None
    assert decision.reason_code == "NO_BACKEND_AVAILABLE"


def test_ps11_route_request_end_to_end():
    engine = RoutingEngine()
    decision = engine.route_request(task_type="vision", hint="screenshot", trace_id="ps11")
    assert decision.profile_name == "vision_analysis"
    assert decision.selected_backend is not None


def test_ps12_route_decision_serialization():
    engine = RoutingEngine()
    decision = engine.route_request(task_type="vision", hint="screenshot", trace_id="ps12")
    data = decision.to_dict()
    assert "trace_id" in data
    assert "fallback_chain" in data
    assert "reason_code" in data
    assert "skipped" in data
