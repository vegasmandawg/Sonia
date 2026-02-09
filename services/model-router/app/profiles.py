"""
Model Router - Routing Profiles

Deterministic, auditable routing profiles for request classification.
Each profile defines model preferences, latency/context budgets,
allowed fallbacks, and retry policy.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Set

logger = logging.getLogger("model-router.profiles")


# ---------------------------------------------------------------------------
# Profile identifiers
# ---------------------------------------------------------------------------

class ProfileName(str, Enum):
    """Canonical routing profile identifiers."""
    CHAT_LOW_LATENCY   = "chat_low_latency"
    REASONING_DEEP     = "reasoning_deep"
    VISION_ANALYSIS    = "vision_analysis"
    MEMORY_OPS         = "memory_ops"
    TOOL_EXECUTION     = "tool_execution"
    SAFE_FALLBACK      = "safe_fallback"


# ---------------------------------------------------------------------------
# Reason codes (why a particular backend was selected/skipped)
# ---------------------------------------------------------------------------

class ReasonCode(str, Enum):
    """Deterministic reason codes for every routing decision."""
    PROFILE_MATCH           = "PROFILE_MATCH"
    FALLBACK_USED           = "FALLBACK_USED"
    BACKEND_UNHEALTHY       = "BACKEND_UNHEALTHY"
    BACKEND_QUARANTINED     = "BACKEND_QUARANTINED"
    BUDGET_EXCEEDED_LATENCY = "BUDGET_EXCEEDED_LATENCY"
    BUDGET_EXCEEDED_CONTEXT = "BUDGET_EXCEEDED_CONTEXT"
    NO_BACKEND_AVAILABLE    = "NO_BACKEND_AVAILABLE"
    DOWNGRADED              = "DOWNGRADED"
    DEFAULT_PROFILE         = "DEFAULT_PROFILE"


# ---------------------------------------------------------------------------
# Retry policy
# ---------------------------------------------------------------------------

@dataclass
class RetryPolicy:
    """Retry and backoff configuration for a profile."""
    max_retries: int = 1
    backoff_base_ms: int = 500
    backoff_max_ms: int = 5000
    backoff_multiplier: float = 2.0

    def delay_ms(self, attempt: int) -> int:
        """Calculate delay for a given attempt (0-indexed)."""
        raw = self.backoff_base_ms * (self.backoff_multiplier ** attempt)
        return int(min(raw, self.backoff_max_ms))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "max_retries": self.max_retries,
            "backoff_base_ms": self.backoff_base_ms,
            "backoff_max_ms": self.backoff_max_ms,
            "backoff_multiplier": self.backoff_multiplier,
        }


# ---------------------------------------------------------------------------
# Routing profile
# ---------------------------------------------------------------------------

@dataclass
class RoutingProfile:
    """
    A routing profile defines deterministic dispatch rules for a class
    of requests.

    Fields
    ------
    name            Canonical profile identifier
    model_prefs     Ordered list of backend/model keys tried in sequence
    latency_ms      Max acceptable latency before downgrade/reject
    max_context     Max input tokens before downgrade/reject
    fallbacks       Ordered fallback model keys after primary list exhausted
    retry           Retry/backoff policy
    capabilities    Required capabilities the backend must advertise
    """
    name: ProfileName
    model_prefs: List[str] = field(default_factory=list)
    latency_ms: int = 10_000
    max_context: int = 8_000
    fallbacks: List[str] = field(default_factory=list)
    retry: RetryPolicy = field(default_factory=RetryPolicy)
    capabilities: Set[str] = field(default_factory=lambda: {"text"})

    # ---- validation -------------------------------------------------------

    def validate(self) -> List[str]:
        """Return list of validation errors (empty == valid)."""
        errors: List[str] = []
        if not self.model_prefs and not self.fallbacks:
            errors.append(f"{self.name.value}: no model_prefs or fallbacks")
        if self.latency_ms <= 0:
            errors.append(f"{self.name.value}: latency_ms must be > 0")
        if self.max_context <= 0:
            errors.append(f"{self.name.value}: max_context must be > 0")
        if self.retry.max_retries < 0:
            errors.append(f"{self.name.value}: max_retries must be >= 0")
        return errors

    # ---- full dispatch chain (prefs + fallbacks) --------------------------

    def dispatch_chain(self) -> List[str]:
        """Return the full ordered list of backends to try."""
        return list(self.model_prefs) + [
            fb for fb in self.fallbacks if fb not in self.model_prefs
        ]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name.value,
            "model_prefs": list(self.model_prefs),
            "latency_ms": self.latency_ms,
            "max_context": self.max_context,
            "fallbacks": list(self.fallbacks),
            "retry": self.retry.to_dict(),
            "capabilities": sorted(self.capabilities),
        }


# ---------------------------------------------------------------------------
# Request classifier
# ---------------------------------------------------------------------------

# Patterns used by the classifier to map incoming request hints to profiles.
_CLASSIFY_PATTERNS: List[tuple[re.Pattern, ProfileName]] = [
    (re.compile(r"(?i)vision|image|screenshot|photo"), ProfileName.VISION_ANALYSIS),
    (re.compile(r"(?i)reason|think|analyz|deep|chain.of.thought"), ProfileName.REASONING_DEEP),
    (re.compile(r"(?i)tool|execute|action|shell|file\.write"), ProfileName.TOOL_EXECUTION),
    (re.compile(r"(?i)memory|remember|recall|ledger|knowledge"), ProfileName.MEMORY_OPS),
    (re.compile(r"(?i)quick|fast|chat|greet|hello|small.talk"), ProfileName.CHAT_LOW_LATENCY),
]


def classify_request(
    task_type: str = "",
    hint: str = "",
    context_tokens: int = 0,
) -> ProfileName:
    """
    Classify an incoming request to a profile name.

    Deterministic: same inputs always yield the same profile.
    Priority: explicit task_type patterns > hint patterns > default.
    """
    combined = f"{task_type} {hint}".strip()

    for pattern, profile in _CLASSIFY_PATTERNS:
        if pattern.search(combined):
            return profile

    # Default: low-latency chat for unclassified requests
    return ProfileName.CHAT_LOW_LATENCY


# ---------------------------------------------------------------------------
# Default profile catalogue
# ---------------------------------------------------------------------------

def default_profiles() -> Dict[ProfileName, RoutingProfile]:
    """
    Return the built-in profile catalogue.

    The model keys reference identifiers in the provider registry
    (e.g., "ollama/qwen2:7b", "anthropic/claude-opus-4-6").
    """
    return {
        ProfileName.CHAT_LOW_LATENCY: RoutingProfile(
            name=ProfileName.CHAT_LOW_LATENCY,
            model_prefs=["ollama/qwen2:7b"],
            latency_ms=3_000,
            max_context=4_000,
            fallbacks=["ollama/qwen2:1.5b"],
            retry=RetryPolicy(max_retries=1, backoff_base_ms=200),
            capabilities={"text"},
        ),
        ProfileName.REASONING_DEEP: RoutingProfile(
            name=ProfileName.REASONING_DEEP,
            model_prefs=["anthropic/claude-opus-4-6", "anthropic/claude-sonnet-4-6"],
            latency_ms=30_000,
            max_context=32_000,
            fallbacks=["ollama/qwen2:7b"],
            retry=RetryPolicy(max_retries=2, backoff_base_ms=1000),
            capabilities={"text"},
        ),
        ProfileName.VISION_ANALYSIS: RoutingProfile(
            name=ProfileName.VISION_ANALYSIS,
            model_prefs=["ollama/qwen2-vl:7b"],
            latency_ms=15_000,
            max_context=8_000,
            fallbacks=["anthropic/claude-sonnet-4-6"],
            retry=RetryPolicy(max_retries=1, backoff_base_ms=500),
            capabilities={"text", "vision"},
        ),
        ProfileName.MEMORY_OPS: RoutingProfile(
            name=ProfileName.MEMORY_OPS,
            model_prefs=["ollama/qwen2:7b"],
            latency_ms=5_000,
            max_context=8_000,
            fallbacks=["ollama/qwen2:1.5b"],
            retry=RetryPolicy(max_retries=1, backoff_base_ms=300),
            capabilities={"text"},
        ),
        ProfileName.TOOL_EXECUTION: RoutingProfile(
            name=ProfileName.TOOL_EXECUTION,
            model_prefs=["ollama/qwen2:7b", "anthropic/claude-sonnet-4-6"],
            latency_ms=10_000,
            max_context=8_000,
            fallbacks=["ollama/qwen2:1.5b"],
            retry=RetryPolicy(max_retries=2, backoff_base_ms=500),
            capabilities={"text"},
        ),
        ProfileName.SAFE_FALLBACK: RoutingProfile(
            name=ProfileName.SAFE_FALLBACK,
            model_prefs=["ollama/qwen2:1.5b", "ollama/qwen2:7b"],
            latency_ms=5_000,
            max_context=2_000,
            fallbacks=[],
            retry=RetryPolicy(max_retries=0),
            capabilities={"text"},
        ),
    }


# ---------------------------------------------------------------------------
# Profile registry (runtime container)
# ---------------------------------------------------------------------------

class ProfileRegistry:
    """
    Runtime registry holding validated routing profiles.

    Thread-safe for reads; mutations (add/remove) are infrequent
    and happen at startup or config reload.
    """

    def __init__(self, profiles: Optional[Dict[ProfileName, RoutingProfile]] = None):
        self._profiles: Dict[ProfileName, RoutingProfile] = {}
        self._validation_errors: List[str] = []

        source = profiles if profiles is not None else default_profiles()
        for prof in source.values():
            self.add(prof)

    # ---- mutation ---------------------------------------------------------

    def add(self, profile: RoutingProfile) -> List[str]:
        """Add or replace a profile.  Returns validation errors (if any)."""
        errors = profile.validate()
        if errors:
            self._validation_errors.extend(errors)
            logger.warning("Profile %s has validation errors: %s",
                           profile.name.value, errors)
        self._profiles[profile.name] = profile
        return errors

    def remove(self, name: ProfileName) -> bool:
        """Remove a profile.  Returns True if it existed."""
        return self._profiles.pop(name, None) is not None

    # ---- lookup -----------------------------------------------------------

    def get(self, name: ProfileName) -> Optional[RoutingProfile]:
        """Retrieve a profile by name."""
        return self._profiles.get(name)

    def get_or_fallback(self, name: ProfileName) -> RoutingProfile:
        """Retrieve profile or return SAFE_FALLBACK."""
        return self._profiles.get(name) or self._profiles[ProfileName.SAFE_FALLBACK]

    @property
    def names(self) -> List[str]:
        return [p.value for p in self._profiles]

    @property
    def validation_errors(self) -> List[str]:
        return list(self._validation_errors)

    # ---- diagnostics ------------------------------------------------------

    def to_dict(self) -> Dict[str, Any]:
        return {
            "profiles": {p.value: prof.to_dict()
                         for p, prof in self._profiles.items()},
            "validation_errors": list(self._validation_errors),
        }
