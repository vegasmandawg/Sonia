"""
Stage 6 — Retry Taxonomy
Classifies action failures by root cause to drive retry policy,
dead letter routing, and operator triage.
"""

from enum import Enum
from typing import Optional


class FailureClass(str, Enum):
    """Failure classification buckets used across pipeline, DLQ, and metrics."""
    CONNECTION_BOOTSTRAP = "connection_bootstrap"   # Dep unreachable / DNS fail
    TIMEOUT = "timeout"                             # Execution exceeded budget
    CIRCUIT_OPEN = "circuit_open"                   # Breaker tripped
    POLICY_DENIED = "policy_denied"                 # Safety gate blocked
    VALIDATION_FAILED = "validation_failed"         # Pre-flight check failed
    EXECUTION_ERROR = "execution_error"             # Dep returned non-success
    BACKPRESSURE = "backpressure"                   # Rate limit / 429
    UNKNOWN = "unknown"                             # Unclassified


# ── Retry policy per failure class ─────────────────────────────────────────

RETRY_POLICY = {
    FailureClass.CONNECTION_BOOTSTRAP: {"retryable": True, "max_retries": 3, "backoff_base": 2.0},
    FailureClass.TIMEOUT:             {"retryable": True, "max_retries": 2, "backoff_base": 1.5},
    FailureClass.CIRCUIT_OPEN:        {"retryable": False, "max_retries": 0, "backoff_base": 0},
    FailureClass.POLICY_DENIED:       {"retryable": False, "max_retries": 0, "backoff_base": 0},
    FailureClass.VALIDATION_FAILED:   {"retryable": False, "max_retries": 0, "backoff_base": 0},
    FailureClass.EXECUTION_ERROR:     {"retryable": True, "max_retries": 2, "backoff_base": 1.5},
    FailureClass.BACKPRESSURE:        {"retryable": True, "max_retries": 3, "backoff_base": 3.0},
    FailureClass.UNKNOWN:             {"retryable": True, "max_retries": 1, "backoff_base": 2.0},
}


def classify_failure(
    error_code: Optional[str] = None,
    error_message: Optional[str] = None,
    status: Optional[str] = None,
    exception: Optional[Exception] = None,
) -> FailureClass:
    """
    Classify a failure into one of the taxonomy buckets.

    Accepts error_code (from pipeline), error_message, raw status strings,
    or an exception instance.  Checks are ordered from most-specific to
    least-specific so that the first match wins.
    """
    code = (error_code or "").upper()
    msg = (error_message or "").lower()
    exc_type = type(exception).__name__ if exception else ""

    # Circuit breaker
    if code == "CIRCUIT_OPEN" or "circuit breaker" in msg or exc_type == "CircuitOpenError":
        return FailureClass.CIRCUIT_OPEN

    # Policy / safety
    if code == "POLICY_DENIED" or "policy denied" in msg or "blocked" in msg:
        return FailureClass.POLICY_DENIED

    # Validation
    if code == "VALIDATION_FAILED" or status == "validation_failed":
        return FailureClass.VALIDATION_FAILED

    # Timeout
    if code == "TIMEOUT" or status == "timeout" or "timed out" in msg:
        return FailureClass.TIMEOUT

    # Backpressure / rate limit
    if "429" in code or "rate limit" in msg or "too many" in msg or code == "BACKPRESSURE":
        return FailureClass.BACKPRESSURE

    # Connection / bootstrap
    if any(kw in msg for kw in ("connection refused", "dns", "unreachable",
                                  "connect timeout", "connection reset",
                                  "no route to host")):
        return FailureClass.CONNECTION_BOOTSTRAP
    if exc_type in ("ConnectionError", "ConnectError", "OSError", "ConnectionRefusedError"):
        return FailureClass.CONNECTION_BOOTSTRAP

    # Generic execution error
    if code in ("EXECUTION_FAILED", "INTERNAL_ERROR") or status == "error":
        return FailureClass.EXECUTION_ERROR

    # Catch-all
    if code or msg or exception:
        return FailureClass.UNKNOWN

    return FailureClass.UNKNOWN


def is_retryable(fc: FailureClass) -> bool:
    """Check whether a failure class is eligible for retry."""
    return RETRY_POLICY.get(fc, {}).get("retryable", False)


def get_retry_budget(fc: FailureClass) -> int:
    """Return the max retries for a given failure class."""
    return RETRY_POLICY.get(fc, {}).get("max_retries", 0)


def get_backoff_base(fc: FailureClass) -> float:
    """Return the backoff base multiplier for a given failure class."""
    return RETRY_POLICY.get(fc, {}).get("backoff_base", 1.5)
