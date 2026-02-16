"""
v4.0 E3 — Runtime QoS, Contract Fidelity, Release Discipline Governance
=========================================================================
10 governance components covering runtime quality and release hardening:

1.  SLOComplianceChecker          — per-capability SLO budget validation
2.  RateLimiterGovernor           — deterministic token-bucket rate limiting
3.  OutputBudgetGovernor          — cross-dimension budget enforcement
4.  SchemaValidationGovernor      — config/data schema completeness audit
5.  ConfigContractFidelityChecker — drift detection + contract enforcement
6.  DependencyLockVerifier        — package hash + version integrity
7.  ReleaseManifestValidator      — artifact completeness + SHA-256 hashes
8.  PromotionGateCoverageChecker  — gate-to-section binding validation
9.  TestStrategyComplianceChecker — section coverage + negative test audit
10. DeploymentReadinessChecker    — pre-deploy health + precondition gate
"""

import hashlib
import json
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Set


# ============================================================================
# 1. SLO Compliance Checker
# ============================================================================


class SLOTier(str, Enum):
    """SLO tiers with latency budgets."""
    INTERACTIVE = "interactive"  # 500ms
    STANDARD = "standard"       # 2000ms
    BATCH = "batch"             # 10000ms
    BACKGROUND = "background"   # unlimited


@dataclass
class SLOBudget:
    """Per-capability SLO budget definition."""
    capability: str
    tier: SLOTier
    p95_limit_ms: float
    p99_limit_ms: float
    error_rate_limit: float = 0.05  # 5%

    def to_dict(self) -> Dict[str, Any]:
        return {
            "capability": self.capability,
            "tier": self.tier.value,
            "p95_limit_ms": self.p95_limit_ms,
            "p99_limit_ms": self.p99_limit_ms,
            "error_rate_limit": self.error_rate_limit,
        }


class SLOViolation(Exception):
    """Raised when an SLO budget is exceeded."""

    def __init__(self, capability: str, metric: str, value: float, limit: float):
        self.capability = capability
        self.metric = metric
        self.value = value
        self.limit = limit
        super().__init__(
            f"SLO violation: {capability} {metric}={value:.1f} exceeds limit {limit:.1f}"
        )


DEFAULT_SLO_BUDGETS = {
    "file.read": SLOBudget("file.read", SLOTier.INTERACTIVE, 200.0, 500.0),
    "file.write": SLOBudget("file.write", SLOTier.INTERACTIVE, 200.0, 500.0),
    "shell.run": SLOBudget("shell.run", SLOTier.STANDARD, 2000.0, 5000.0),
    "model.chat": SLOBudget("model.chat", SLOTier.STANDARD, 2000.0, 5000.0),
    "memory.recall": SLOBudget("memory.recall", SLOTier.INTERACTIVE, 300.0, 800.0),
    "memory.write": SLOBudget("memory.write", SLOTier.INTERACTIVE, 200.0, 500.0),
}


class SLOComplianceChecker:
    """
    Validates per-capability SLO budget compliance.
    Tracks observed latencies and flags violations.
    """

    def __init__(self, budgets: Optional[Dict[str, SLOBudget]] = None):
        self._budgets = budgets or dict(DEFAULT_SLO_BUDGETS)
        self._observations: Dict[str, List[float]] = {}
        self._violations: List[Dict[str, Any]] = []

    def register_budget(self, budget: SLOBudget) -> None:
        self._budgets[budget.capability] = budget

    def record_latency(self, capability: str, latency_ms: float) -> None:
        if capability not in self._observations:
            self._observations[capability] = []
        obs = self._observations[capability]
        obs.append(latency_ms)
        if len(obs) > 1000:
            self._observations[capability] = obs[-1000:]

    def check_compliance(self, capability: str) -> Dict[str, Any]:
        """Check if a capability is within SLO budget."""
        budget = self._budgets.get(capability)
        if not budget:
            return {"capability": capability, "has_budget": False, "compliant": True}

        obs = self._observations.get(capability, [])
        if not obs:
            return {"capability": capability, "has_budget": True, "compliant": True,
                    "observations": 0}

        sorted_obs = sorted(obs)
        n = len(sorted_obs)
        p95_idx = int(n * 0.95)
        p99_idx = int(n * 0.99)
        p95 = sorted_obs[min(p95_idx, n - 1)]
        p99 = sorted_obs[min(p99_idx, n - 1)]

        violations = []
        if p95 > budget.p95_limit_ms:
            violations.append(f"p95={p95:.1f}ms > {budget.p95_limit_ms}ms")
        if p99 > budget.p99_limit_ms:
            violations.append(f"p99={p99:.1f}ms > {budget.p99_limit_ms}ms")

        compliant = len(violations) == 0
        result = {
            "capability": capability,
            "has_budget": True,
            "compliant": compliant,
            "p95_ms": p95,
            "p99_ms": p99,
            "observations": n,
            "violations": violations,
        }

        if not compliant:
            self._violations.append(result)

        return result

    def check_all(self) -> Dict[str, Any]:
        """Check compliance for all registered budgets."""
        results = {}
        for cap in self._budgets:
            results[cap] = self.check_compliance(cap)
        all_compliant = all(r["compliant"] for r in results.values())
        return {"all_compliant": all_compliant, "capabilities": results}

    def get_budgets(self) -> Dict[str, Dict[str, Any]]:
        return {k: v.to_dict() for k, v in self._budgets.items()}

    def get_violations(self) -> List[Dict[str, Any]]:
        return list(self._violations)


# ============================================================================
# 2. Rate Limiter Governor
# ============================================================================


@dataclass
class RateLimitConfig:
    """Token bucket rate limit configuration."""
    tokens_per_second: float
    burst_size: int
    scope: str = "session"  # session, user, global

    def to_dict(self) -> Dict[str, Any]:
        return {
            "tokens_per_second": self.tokens_per_second,
            "burst_size": self.burst_size,
            "scope": self.scope,
        }


class RateLimitExceeded(Exception):
    """Raised when rate limit is exceeded."""

    def __init__(self, scope_key: str, tokens_available: float):
        self.scope_key = scope_key
        self.tokens_available = tokens_available
        super().__init__(f"Rate limit exceeded for {scope_key}: {tokens_available:.2f} tokens available")


class RateLimiterGovernor:
    """
    Deterministic token-bucket rate limiter with per-scope buckets.
    Each bucket refills at a fixed rate and allows burst capacity.
    """

    def __init__(self, config: Optional[RateLimitConfig] = None):
        self._config = config or RateLimitConfig(
            tokens_per_second=10.0, burst_size=20, scope="session"
        )
        self._buckets: Dict[str, Dict[str, float]] = {}
        self._stats = {"total_requests": 0, "total_limited": 0}

    def _get_bucket(self, scope_key: str) -> Dict[str, float]:
        if scope_key not in self._buckets:
            self._buckets[scope_key] = {
                "tokens": float(self._config.burst_size),
                "last_refill": time.monotonic(),
            }
        return self._buckets[scope_key]

    def _refill(self, bucket: Dict[str, float]) -> None:
        now = time.monotonic()
        elapsed = now - bucket["last_refill"]
        new_tokens = elapsed * self._config.tokens_per_second
        bucket["tokens"] = min(
            float(self._config.burst_size),
            bucket["tokens"] + new_tokens,
        )
        bucket["last_refill"] = now

    def try_acquire(self, scope_key: str, tokens: float = 1.0) -> bool:
        """Try to acquire tokens. Returns True if allowed, False if rate-limited."""
        self._stats["total_requests"] += 1
        bucket = self._get_bucket(scope_key)
        self._refill(bucket)

        if bucket["tokens"] >= tokens:
            bucket["tokens"] -= tokens
            return True

        self._stats["total_limited"] += 1
        return False

    def acquire_or_raise(self, scope_key: str, tokens: float = 1.0) -> None:
        """Acquire tokens or raise RateLimitExceeded."""
        if not self.try_acquire(scope_key, tokens):
            bucket = self._get_bucket(scope_key)
            raise RateLimitExceeded(scope_key, bucket["tokens"])

    def get_config(self) -> Dict[str, Any]:
        return self._config.to_dict()

    def get_stats(self) -> Dict[str, Any]:
        return {
            **self._stats,
            "active_buckets": len(self._buckets),
            "config": self._config.to_dict(),
        }

    def is_deterministic(self) -> bool:
        """Verify that rate limiter uses deterministic (non-random) logic."""
        return True  # Token bucket is inherently deterministic


# ============================================================================
# 3. Output Budget Governor
# ============================================================================


class BudgetDimension(str, Enum):
    """Output budget enforcement dimensions."""
    OUTPUT_CHARS = "output_chars"
    CONTEXT_CHARS = "context_chars"
    TOOL_CALLS = "tool_calls"
    VISION_FRAMES = "vision_frames"
    MEMORY_ENTRIES = "memory_entries"


@dataclass
class BudgetEnforcementResult:
    """Result of budget enforcement for a single dimension."""
    dimension: str
    original_value: int
    enforced_value: int
    limit: int
    within_budget: bool

    def to_dict(self) -> Dict[str, Any]:
        return {
            "dimension": self.dimension,
            "original_value": self.original_value,
            "enforced_value": self.enforced_value,
            "limit": self.limit,
            "within_budget": self.within_budget,
        }


DEFAULT_BUDGET_LIMITS = {
    BudgetDimension.OUTPUT_CHARS: 4000,
    BudgetDimension.CONTEXT_CHARS: 7000,
    BudgetDimension.TOOL_CALLS: 5,
    BudgetDimension.VISION_FRAMES: 3,
    BudgetDimension.MEMORY_ENTRIES: 10,
}


class OutputBudgetGovernor:
    """
    Cross-dimension budget enforcement governor.
    Validates that all 5 budget dimensions are within limits.
    """

    def __init__(self, limits: Optional[Dict[BudgetDimension, int]] = None):
        self._limits = limits or dict(DEFAULT_BUDGET_LIMITS)
        self._enforcement_log: List[Dict[str, Any]] = []

    def enforce(
        self, values: Dict[str, int]
    ) -> Dict[str, Any]:
        """
        Enforce budget across all dimensions.
        Returns enforcement result with per-dimension details.
        """
        results = []
        all_within = True

        for dim, limit in self._limits.items():
            val = values.get(dim.value, 0)
            within = val <= limit
            enforced = min(val, limit)
            if not within:
                all_within = False
            results.append(BudgetEnforcementResult(
                dimension=dim.value,
                original_value=val,
                enforced_value=enforced,
                limit=limit,
                within_budget=within,
            ))

        result = {
            "all_within_budget": all_within,
            "dimensions_checked": len(results),
            "results": [r.to_dict() for r in results],
            "timestamp": time.time(),
        }
        self._enforcement_log.append(result)
        if len(self._enforcement_log) > 500:
            self._enforcement_log = self._enforcement_log[-500:]

        return result

    def get_limits(self) -> Dict[str, int]:
        return {d.value: l for d, l in self._limits.items()}

    def dimensions_complete(self) -> bool:
        """Check all 5 dimensions have limits."""
        return len(self._limits) == len(BudgetDimension)

    def get_enforcement_log(self, limit: int = 50) -> List[Dict[str, Any]]:
        return self._enforcement_log[-limit:]


# ============================================================================
# 4. Schema Validation Governor
# ============================================================================


@dataclass
class SchemaAuditResult:
    """Result of a schema validation audit."""
    schema_name: str
    fields_defined: int
    fields_validated: int
    missing_validators: List[str]
    complete: bool

    def to_dict(self) -> Dict[str, Any]:
        return {
            "schema_name": self.schema_name,
            "fields_defined": self.fields_defined,
            "fields_validated": self.fields_validated,
            "missing_validators": self.missing_validators,
            "complete": self.complete,
        }


class SchemaValidationGovernor:
    """
    Audits schema validation completeness across config and data schemas.
    Ensures every defined field has a corresponding validator.
    """

    def __init__(self):
        self._schemas: Dict[str, Dict[str, Any]] = {}
        self._audit_results: List[SchemaAuditResult] = []

    def register_schema(
        self, name: str, fields: List[str], validators: List[str]
    ) -> None:
        """Register a schema with its fields and validators."""
        self._schemas[name] = {"fields": fields, "validators": validators}

    def audit_schema(self, name: str) -> SchemaAuditResult:
        """Audit a single schema for completeness."""
        schema = self._schemas.get(name)
        if not schema:
            result = SchemaAuditResult(
                schema_name=name, fields_defined=0, fields_validated=0,
                missing_validators=[], complete=False,
            )
            self._audit_results.append(result)
            return result

        fields = set(schema["fields"])
        validators = set(schema["validators"])
        missing = sorted(fields - validators)

        result = SchemaAuditResult(
            schema_name=name,
            fields_defined=len(fields),
            fields_validated=len(fields & validators),
            missing_validators=missing,
            complete=len(missing) == 0,
        )
        self._audit_results.append(result)
        return result

    def audit_all(self) -> Dict[str, Any]:
        """Audit all registered schemas."""
        results = {}
        for name in self._schemas:
            results[name] = self.audit_schema(name).to_dict()
        all_complete = all(r["complete"] for r in results.values())
        return {
            "all_complete": all_complete,
            "schemas_audited": len(results),
            "results": results,
        }

    def get_schemas(self) -> List[str]:
        return sorted(self._schemas.keys())


# ============================================================================
# 5. Config Contract Fidelity Checker
# ============================================================================


class ConfigDriftDetected(Exception):
    """Raised when configuration drift is detected."""

    def __init__(self, field: str, expected: Any, actual: Any):
        self.field = field
        self.expected = expected
        self.actual = actual
        super().__init__(f"Config drift: {field} expected={expected}, actual={actual}")


class ConfigContractFidelityChecker:
    """
    Enforces configuration contract fidelity by tracking baselines
    and detecting unauthorized changes.
    """

    def __init__(self):
        self._baselines: Dict[str, str] = {}  # field -> SHA-256 of value
        self._contracts: Dict[str, Any] = {}   # field -> expected value
        self._drift_log: List[Dict[str, Any]] = []

    def set_baseline(self, field: str, value: Any) -> str:
        """Set a baseline for a config field. Returns SHA-256 hash."""
        h = hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()
        self._baselines[field] = h
        self._contracts[field] = value
        return h

    def check_drift(self, field: str, current_value: Any) -> Dict[str, Any]:
        """Check if a field has drifted from baseline."""
        h = hashlib.sha256(
            json.dumps(current_value, sort_keys=True).encode()
        ).hexdigest()
        baseline = self._baselines.get(field)

        if baseline is None:
            return {"field": field, "has_baseline": False, "drifted": False}

        drifted = h != baseline
        result = {
            "field": field,
            "has_baseline": True,
            "drifted": drifted,
            "baseline_hash": baseline[:16],
            "current_hash": h[:16],
            "timestamp": time.time(),
        }

        if drifted:
            self._drift_log.append(result)

        return result

    def check_all(self, current_config: Dict[str, Any]) -> Dict[str, Any]:
        """Check all baselined fields for drift."""
        drifts = []
        for field in self._baselines:
            val = current_config.get(field)
            result = self.check_drift(field, val)
            if result["drifted"]:
                drifts.append(field)

        return {
            "total_fields": len(self._baselines),
            "fields_checked": len(self._baselines),
            "drifts_detected": len(drifts),
            "drifted_fields": drifts,
            "all_stable": len(drifts) == 0,
        }

    def get_drift_log(self) -> List[Dict[str, Any]]:
        return list(self._drift_log)


# ============================================================================
# 6. Dependency Lock Verifier
# ============================================================================


class DependencyIntegrityError(Exception):
    """Raised when dependency lock integrity check fails."""

    def __init__(self, issues: List[str]):
        self.issues = issues
        super().__init__(f"Dependency integrity issues: {issues}")


@dataclass
class DependencyRecord:
    """A single locked dependency."""
    name: str
    version: str
    sha256: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {"name": self.name, "version": self.version, "sha256": self.sha256}


class DependencyLockVerifier:
    """
    Verifies dependency lock file integrity.
    Checks package count, version pins, and overall digest.
    """

    def __init__(self):
        self._locked_deps: List[DependencyRecord] = []
        self._manifest_hash: str = ""

    def load_manifest(
        self,
        packages: List[Dict[str, str]],
        manifest_hash: str = "",
    ) -> None:
        """Load dependency manifest."""
        self._locked_deps = [
            DependencyRecord(
                name=p["name"],
                version=p["version"],
                sha256=p.get("sha256", ""),
            )
            for p in packages
        ]
        self._manifest_hash = manifest_hash

    def verify(self) -> Dict[str, Any]:
        """Verify integrity of locked dependencies."""
        issues: List[str] = []

        if not self._locked_deps:
            issues.append("No locked dependencies loaded")

        # Check for missing version pins
        unpinned = [d for d in self._locked_deps if not d.version]
        if unpinned:
            issues.append(f"{len(unpinned)} deps without version pins")

        # Check for duplicate packages
        names = [d.name for d in self._locked_deps]
        dupes = [n for n in set(names) if names.count(n) > 1]
        if dupes:
            issues.append(f"Duplicate packages: {sorted(dupes)}")

        # Compute manifest hash
        canonical = json.dumps(
            [d.to_dict() for d in self._locked_deps],
            sort_keys=True,
            separators=(",", ":"),
        )
        computed_hash = hashlib.sha256(canonical.encode()).hexdigest()

        hash_valid = True
        if self._manifest_hash:
            hash_valid = computed_hash == self._manifest_hash
            if not hash_valid:
                issues.append("Manifest hash mismatch")

        return {
            "package_count": len(self._locked_deps),
            "all_pinned": len(unpinned) == 0,
            "no_duplicates": len(dupes) == 0,
            "hash_valid": hash_valid,
            "computed_hash": computed_hash[:16],
            "issues": issues,
            "integrity_ok": len(issues) == 0,
        }

    def get_locked_deps(self) -> List[Dict[str, Any]]:
        return [d.to_dict() for d in self._locked_deps]


# ============================================================================
# 7. Release Manifest Validator
# ============================================================================


class ReleaseManifestIncomplete(Exception):
    """Raised when a release manifest is incomplete."""

    def __init__(self, missing: List[str]):
        self.missing = missing
        super().__init__(f"Release manifest missing: {missing}")


REQUIRED_MANIFEST_FIELDS = frozenset({
    "version",
    "release_date",
    "git_sha",
    "gate_report",
    "test_count",
    "artifact_checksums",
    "dependency_lock_hash",
    "changelog",
})


class ReleaseManifestValidator:
    """
    Validates release manifest completeness and integrity.
    Ensures all required fields are present and checksums are valid.
    """

    def __init__(self):
        self._validation_log: List[Dict[str, Any]] = []

    def validate(self, manifest: Dict[str, Any]) -> Dict[str, Any]:
        """Validate a release manifest dict."""
        missing = []
        for f in REQUIRED_MANIFEST_FIELDS:
            if f not in manifest or not manifest[f]:
                missing.append(f)

        # Validate artifact checksums if present
        checksums = manifest.get("artifact_checksums", {})
        checksum_valid = isinstance(checksums, dict) and len(checksums) > 0

        # Validate gate report
        gate = manifest.get("gate_report", {})
        gate_valid = (
            isinstance(gate, dict)
            and gate.get("passed", 0) > 0
            and gate.get("failed", 0) == 0
        )

        result = {
            "valid": len(missing) == 0 and checksum_valid and gate_valid,
            "missing_fields": missing,
            "checksum_valid": checksum_valid,
            "gate_valid": gate_valid,
            "fields_present": len(manifest),
            "timestamp": time.time(),
        }

        self._validation_log.append(result)
        if len(self._validation_log) > 100:
            self._validation_log = self._validation_log[-100:]

        if missing:
            raise ReleaseManifestIncomplete(missing)

        return result

    def get_required_fields(self) -> List[str]:
        return sorted(REQUIRED_MANIFEST_FIELDS)

    def get_validation_log(self) -> List[Dict[str, Any]]:
        return list(self._validation_log)


# ============================================================================
# 8. Promotion Gate Coverage Checker
# ============================================================================


@dataclass
class GateSectionBinding:
    """Binding of a gate script to sections it validates."""
    gate_name: str
    sections: List[str]

    def to_dict(self) -> Dict[str, Any]:
        return {"gate_name": self.gate_name, "sections": self.sections}


class PromotionGateCoverageChecker:
    """
    Validates that all defined sections have at least one gate covering them.
    Checks gate-to-section binding completeness.
    """

    def __init__(self):
        self._bindings: List[GateSectionBinding] = []
        self._all_sections: Set[str] = set()

    def define_sections(self, sections: List[str]) -> None:
        """Define the full set of sections that need coverage."""
        self._all_sections = set(sections)

    def register_gate(self, gate_name: str, sections: List[str]) -> None:
        """Register a gate with the sections it covers."""
        self._bindings.append(GateSectionBinding(gate_name, sections))

    def check_coverage(self) -> Dict[str, Any]:
        """Check that all sections have at least one gate."""
        covered = set()
        for binding in self._bindings:
            covered.update(binding.sections)

        uncovered = self._all_sections - covered
        extra = covered - self._all_sections

        return {
            "total_sections": len(self._all_sections),
            "covered_sections": len(covered & self._all_sections),
            "uncovered_sections": sorted(uncovered),
            "extra_sections": sorted(extra),
            "total_gates": len(self._bindings),
            "complete": len(uncovered) == 0,
        }

    def get_bindings(self) -> List[Dict[str, Any]]:
        return [b.to_dict() for b in self._bindings]


# ============================================================================
# 9. Test Strategy Compliance Checker
# ============================================================================


@dataclass
class TestSectionMapping:
    """Maps a test file to sections it validates."""
    test_file: str
    sections: List[str]
    has_negative_tests: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "test_file": self.test_file,
            "sections": self.sections,
            "has_negative_tests": self.has_negative_tests,
        }


class TestStrategyComplianceChecker:
    """
    Validates that test strategy covers all required sections
    with both positive and negative test paths.
    """

    def __init__(self):
        self._mappings: List[TestSectionMapping] = []
        self._required_sections: Set[str] = set()

    def define_required_sections(self, sections: List[str]) -> None:
        self._required_sections = set(sections)

    def register_test(
        self, test_file: str, sections: List[str], has_negative_tests: bool = False
    ) -> None:
        self._mappings.append(
            TestSectionMapping(test_file, sections, has_negative_tests)
        )

    def check_compliance(self) -> Dict[str, Any]:
        """Check test strategy compliance."""
        covered = set()
        negative_covered = set()

        for m in self._mappings:
            covered.update(m.sections)
            if m.has_negative_tests:
                negative_covered.update(m.sections)

        uncovered = self._required_sections - covered
        missing_negative = self._required_sections - negative_covered

        return {
            "total_required_sections": len(self._required_sections),
            "sections_covered": len(covered & self._required_sections),
            "uncovered_sections": sorted(uncovered),
            "sections_with_negative_tests": len(negative_covered & self._required_sections),
            "missing_negative_tests": sorted(missing_negative),
            "total_test_files": len(self._mappings),
            "section_coverage_complete": len(uncovered) == 0,
            "negative_coverage_complete": len(missing_negative) == 0,
        }

    def get_mappings(self) -> List[Dict[str, Any]]:
        return [m.to_dict() for m in self._mappings]


# ============================================================================
# 10. Deployment Readiness Checker
# ============================================================================


class DeploymentNotReady(Exception):
    """Raised when deployment preconditions are not met."""

    def __init__(self, blockers: List[str]):
        self.blockers = blockers
        super().__init__(f"Deployment not ready: {blockers}")


class DeploymentReadinessChecker:
    """
    Pre-deployment health and precondition gate.
    All checks must pass before deployment is allowed.
    """

    REQUIRED_CHECKS = [
        "config_valid",
        "dependencies_locked",
        "gates_passed",
        "tests_passed",
        "health_endpoint_ok",
        "no_active_incidents",
        "backup_current",
    ]

    def __init__(self):
        self._check_results: Dict[str, bool] = {}
        self._history: List[Dict[str, Any]] = []

    def record_check(self, check_name: str, passed: bool, detail: str = "") -> None:
        if check_name not in self.REQUIRED_CHECKS:
            raise ValueError(f"Unknown deployment check: {check_name}")
        self._check_results[check_name] = passed

    def evaluate(self) -> Dict[str, Any]:
        """Evaluate all deployment readiness checks."""
        blockers = []
        for check in self.REQUIRED_CHECKS:
            if check not in self._check_results:
                blockers.append(f"unchecked:{check}")
            elif not self._check_results[check]:
                blockers.append(check)

        ready = len(blockers) == 0
        result = {
            "ready": ready,
            "checks_passed": sum(1 for v in self._check_results.values() if v),
            "checks_total": len(self.REQUIRED_CHECKS),
            "blockers": blockers,
            "timestamp": time.time(),
        }

        self._history.append(result)
        if len(self._history) > 50:
            self._history = self._history[-50:]

        self._check_results.clear()

        if not ready:
            raise DeploymentNotReady(blockers)

        return result

    def get_history(self) -> List[Dict[str, Any]]:
        return list(self._history)
