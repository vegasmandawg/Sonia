"""
Chaos scenario policy: declared, bounded, deterministic.

Provides a registry of chaos scenarios with explicit bounds on timeouts,
retries, and max impact. All operations are deterministic and sorted.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Dict, FrozenSet, List, Optional


SCHEMA_VERSION = "1.0.0"


@dataclass(frozen=True)
class ChaosScenario:
    """A declared chaos scenario with bounded parameters."""
    scenario_id: str
    name: str
    description: str
    target_adapter: str          # e.g. "native", "subprocess", "dry-run"
    fault_type: str              # e.g. "timeout", "error", "latency", "crash"
    max_timeout_ms: int          # upper bound for timeout injection
    max_retries: int             # upper bound for retries allowed
    max_impact_scope: str        # "single_action", "adapter", "pipeline"
    deterministic_seed: Optional[int] = None  # None = no randomness

    def __post_init__(self):
        if self.max_timeout_ms < 0:
            raise ValueError(f"max_timeout_ms must be >= 0, got {self.max_timeout_ms}")
        if self.max_retries < 0:
            raise ValueError(f"max_retries must be >= 0, got {self.max_retries}")
        valid_scopes = ("single_action", "adapter", "pipeline")
        if self.max_impact_scope not in valid_scopes:
            raise ValueError(f"max_impact_scope must be one of {valid_scopes}")

    def fingerprint(self) -> str:
        canonical = (
            f"{self.scenario_id}|{self.name}|{self.target_adapter}|"
            f"{self.fault_type}|{self.max_timeout_ms}|{self.max_retries}|"
            f"{self.max_impact_scope}|{self.deterministic_seed}"
        )
        return hashlib.sha256(canonical.encode()).hexdigest()

    def is_bounded(self) -> bool:
        """Verify scenario has finite bounds."""
        return (
            self.max_timeout_ms <= 60_000
            and self.max_retries <= 10
            and self.max_impact_scope in ("single_action", "adapter", "pipeline")
        )


class DuplicateScenarioError(Exception):
    pass


class ScenarioNotFoundError(Exception):
    pass


class ChaosPolicyRegistry:
    """Registry for chaos scenarios with versioning and bounds enforcement."""

    def __init__(self):
        self._scenarios: Dict[str, ChaosScenario] = {}
        self._version = SCHEMA_VERSION

    @property
    def version(self) -> str:
        return self._version

    def register(self, scenario: ChaosScenario) -> None:
        if scenario.scenario_id in self._scenarios:
            raise DuplicateScenarioError(
                f"Scenario '{scenario.scenario_id}' already registered"
            )
        self._scenarios[scenario.scenario_id] = scenario

    def get(self, scenario_id: str) -> ChaosScenario:
        if scenario_id not in self._scenarios:
            raise ScenarioNotFoundError(f"Scenario '{scenario_id}' not found")
        return self._scenarios[scenario_id]

    def has(self, scenario_id: str) -> bool:
        return scenario_id in self._scenarios

    def list_all(self) -> List[ChaosScenario]:
        return sorted(self._scenarios.values(), key=lambda s: s.scenario_id)

    def list_by_fault_type(self, fault_type: str) -> List[ChaosScenario]:
        return sorted(
            [s for s in self._scenarios.values() if s.fault_type == fault_type],
            key=lambda s: s.scenario_id,
        )

    def all_bounded(self) -> bool:
        """Check all registered scenarios have finite bounds."""
        return all(s.is_bounded() for s in self._scenarios.values())

    def unbounded_scenarios(self) -> List[str]:
        return sorted(
            s.scenario_id for s in self._scenarios.values() if not s.is_bounded()
        )

    def export_manifest(self) -> dict:
        fingerprints = sorted(s.fingerprint() for s in self._scenarios.values())
        combined = "|".join(fingerprints)
        manifest_hash = hashlib.sha256(combined.encode()).hexdigest()
        return {
            "schema_version": self._version,
            "scenario_count": len(self._scenarios),
            "manifest_hash": manifest_hash,
            "scenario_ids": sorted(self._scenarios.keys()),
        }
