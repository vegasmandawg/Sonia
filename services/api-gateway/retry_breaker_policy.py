"""Retry/Breaker Policy — v4.2 E2.

Enforces deterministic retry taxonomy, breaker FSM transitions,
and fallback behaviour under fault conditions.
"""
import hashlib
import json
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Set, Tuple

SCHEMA_VERSION = "1.0.0"


# --- Retry Taxonomy ---

class FailureClass(Enum):
    CONNECTION_BOOTSTRAP = "connection_bootstrap"
    TIMEOUT = "timeout"
    CIRCUIT_OPEN = "circuit_open"
    POLICY_DENIED = "policy_denied"
    VALIDATION_FAILED = "validation_failed"
    EXECUTION_ERROR = "execution_error"
    BACKPRESSURE = "backpressure"
    UNKNOWN = "unknown"

ALL_FAILURE_CLASSES = frozenset(fc.value for fc in FailureClass)


class RetryDecision(Enum):
    RETRY = "retry"
    NO_RETRY = "no_retry"
    ESCALATE = "escalate"


@dataclass(frozen=True)
class RetryPolicy:
    """Policy for a specific failure class."""
    failure_class: FailureClass
    max_attempts: int
    backoff_base_ms: int
    retryable: bool

    def __post_init__(self):
        if self.max_attempts < 0:
            raise ValueError("max_attempts must be non-negative")
        if self.backoff_base_ms < 0:
            raise ValueError("backoff_base_ms must be non-negative")


# Default taxonomy: complete mapping for all 8 classes
DEFAULT_RETRY_TAXONOMY: Dict[FailureClass, RetryPolicy] = {
    FailureClass.CONNECTION_BOOTSTRAP: RetryPolicy(FailureClass.CONNECTION_BOOTSTRAP, 3, 1000, True),
    FailureClass.TIMEOUT: RetryPolicy(FailureClass.TIMEOUT, 2, 2000, True),
    FailureClass.CIRCUIT_OPEN: RetryPolicy(FailureClass.CIRCUIT_OPEN, 0, 0, False),
    FailureClass.POLICY_DENIED: RetryPolicy(FailureClass.POLICY_DENIED, 0, 0, False),
    FailureClass.VALIDATION_FAILED: RetryPolicy(FailureClass.VALIDATION_FAILED, 0, 0, False),
    FailureClass.EXECUTION_ERROR: RetryPolicy(FailureClass.EXECUTION_ERROR, 1, 500, True),
    FailureClass.BACKPRESSURE: RetryPolicy(FailureClass.BACKPRESSURE, 3, 3000, True),
    FailureClass.UNKNOWN: RetryPolicy(FailureClass.UNKNOWN, 1, 1000, True),
}


class RetryTaxonomyPolicy:
    """Deterministic retry classification and decision engine."""

    def __init__(self, taxonomy: Optional[Dict[FailureClass, RetryPolicy]] = None):
        self._taxonomy = taxonomy or dict(DEFAULT_RETRY_TAXONOMY)

    def classify(self, failure_class_name: str) -> Optional[FailureClass]:
        """Classify a failure by name. Returns None for unknown names."""
        try:
            return FailureClass(failure_class_name)
        except ValueError:
            return None

    def get_policy(self, fc: FailureClass) -> RetryPolicy:
        """Get the retry policy for a failure class."""
        if fc not in self._taxonomy:
            raise ValueError(f"No policy for failure class: {fc.value}")
        return self._taxonomy[fc]

    def decide(self, failure_class_name: str, attempt: int) -> dict:
        """Make a deterministic retry decision.

        Same failure_class + attempt always produces the same result.
        """
        fc = self.classify(failure_class_name)
        if fc is None:
            return {
                "decision": RetryDecision.ESCALATE.value,
                "reason": f"unknown_failure_class: {failure_class_name}",
                "retryable": False,
            }
        policy = self._taxonomy[fc]
        if not policy.retryable:
            return {
                "decision": RetryDecision.NO_RETRY.value,
                "reason": f"{fc.value} is non-retryable",
                "retryable": False,
            }
        if attempt >= policy.max_attempts:
            return {
                "decision": RetryDecision.ESCALATE.value,
                "reason": f"exceeded max_attempts={policy.max_attempts}",
                "retryable": True,
            }
        return {
            "decision": RetryDecision.RETRY.value,
            "reason": f"attempt {attempt}/{policy.max_attempts}",
            "retryable": True,
            "backoff_ms": policy.backoff_base_ms * (2 ** attempt),
        }

    def check_completeness(self) -> dict:
        """Verify taxonomy covers all failure classes."""
        covered = set(self._taxonomy.keys())
        expected = set(FailureClass)
        missing = expected - covered
        return {
            "complete": len(missing) == 0,
            "covered": len(covered),
            "expected": len(expected),
            "missing": [fc.value for fc in missing],
        }


# --- Breaker FSM ---

class BreakerState(Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


# Valid transitions
VALID_TRANSITIONS: Dict[BreakerState, Set[BreakerState]] = {
    BreakerState.CLOSED: {BreakerState.OPEN},
    BreakerState.OPEN: {BreakerState.HALF_OPEN},
    BreakerState.HALF_OPEN: {BreakerState.CLOSED, BreakerState.OPEN},
}


class BreakerFSM:
    """Deterministic circuit breaker finite state machine."""

    def __init__(self, name: str, failure_threshold: int = 3, success_threshold: int = 1):
        if not name:
            raise ValueError("name must be non-empty")
        if failure_threshold < 1:
            raise ValueError("failure_threshold must be >= 1")
        self.name = name
        self.failure_threshold = failure_threshold
        self.success_threshold = success_threshold
        self._state = BreakerState.CLOSED
        self._failure_count = 0
        self._success_count = 0
        self._transition_log: List[dict] = []

    @property
    def state(self) -> BreakerState:
        return self._state

    def _transition(self, target: BreakerState) -> bool:
        """Attempt a state transition. Returns True if valid."""
        if target not in VALID_TRANSITIONS.get(self._state, set()):
            return False
        old = self._state
        self._state = target
        self._transition_log.append({
            "from": old.value,
            "to": target.value,
        })
        return True

    def record_failure(self) -> dict:
        """Record a failure. Deterministic state transitions."""
        if self._state == BreakerState.CLOSED:
            self._failure_count += 1
            if self._failure_count >= self.failure_threshold:
                self._transition(BreakerState.OPEN)
                self._failure_count = 0
                return {"state": self._state.value, "tripped": True}
            return {"state": self._state.value, "tripped": False}
        elif self._state == BreakerState.HALF_OPEN:
            self._transition(BreakerState.OPEN)
            self._success_count = 0
            return {"state": self._state.value, "tripped": True}
        return {"state": self._state.value, "tripped": False}

    def record_success(self) -> dict:
        """Record a success. Deterministic state transitions."""
        if self._state == BreakerState.HALF_OPEN:
            self._success_count += 1
            if self._success_count >= self.success_threshold:
                self._transition(BreakerState.CLOSED)
                self._success_count = 0
                return {"state": self._state.value, "recovered": True}
            return {"state": self._state.value, "recovered": False}
        return {"state": self._state.value, "recovered": False}

    def attempt_reset(self) -> dict:
        """Attempt to move from OPEN to HALF_OPEN."""
        if self._state != BreakerState.OPEN:
            return {"transitioned": False, "state": self._state.value}
        ok = self._transition(BreakerState.HALF_OPEN)
        return {"transitioned": ok, "state": self._state.value}

    def check_transition_validity(self, from_state: str, to_state: str) -> bool:
        """Check if a transition is valid per FSM rules."""
        try:
            src = BreakerState(from_state)
            dst = BreakerState(to_state)
        except ValueError:
            return False
        return dst in VALID_TRANSITIONS.get(src, set())

    @property
    def transition_log(self) -> List[dict]:
        return list(self._transition_log)


# --- Fallback ---

@dataclass(frozen=True)
class FallbackEnvelope:
    """Envelope wrapping a fallback response under fault conditions."""
    original_action: str
    fallback_action: str
    failure_class: str
    is_degraded: bool

    def __post_init__(self):
        if not self.original_action:
            raise ValueError("original_action must be non-empty")
        if not self.fallback_action:
            raise ValueError("fallback_action must be non-empty")
        if not self.failure_class:
            raise ValueError("failure_class must be non-empty")

    @property
    def fingerprint(self) -> str:
        blob = json.dumps({
            "original_action": self.original_action,
            "fallback_action": self.fallback_action,
            "failure_class": self.failure_class,
            "is_degraded": self.is_degraded,
        }, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(blob.encode()).hexdigest()


def validate_fallback_envelope(envelope: FallbackEnvelope) -> dict:
    """Validate a fallback envelope's contract."""
    issues = []
    if envelope.original_action == envelope.fallback_action:
        issues.append("fallback_action must differ from original_action")
    if not envelope.is_degraded:
        issues.append("fallback must be marked as degraded")
    fc = None
    try:
        fc = FailureClass(envelope.failure_class)
    except ValueError:
        issues.append(f"unknown failure_class: {envelope.failure_class}")
    return {
        "valid": len(issues) == 0,
        "issues": issues,
        "failure_class_recognized": fc is not None,
    }
