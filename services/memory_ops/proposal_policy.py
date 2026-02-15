"""Policy classifier for memory mutation proposals.

Classifies each proposal into a risk tier and determines approval
requirements. Every proposal gets a policy decision artifact — no
path writes to the ledger without classification.

Tiers:
    auto_low:       Ephemeral/system telemetry, low-risk summaries.
                    Auto-approved (PROPOSED -> APPROVED directly).
    guarded_medium: User preference updates, episodic inserts with
                    behavioral impact. Requires one-shot approval token.
    guarded_high:   Identity/core belief/persistent profile changes,
                    destructive edits/retractions. Requires approval.

Invariants:
    - Every proposal receives a PolicyDecision.
    - No write path bypasses classification.
    - Reason codes emitted on every decision.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from .proposal_model import (
    MemoryProposal,
    MemoryType,
    RiskTier,
)


# ── Policy decision artifact ────────────────────────────────────────

@dataclass(frozen=True)
class PolicyDecision:
    """Result of classifying a memory proposal."""
    proposal_id: str
    tier: RiskTier
    requires_approval: bool
    reason_code: str
    required_token_scope: str         # "none" | "session" | "operator"
    confidence_factor: float          # input confidence used in decision


# ── Classification rules ─────────────────────────────────────────────

# Memory types that are always auto_low
AUTO_LOW_TYPES = frozenset({
    MemoryType.SESSION_CONTEXT,
    MemoryType.SYSTEM_STATE,
})

# Memory types that are always guarded_high
GUARDED_HIGH_TYPES = frozenset({
    MemoryType.PREFERENCE,
})

# Confidence threshold: below this, even normally-auto types
# get elevated to guarded_medium
LOW_CONFIDENCE_THRESHOLD = 0.5

# High-confidence threshold for FACT/EPISODE to remain at medium
HIGH_CONFIDENCE_THRESHOLD = 0.85


def classify_proposal(proposal: MemoryProposal) -> PolicyDecision:
    """Classify a memory proposal into a risk tier.

    Decision logic:
        1. SESSION_CONTEXT, SYSTEM_STATE -> auto_low (unless low confidence)
        2. PREFERENCE -> guarded_high (always requires operator approval)
        3. FACT, EPISODE, PROJECT:
           - confidence >= 0.85 -> guarded_medium
           - confidence < 0.85  -> guarded_high
        4. Low confidence (< 0.5) on any type elevates by one tier

    Returns a PolicyDecision with all classification metadata.
    """
    mtype = proposal.memory_type
    conf = proposal.confidence

    # Rule 1: Auto-low types
    if mtype in AUTO_LOW_TYPES:
        if conf < LOW_CONFIDENCE_THRESHOLD:
            return PolicyDecision(
                proposal_id=proposal.proposal_id,
                tier=RiskTier.GUARDED_MEDIUM,
                requires_approval=True,
                reason_code="auto_type_low_confidence_elevated",
                required_token_scope="session",
                confidence_factor=conf,
            )
        return PolicyDecision(
            proposal_id=proposal.proposal_id,
            tier=RiskTier.AUTO_LOW,
            requires_approval=False,
            reason_code="auto_low_system_type",
            required_token_scope="none",
            confidence_factor=conf,
        )

    # Rule 2: Preference always guarded_high
    if mtype in GUARDED_HIGH_TYPES:
        return PolicyDecision(
            proposal_id=proposal.proposal_id,
            tier=RiskTier.GUARDED_HIGH,
            requires_approval=True,
            reason_code="preference_always_guarded_high",
            required_token_scope="operator",
            confidence_factor=conf,
        )

    # Rule 3: FACT, EPISODE, PROJECT
    if conf >= HIGH_CONFIDENCE_THRESHOLD:
        return PolicyDecision(
            proposal_id=proposal.proposal_id,
            tier=RiskTier.GUARDED_MEDIUM,
            requires_approval=True,
            reason_code="content_type_high_confidence",
            required_token_scope="session",
            confidence_factor=conf,
        )

    # Low confidence on content types -> guarded_high
    return PolicyDecision(
        proposal_id=proposal.proposal_id,
        tier=RiskTier.GUARDED_HIGH,
        requires_approval=True,
        reason_code="content_type_low_confidence_elevated",
        required_token_scope="operator",
        confidence_factor=conf,
    )
