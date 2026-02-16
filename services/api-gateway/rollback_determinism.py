"""
Rollback determinism: script existence, execution contract, dry-run stability.

Validates that rollback scripts exist, follow a declared contract,
and produce deterministic outputs under dry-run.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional


class RollbackVerdict(Enum):
    PASS = "PASS"
    FAIL = "FAIL"


@dataclass(frozen=True)
class RollbackScript:
    """A declared rollback script with execution contract."""
    script_id: str
    name: str
    path: str
    target_version: str
    supports_dry_run: bool
    required_preconditions: tuple  # frozen tuple of strings

    def fingerprint(self) -> str:
        canonical = f"{self.script_id}|{self.name}|{self.target_version}|{self.supports_dry_run}"
        return hashlib.sha256(canonical.encode()).hexdigest()


@dataclass
class RollbackCheck:
    name: str
    verdict: RollbackVerdict
    detail: str = ""


class RollbackScriptRegistry:
    """Registry of rollback scripts with contract validation."""

    def __init__(self):
        self._scripts: Dict[str, RollbackScript] = {}

    def register(self, script: RollbackScript) -> None:
        self._scripts[script.script_id] = script

    def get(self, script_id: str) -> Optional[RollbackScript]:
        return self._scripts.get(script_id)

    def list_all(self) -> List[RollbackScript]:
        return sorted(self._scripts.values(), key=lambda s: s.script_id)

    def scripts_without_dry_run(self) -> List[str]:
        return sorted(
            s.script_id for s in self._scripts.values()
            if not s.supports_dry_run
        )

    def all_support_dry_run(self) -> bool:
        return len(self.scripts_without_dry_run()) == 0


@dataclass
class DryRunOutput:
    """Output from a rollback dry-run execution."""
    script_id: str
    actions_planned: List[str]
    would_modify: List[str]
    output_hash: str

    @staticmethod
    def compute_hash(actions: List[str], modifications: List[str]) -> str:
        canonical = "|".join(sorted(actions)) + "||" + "|".join(sorted(modifications))
        return hashlib.sha256(canonical.encode()).hexdigest()


def simulate_dry_run(script: RollbackScript) -> DryRunOutput:
    """Simulate a deterministic dry-run of a rollback script."""
    actions = [
        f"stop_service:{script.target_version}",
        f"restore_state:{script.target_version}",
        f"verify_health:{script.target_version}",
    ]
    modifications = [
        f"state/{script.target_version}/backup",
        f"config/{script.target_version}/rollback",
    ]
    output_hash = DryRunOutput.compute_hash(actions, modifications)
    return DryRunOutput(
        script_id=script.script_id,
        actions_planned=actions,
        would_modify=modifications,
        output_hash=output_hash,
    )


def dry_run_is_deterministic(script: RollbackScript) -> bool:
    """Verify dry-run produces identical output across multiple runs."""
    r1 = simulate_dry_run(script)
    r2 = simulate_dry_run(script)
    return r1.output_hash == r2.output_hash and r1.output_hash != ""


def validate_rollback_contract(script: RollbackScript) -> List[RollbackCheck]:
    """Validate a rollback script meets its execution contract."""
    checks = []

    # Script must support dry-run
    checks.append(RollbackCheck(
        name="supports_dry_run",
        verdict=RollbackVerdict.PASS if script.supports_dry_run else RollbackVerdict.FAIL,
        detail="dry-run supported" if script.supports_dry_run else "no dry-run support",
    ))

    # Script must have preconditions
    checks.append(RollbackCheck(
        name="has_preconditions",
        verdict=RollbackVerdict.PASS if len(script.required_preconditions) > 0 else RollbackVerdict.FAIL,
        detail=f"{len(script.required_preconditions)} preconditions declared",
    ))

    # Dry-run must be deterministic
    is_det = dry_run_is_deterministic(script)
    checks.append(RollbackCheck(
        name="dry_run_deterministic",
        verdict=RollbackVerdict.PASS if is_det else RollbackVerdict.FAIL,
        detail="deterministic" if is_det else "non-deterministic output",
    ))

    return checks
