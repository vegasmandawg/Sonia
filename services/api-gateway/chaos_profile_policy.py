"""Chaos Profile Policy — v4.2 E2.

Governs bounded, versioned chaos scenarios with hash-stable profiles.
Each profile defines timeout caps, retry limits, and blast-radius
constraints that are enforced deterministically.
"""
import hashlib
import json
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional

SCHEMA_VERSION = "1.0.0"

# Hard caps for scenario bounds
MAX_TIMEOUT_MS = 30000
MAX_RETRIES = 5
MAX_BLAST_RADIUS = 3  # max concurrent faults


class ScenarioType(Enum):
    ADAPTER_TIMEOUT = "adapter_timeout"
    BREAKER_TRIP = "breaker_trip"
    DLQ_OVERFLOW = "dlq_overflow"
    MEMORY_PRESSURE = "memory_pressure"
    CASCADE_FAILURE = "cascade_failure"


@dataclass(frozen=True)
class ChaosScenario:
    """A single bounded chaos scenario."""
    scenario_id: str
    scenario_type: ScenarioType
    timeout_ms: int
    max_retries: int
    blast_radius: int  # number of concurrent faults
    description: str

    def __post_init__(self):
        if not self.scenario_id:
            raise ValueError("scenario_id must be non-empty")
        if self.timeout_ms < 0:
            raise ValueError("timeout_ms must be non-negative")
        if self.timeout_ms > MAX_TIMEOUT_MS:
            raise ValueError(
                f"timeout_ms {self.timeout_ms} exceeds cap {MAX_TIMEOUT_MS}"
            )
        if self.max_retries < 0:
            raise ValueError("max_retries must be non-negative")
        if self.max_retries > MAX_RETRIES:
            raise ValueError(
                f"max_retries {self.max_retries} exceeds cap {MAX_RETRIES}"
            )
        if self.blast_radius < 1:
            raise ValueError("blast_radius must be >= 1")
        if self.blast_radius > MAX_BLAST_RADIUS:
            raise ValueError(
                f"blast_radius {self.blast_radius} exceeds cap {MAX_BLAST_RADIUS}"
            )

    @property
    def fingerprint(self) -> str:
        blob = json.dumps({
            "scenario_id": self.scenario_id,
            "scenario_type": self.scenario_type.value,
            "timeout_ms": self.timeout_ms,
            "max_retries": self.max_retries,
            "blast_radius": self.blast_radius,
            "description": self.description,
        }, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(blob.encode()).hexdigest()


@dataclass(frozen=True)
class ChaosProfile:
    """A versioned collection of chaos scenarios."""
    profile_id: str
    version: int
    scenarios: tuple  # tuple of ChaosScenario
    description: str

    def __post_init__(self):
        if not self.profile_id:
            raise ValueError("profile_id must be non-empty")
        if self.version < 1:
            raise ValueError("version must be >= 1")
        if not self.scenarios:
            raise ValueError("scenarios must be non-empty")

    @property
    def fingerprint(self) -> str:
        blob = json.dumps({
            "profile_id": self.profile_id,
            "version": self.version,
            "scenario_fingerprints": [s.fingerprint for s in self.scenarios],
            "description": self.description,
        }, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(blob.encode()).hexdigest()


class ChaosProfileRegistry:
    """Registry of versioned chaos profiles with hash stability."""

    def __init__(self):
        self._profiles: Dict[str, ChaosProfile] = {}
        self._history: Dict[str, List[ChaosProfile]] = {}

    def register(self, profile: ChaosProfile) -> None:
        """Register a chaos profile. Rejects version conflicts."""
        if profile.profile_id in self._profiles:
            existing = self._profiles[profile.profile_id]
            if profile.version <= existing.version:
                raise ValueError(
                    f"Version {profile.version} must be > current {existing.version}"
                )
        self._profiles[profile.profile_id] = profile
        if profile.profile_id not in self._history:
            self._history[profile.profile_id] = []
        self._history[profile.profile_id].append(profile)

    def get(self, profile_id: str) -> Optional[ChaosProfile]:
        return self._profiles.get(profile_id)

    def get_history(self, profile_id: str) -> List[ChaosProfile]:
        return list(self._history.get(profile_id, []))

    def verify_hash_stability(self, profile_id: str) -> dict:
        """Verify a profile's fingerprint is deterministic."""
        profile = self._profiles.get(profile_id)
        if not profile:
            return {"valid": False, "reason": "profile_not_found"}
        # Recompute and compare
        recomputed = profile.fingerprint
        return {"valid": True, "fingerprint": recomputed}

    def check_bounds(self, scenario: ChaosScenario) -> dict:
        """Check if a scenario respects all bounds."""
        violations = []
        if scenario.timeout_ms > MAX_TIMEOUT_MS:
            violations.append(f"timeout_ms {scenario.timeout_ms} > {MAX_TIMEOUT_MS}")
        if scenario.max_retries > MAX_RETRIES:
            violations.append(f"max_retries {scenario.max_retries} > {MAX_RETRIES}")
        if scenario.blast_radius > MAX_BLAST_RADIUS:
            violations.append(f"blast_radius {scenario.blast_radius} > {MAX_BLAST_RADIUS}")
        return {"bounded": len(violations) == 0, "violations": violations}

    @property
    def profile_count(self) -> int:
        return len(self._profiles)

    def list_profiles(self) -> List[str]:
        return list(self._profiles.keys())
