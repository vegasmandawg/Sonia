"""Pytest suite for model-router budget guard."""

import sys
from pathlib import Path


MODEL_ROUTER_DIR = Path(__file__).resolve().parents[2] / "services" / "model-router"
if str(MODEL_ROUTER_DIR) not in sys.path:
    sys.path.insert(0, str(MODEL_ROUTER_DIR))

from app.budget_guard import BudgetGuard
from app.profiles import ProfileName, ReasonCode, RoutingProfile
from app.routing_engine import RoutingEngine


def _profile() -> RoutingProfile:
    return RoutingProfile(
        name=ProfileName.CHAT_LOW_LATENCY,
        model_prefs=["x"],
        max_context=4000,
        latency_ms=3000,
    )


def test_bg1_unknown_backend_passes():
    bg = BudgetGuard()
    assert bg.check("unknown", _profile()) is None


def test_bg2_context_within_limit():
    bg = BudgetGuard()
    bg.register_backend("ok", max_context=8000, avg_latency_ms=500)
    assert bg.check("ok", _profile()) is None


def test_bg3_context_exceeded():
    bg = BudgetGuard()
    bg.register_backend("small", max_context=2000, avg_latency_ms=500)
    assert bg.check("small", _profile()) == ReasonCode.BUDGET_EXCEEDED_CONTEXT


def test_bg4_latency_exceeded():
    bg = BudgetGuard()
    bg.register_backend("slow", max_context=8000, avg_latency_ms=5000)
    assert bg.check("slow", _profile()) == ReasonCode.BUDGET_EXCEEDED_LATENCY


def test_bg5_context_check_precedence():
    bg = BudgetGuard()
    bg.register_backend("both", max_context=1000, avg_latency_ms=9000)
    assert bg.check("both", _profile()) == ReasonCode.BUDGET_EXCEEDED_CONTEXT


def test_bg6_ewma_latency_update():
    bg = BudgetGuard()
    bg.register_backend("ewma", max_context=8000, avg_latency_ms=1000)
    bg.update_latency("ewma", 4000)
    assert abs(bg._capacities["ewma"].avg_latency_ms - 1900) < 1
    bg.update_latency("ewma", 4000)
    assert abs(bg._capacities["ewma"].avg_latency_ms - 2530) < 1


def test_bg7_rejection_log():
    bg = BudgetGuard()
    bg.register_backend("small", max_context=2000, avg_latency_ms=500)
    bg.register_backend("slow", max_context=8000, avg_latency_ms=5000)
    bg.register_backend("both", max_context=1000, avg_latency_ms=9000)
    p = _profile()
    bg.check("small", p)
    bg.check("slow", p)
    bg.check("both", p)
    rejections = bg.recent_rejections
    assert len(rejections) >= 3
    assert all("reason" in item for item in rejections)


def test_bg8_routing_integration():
    bg = BudgetGuard()
    bg.register_backend("ollama/sonia-vlm:32b", max_context=4096, avg_latency_ms=800)
    bg.register_backend("ollama/qwen2.5:7b", max_context=4096, avg_latency_ms=500)
    engine = RoutingEngine(check_budget=bg.check)
    decision = engine.select(ProfileName.CHAT_LOW_LATENCY, trace_id="bg8")
    assert decision.selected_backend == "ollama/sonia-vlm:32b"


def test_bg9_exact_boundary_passes():
    bg = BudgetGuard()
    bg.register_backend("exact", max_context=4000, avg_latency_ms=3000)
    assert bg.check("exact", _profile()) is None


def test_bg10_to_dict():
    bg = BudgetGuard()
    bg.register_backend("a", max_context=1234, avg_latency_ms=10)
    data = bg.to_dict()
    assert "capacities" in data
    assert "a" in data["capacities"]
