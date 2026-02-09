"""
Identity Invariant Enforcement — v2.6 Track A

Ensures that exported training data does NOT hardcode identity facts that
belong in the system prompt / config layer. Conversations that leak identity
anchors into example content are flagged or stripped at export time.

Philosophy: "Sonia-ness" comes from fine-tuned *style* and *behavior*, not
from baking "My name is Sonia" into training examples. Identity facts
(name, wake word, persona anchors) must remain config-driven.
"""

from __future__ import annotations

import re
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional


# ---------------------------------------------------------------------------
# Default identity anchors (loaded from config or overridden)
# ---------------------------------------------------------------------------

DEFAULT_IDENTITY_ANCHORS = [
    # Name patterns
    r"\bmy name is sonia\b",
    r"\bi am sonia\b",
    r"\bi'm sonia\b",
    r"\bcall me sonia\b",
    r"\bsonia here\b",
    # Wake word patterns
    r"\bhey sonia\b",
    r"\bok sonia\b",
    r"\bsonia,?\s+(can you|please|help|what|tell|do)\b",
    # Persona anchors that should stay in system prompt
    r"\bi was (created|built|designed|made) by\b",
    r"\bmy (creator|developer|designer) is\b",
    r"\bi run on (the sonia|eva|openclaw)\b",
]


@dataclass
class InvariantViolation:
    """A single identity invariant violation."""
    conversation_index: int
    message_index: int
    role: str
    pattern_matched: str
    snippet: str  # surrounding context (truncated)


@dataclass
class InvariantReport:
    """Summary of enforcement across a dataset."""
    total_conversations: int = 0
    total_messages_scanned: int = 0
    violations: List[InvariantViolation] = field(default_factory=list)
    conversations_removed: int = 0
    conversations_passed: int = 0

    @property
    def violation_rate(self) -> float:
        if self.total_conversations == 0:
            return 0.0
        return len(self.violations) / self.total_conversations

    def to_dict(self) -> dict:
        return {
            "total_conversations": self.total_conversations,
            "total_messages_scanned": self.total_messages_scanned,
            "violation_count": len(self.violations),
            "conversations_removed": self.conversations_removed,
            "conversations_passed": self.conversations_passed,
            "violation_rate": round(self.violation_rate, 4),
            "violations": [
                {
                    "conv_idx": v.conversation_index,
                    "msg_idx": v.message_index,
                    "role": v.role,
                    "pattern": v.pattern_matched,
                    "snippet": v.snippet,
                }
                for v in self.violations
            ],
        }

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, indent=2, ensure_ascii=False)


class IdentityInvariantEnforcer:
    """
    Scans conversations for identity anchor leakage and either
    flags (audit mode) or removes (enforce mode) violating entries.
    """

    def __init__(
        self,
        anchor_patterns: Optional[List[str]] = None,
        mode: str = "enforce",  # "audit" or "enforce"
        scan_roles: tuple[str, ...] = ("assistant",),
    ):
        patterns = anchor_patterns or DEFAULT_IDENTITY_ANCHORS
        self.patterns = [re.compile(p, re.IGNORECASE) for p in patterns]
        self.pattern_sources = patterns
        self.mode = mode
        self.scan_roles = scan_roles

    def check_message(self, text: str) -> Optional[tuple[str, str]]:
        """Check a single message. Returns (pattern, snippet) or None."""
        for pat, src in zip(self.patterns, self.pattern_sources):
            match = pat.search(text)
            if match:
                start = max(0, match.start() - 30)
                end = min(len(text), match.end() + 30)
                snippet = text[start:end]
                return (src, snippet)
        return None

    def process(self, conversations: List[dict]) -> tuple[List[dict], InvariantReport]:
        """
        Scan all conversations. In enforce mode, remove violating ones.
        In audit mode, flag but keep all.
        Returns (filtered_conversations, report).
        """
        report = InvariantReport(total_conversations=len(conversations))
        passed: List[dict] = []
        violating_indices: set[int] = set()

        for conv_idx, conv in enumerate(conversations):
            messages = conv.get("messages", [])
            conv_clean = True
            for msg_idx, msg in enumerate(messages):
                report.total_messages_scanned += 1
                role = msg.get("role", "")
                if role not in self.scan_roles:
                    continue
                content = msg.get("content", "")
                if not isinstance(content, str):
                    continue
                result = self.check_message(content)
                if result:
                    pattern_src, snippet = result
                    report.violations.append(InvariantViolation(
                        conversation_index=conv_idx,
                        message_index=msg_idx,
                        role=role,
                        pattern_matched=pattern_src,
                        snippet=snippet,
                    ))
                    conv_clean = False
                    violating_indices.add(conv_idx)

            if conv_clean or self.mode == "audit":
                passed.append(conv)
            # In enforce mode, violating conversations are dropped

        report.conversations_removed = len(violating_indices) if self.mode == "enforce" else 0
        report.conversations_passed = len(passed)
        return passed, report


def load_config(config_path: Path) -> List[str]:
    """Load custom identity anchor patterns from a JSON config file."""
    with open(config_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return data.get("identity_anchors", DEFAULT_IDENTITY_ANCHORS)
