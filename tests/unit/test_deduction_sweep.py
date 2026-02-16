"""
Deduction Sweep Tests (14+ tests)
===================================
Tests for C (code quality), D (config), K (perf), L (contracts),
N (observability) deduction elimination modules.
"""
import sys
import hashlib

sys.path.insert(0, r"S:\services\api-gateway")

from lint_config import LintConfig, LintRule, Severity, DEFAULT_POLICY
from config_audit import ConfigAuditEngine
from slo_dashboard import SLODashboard, SLOStatus
from contract_trace import (
    ContractConsistencyChecker,
    ServiceContract,
    ContractField,
    TracePropagationChecker,
)
from observability_requirements import ObservabilityRequirements


class TestCodeQuality_C:
    """Section C: Lint/type/style policy evidence."""

    def test_default_policy_valid(self):
        v = DEFAULT_POLICY.validate()
        assert v["valid"]
        assert v["error_rules"] >= 2

    def test_empty_config_invalid(self):
        cfg = LintConfig()
        v = cfg.validate()
        assert not v["valid"]
        assert "No lint rules defined" in v["issues"]

    def test_get_enabled_rules(self):
        cfg = LintConfig(rules=[
            LintRule("r1", "test", Severity.ERROR, enabled=True),
            LintRule("r2", "test", Severity.WARNING, enabled=False),
        ])
        enabled = cfg.get_enabled_rules()
        assert len(enabled) == 1
        assert enabled[0].rule_id == "r1"

    def test_severity_filter(self):
        errors = DEFAULT_POLICY.get_rules_by_severity(Severity.ERROR)
        assert len(errors) >= 2
        assert all(r.severity == Severity.ERROR for r in errors)

    def test_to_dict(self):
        d = DEFAULT_POLICY.to_dict()
        assert "rules" in d
        assert "version" in d
        assert len(d["rules"]) >= 5


class TestConfigManagement_D:
    """Section D: Schema validation + config drift checks."""

    def test_register_and_check_clean(self):
        e = ConfigAuditEngine()
        e.register("a.json", "1.0", '{"key": "val"}')
        r = e.check_drift("a.json", '{"key": "val"}')
        assert r["status"] == "CLEAN"
        assert not r["drifted"]

    def test_drift_detected(self):
        e = ConfigAuditEngine()
        e.register("a.json", "1.0", '{"key": "val"}')
        r = e.check_drift("a.json", '{"key": "changed"}')
        assert r["status"] == "DRIFTED"
        assert r["drifted"]

    def test_required_keys_pass(self):
        e = ConfigAuditEngine()
        e.register("a.json", "1.0", "{}", ["port", "host"])
        r = e.validate_required_keys("a.json", {"port": 7000, "host": "localhost"})
        assert r["valid"]

    def test_required_keys_missing(self):
        e = ConfigAuditEngine()
        e.register("a.json", "1.0", "{}", ["port", "host"])
        r = e.validate_required_keys("a.json", {"port": 7000})
        assert not r["valid"]
        assert "host" in r["missing"]

    def test_check_all_drift(self):
        e = ConfigAuditEngine()
        e.register("a.json", "1.0", "content_a")
        e.register("b.json", "1.0", "content_b")
        r = e.check_all_drift({"a.json": "content_a", "b.json": "changed"})
        assert r["drifted"] == 1
        assert r["clean"] == 1


class TestPerformance_K:
    """Section K: Steady-state performance assertions + budget evidence."""

    def test_slo_met(self):
        d = SLODashboard()
        d.define_slo("latency", "p95", 200.0)
        r = d.evaluate("latency", 150.0)
        assert r.status == SLOStatus.MET

    def test_slo_breached(self):
        d = SLODashboard()
        d.define_slo("latency", "p95", 200.0)
        r = d.evaluate("latency", 250.0)
        assert r.status == SLOStatus.BREACHED

    def test_evaluate_all(self):
        d = SLODashboard()
        d.define_slo("latency", "p95", 200.0)
        d.define_slo("throughput", "rps", 1000.0)
        r = d.evaluate_all({"latency": 150.0, "throughput": 800.0})
        assert r["all_met"]
        assert r["met"] == 2

    def test_budget_report(self):
        d = SLODashboard()
        d.define_slo("latency", "p95", 200.0)
        d.evaluate("latency", 180.0)
        report = d.get_budget_report()
        assert report["total"] == 1
        assert report["results"][0]["margin"] == 20.0


class TestContracts_L:
    """Section L: Contract consistency/trace propagation checks."""

    def test_contract_required_fields_pass(self):
        cc = ContractConsistencyChecker()
        cc.register(ServiceContract("svc", "1.0", [
            ContractField("id", "string"), ContractField("ts", "string")
        ]))
        r = cc.check_required_fields("svc", {"id": "1", "ts": "now"})
        assert r["valid"]

    def test_contract_missing_field(self):
        cc = ContractConsistencyChecker()
        cc.register(ServiceContract("svc", "1.0", [
            ContractField("id", "string"), ContractField("ts", "string")
        ]))
        r = cc.check_required_fields("svc", {"id": "1"})
        assert not r["valid"]
        assert "ts" in r["missing"]

    def test_trace_propagation_valid(self):
        stages = [
            {"correlation_id": "req_trace_test"},
            {"correlation_id": "req_trace_test"},
        ]
        r = TracePropagationChecker.check_propagation(stages)
        assert r["valid"]
        assert r["consistent"]

    def test_trace_propagation_inconsistent(self):
        stages = [
            {"correlation_id": "req_trace_aaaa"},
            {"correlation_id": "req_trace_bbbb"},
        ]
        r = TracePropagationChecker.check_propagation(stages)
        assert not r["consistent"]

    def test_trace_propagation_missing(self):
        stages = [
            {"correlation_id": "req_trace_test"},
            {"other": "no_cid"},
        ]
        r = TracePropagationChecker.check_propagation(stages)
        assert not r["valid"]


class TestObservability_N:
    """Section N: Required telemetry field completeness."""

    def test_log_entry_complete(self):
        obs = ObservabilityRequirements()
        entry = {"timestamp": "t", "level": "INFO", "message": "m",
                 "service": "gw", "correlation_id": "req_obs_test"}
        r = obs.check_field_completeness("log_entry", entry)
        assert r["valid"]

    def test_log_entry_missing_field(self):
        obs = ObservabilityRequirements()
        entry = {"timestamp": "t", "level": "INFO"}
        r = obs.check_field_completeness("log_entry", entry)
        assert not r["valid"]
        assert "message" in r["missing"]

    def test_correlation_continuity_complete(self):
        entries = [
            {"correlation_id": "req_corr_test", "msg": "a"},
            {"correlation_id": "req_corr_test", "msg": "b"},
        ]
        obs = ObservabilityRequirements()
        r = obs.check_correlation_continuity(entries)
        assert r["complete"]
        assert r["coverage_pct"] == 100.0

    def test_correlation_continuity_incomplete(self):
        entries = [
            {"correlation_id": "req_corr_test"},
            {"msg": "no cid"},
        ]
        obs = ObservabilityRequirements()
        r = obs.check_correlation_continuity(entries)
        assert not r["complete"]

    def test_check_all_types(self):
        obs = ObservabilityRequirements()
        samples = {
            "log_entry": {"timestamp": "t", "level": "INFO", "message": "m",
                          "service": "s", "correlation_id": "c"},
            "health_check": {"timestamp": "t", "service": "s",
                             "status": "ok", "latency_ms": 10},
        }
        r = obs.check_all_types(samples)
        assert r["all_valid"]
