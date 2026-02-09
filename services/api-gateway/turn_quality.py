"""
API Gateway — Turn Quality Controls (Stage 4)

Response policy enforcement, normalization, and quality annotations.
"""

import re
import logging
from typing import Optional

from schemas.vision import ResponsePolicy, QualityAnnotations

logger = logging.getLogger("api-gateway.turn_quality")

# Unsafe control tokens to strip from assistant output
_UNSAFE_CONTROL_RE = re.compile(
    r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]"      # C0 controls (keep \t \n \r)
)

DEFAULT_POLICY = ResponsePolicy()


def normalize_response(text: str, policy: Optional[ResponsePolicy] = None) -> str:
    """
    Trim unsafe control tokens and enforce max_output_chars.
    """
    pol = policy or DEFAULT_POLICY
    cleaned = _UNSAFE_CONTROL_RE.sub("", text)
    if len(cleaned) > pol.max_output_chars:
        cleaned = cleaned[: pol.max_output_chars]
    return cleaned.strip()


def enforce_non_empty(
    text: str,
    policy: Optional[ResponsePolicy] = None,
) -> str:
    """If disallow_empty_response, provide a minimal fallback."""
    pol = policy or DEFAULT_POLICY
    if pol.disallow_empty_response and not text.strip():
        return "(No response generated)"
    return text


def should_use_fallback(
    primary_failed: bool,
    policy: Optional[ResponsePolicy] = None,
) -> bool:
    """Return True if we should retry with the fallback profile."""
    pol = policy or DEFAULT_POLICY
    return primary_failed and pol.fallback_on_model_timeout


def build_annotations(
    profile_used: str = "chat_low_latency",
    fallback_used: bool = False,
    tool_calls_attempted: int = 0,
    tool_calls_executed: int = 0,
    completion_reason: str = "ok",
) -> dict:
    """Build quality annotation dict for inclusion in response payloads."""
    return QualityAnnotations(
        generation_profile_used=profile_used,
        fallback_used=fallback_used,
        tool_calls_attempted=tool_calls_attempted,
        tool_calls_executed=tool_calls_executed,
        completion_reason=completion_reason,
    ).dict()
