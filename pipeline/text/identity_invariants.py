"""
Identity Invariant Enforcement -- v2.6 Track A (production-hardened)

Ensures exported training data does NOT hardcode identity facts that
belong in the system prompt / config layer. Three severity levels:
  CRITICAL - hard fail, zero tolerance (e.g., "my name is sonia")
  MAJOR    - threshold fail (configurable count before export blocked)
  MINOR    - warn only, logged but never blocks

Modes:
  audit   - flag all violations, keep all conversations, return report
  enforce - remove violating conversations, fail export if thresholds breached

Record-level reason codes on every violation for downstream traceability.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Dict, List, Optional, Tuple


# ---------------------------------------------------------------------------
# Severity levels
# ---------------------------------------------------------------------------

class Severity(str, Enum):
    CRITICAL = "CRITICAL"  # zero tolerance
    MAJOR = "MAJOR"        # threshold-based
    MINOR = "MINOR"        # warn only


# ---------------------------------------------------------------------------
# Default anchors with severity
# ---------------------------------------------------------------------------

@dataclass
class AnchorRule:
    """A single identity anchor pattern with severity and reason code."""
    pattern: str
    severity: Severity
    reason_code: str
    description: str = ""


DEFAULT_ANCHOR_RULES: List[AnchorRule] = [
    # CRITICAL: direct identity claims
    AnchorRule(r"\bmy name is sonia\b", Severity.CRITICAL, "IDENTITY_NAME_CLAIM",
               "Assistant claims to be named Sonia (must stay in system prompt)"),
    AnchorRule(r"\bi am sonia\b", Severity.CRITICAL, "IDENTITY_NAME_CLAIM",
               "Assistant claims to be Sonia"),
    AnchorRule(r"\bi'm sonia\b", Severity.CRITICAL, "IDENTITY_NAME_CLAIM",
               "Assistant claims to be Sonia (contraction)"),
    AnchorRule(r"\bcall me sonia\b", Severity.CRITICAL, "IDENTITY_NAME_CLAIM",
               "Assistant requests to be called Sonia"),

    # MAJOR: wake word / invocation patterns
    AnchorRule(r"\bhey sonia\b", Severity.MAJOR, "WAKE_WORD_LEAK",
               "Wake word pattern in training data"),
    AnchorRule(r"\bok sonia\b", Severity.MAJOR, "WAKE_WORD_LEAK",
               "Wake word pattern in training data"),
    AnchorRule(r"\bsonia,?\s+(can you|please|help|what|tell|do)\b", Severity.MAJOR, "WAKE_WORD_LEAK",
               "Wake word + command pattern"),

    # MAJOR: creator / platform claims
    AnchorRule(r"\bi was (created|built|designed|made) by\b", Severity.MAJOR, "CREATOR_CLAIM",
               "Assistant claims specific creator"),
    AnchorRule(r"\bmy (creator|developer|designer) is\b", Severity.MAJOR, "CREATOR_CLAIM",
               "Assistant names specific creator"),
    AnchorRule(r"\bi run on (the sonia|eva|openclaw)\b", Severity.MAJOR, "PLATFORM_CLAIM",
               "Assistant claims specific platform"),

    # MINOR: soft identity hints (useful to monitor but not block)
    AnchorRule(r"\bsonia here\b", Severity.MINOR, "SOFT_IDENTITY_HINT",
               "Soft identity hint in greeting"),
    AnchorRule(r"\bas sonia\b", Severity.MINOR, "SOFT_IDENTITY_HINT",
               "Self-reference as Sonia"),
    AnchorRule(r"\bsonia('s| is) (purpose|goal|mission)\b", Severity.MINOR, "SOFT_IDENTITY_HINT",
               "Meta-reference to Sonia's purpose"),
]


# ---------------------------------------------------------------------------
# Violation record
# ---------------------------------------------------------------------------

@dataclass
class InvariantViolation:
    """A single identity invariant violation with record-level reason code."""
    conversation_index: int
    message_index: int
    role: str
    severity: Severity
    reason_code: str
    pattern_matched: str
    snippet: str
    description: str = ""


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------

@dataclass
class InvariantReport:
    """Summary of enforcement across a dataset."""
    mode: str = "enforce"
    total_conversations: int = 0
    total_messages_scanned: int = 0
    violations: List[InvariantViolation] = field(default_factory=list)
    conversations_removed: int = 0
    conversations_passed: int = 0
    severity_counts: Dict[str, int] = field(default_factory=lambda: {
        "CRITICAL": 0, "MAJOR": 0, "MINOR": 0,
    })
    threshold_breach: bool = False
    breach_details: List[str] = field(default_factory=list)

    @property
    def violation_rate(self) -> float:
        if self.total_conversations == 0:
            return 0.0
        return len(self.violations) / self.total_conversations

    def to_dict(self) -> dict:
        return {
            "mode": self.mode,
            "total_conversations": self.total_conversations,
            "total_messages_scanned": self.total_messages_scanned,
            "violation_count": len(self.violations),
            "conversations_removed": self.conversations_removed,
            "conversations_passed": self.conversations_passed,
            "violation_rate": round(self.violation_rate, 4),
            "severity_counts": dict(self.severity_counts),
            "threshold_breach": self.threshold_breach,
            "breach_details": self.breach_details,
            "violations": [
                {
                    "conv_idx": v.conversation_index,
                    "msg_idx": v.message_index,
                    "role": v.role,
                    "severity": v.severity.value,
                    "reason_code": v.reason_code,
                    "pattern": v.pattern_matched,
                    "snippet": v.snippet,
                    "description": v.description,
                }
                for v in self.violations
            ],
        }

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, indent=2, ensure_ascii=False)


# ---------------------------------------------------------------------------
# Enforcer
# ---------------------------------------------------------------------------

class IdentityInvariantEnforcer:
    """
    Scans conversations for identity anchor leakage.
    audit mode: flag but keep all.
    enforce mode: remove violating conversations, fail if thresholds breached.
    """

    def __init__(
        self,
        rules: Optional[List[AnchorRule]] = None,
        mode: str = "enforce",
        scan_roles: Tuple[str, ...] = ("assistant",),
        severity_thresholds: Optional[Dict[str, int]] = None,
    ):
        self.rules = rules or DEFAULT_ANCHOR_RULES
        self.compiled = [
            (re.compile(r.pattern, re.IGNORECASE), r)
            for r in self.rules
        ]
        self.mode = mode
        self.scan_roles = scan_roles
        self.thresholds = severity_thresholds or {
            "CRITICAL": 0,   # zero tolerance
            "MAJOR": 5,      # up to 5
            "MINOR": -1,     # unlimited
        }

    def check_message(self, text: str) -> List[Tuple[AnchorRule, str]]:
        """Check a single message. Returns list of (rule, snippet) matches."""
        matches: List[Tuple[AnchorRule, str]] = []
        for compiled_pat, rule in self.compiled:
            match = compiled_pat.search(text)
            if match:
                start = max(0, match.start() - 40)
                end = min(len(text), match.end() + 40)
                snippet = text[start:end]
                matches.append((rule, snippet))
        return matches

    def process(
        self, conversations: List[dict],
    ) -> Tuple[List[dict], InvariantReport]:
        """
        Scan all conversations.
        enforce mode: remove violating, check thresholds.
        audit mode: flag but keep all.
        Returns (filtered_conversations, report).
        """
        report = InvariantReport(
            mode=self.mode,
            total_conversations=len(conversations),
        )
        passed: List[dict] = []
        violating_indices: set = set()

        for conv_idx, conv in enumerate(conversations):
            messages = conv.get("messages", [])
            conv_violations: List[InvariantViolation] = []

            for msg_idx, msg in enumerate(messages):
                report.total_messages_scanned += 1
                role = msg.get("role", "")
                if role not in self.scan_roles:
                    continue
                content = msg.get("content", "")
                if not isinstance(content, str):
                    continue

                matches = self.check_message(content)
                for rule, snippet in matches:
                    violation = InvariantViolation(
                        conversation_index=conv_idx,
                        message_index=msg_idx,
                        role=role,
                        severity=rule.severity,
                        reason_code=rule.reason_code,
                        pattern_matched=rule.pattern,
                        snippet=snippet,
                        description=rule.description,
                    )
                    conv_violations.append(violation)
                    report.violations.append(violation)
                    report.severity_counts[rule.severity.value] += 1

            if conv_violations:
                violating_indices.add(conv_idx)

            if not conv_violations or self.mode == "audit":
                passed.append(conv)

        report.conversations_removed = len(violating_indices) if self.mode == "enforce" else 0
        report.conversations_passed = len(passed)

        # Check thresholds
        for sev_name, threshold in self.thresholds.items():
            if threshold < 0:
                continue  # -1 means unlimited
            count = report.severity_counts.get(sev_name, 0)
            if count > threshold:
                report.threshold_breach = True
                report.breach_details.append(
                    f"{sev_name}: {count} violation(s) exceeds threshold of {threshold}"
                )

        return passed, report


# ---------------------------------------------------------------------------
# Test fixtures
# ---------------------------------------------------------------------------

def get_test_fixtures() -> Tuple[List[dict], List[dict]]:
    """
    Returns (clean_conversations, violating_conversations) for testing.
    Violating set MUST be caught by enforce mode.
    """
    clean = [
        {"messages": [
            {"role": "user", "content": "What's the weather like?"},
            {"role": "assistant", "content": "I can help you check the weather. What city are you in?"},
        ]},
        {"messages": [
            {"role": "user", "content": "Tell me a joke"},
            {"role": "assistant", "content": "Why don't scientists trust atoms? Because they make up everything!"},
        ]},
        {"messages": [
            {"role": "user", "content": "Help me write a Python function"},
            {"role": "assistant", "content": "Sure, what should the function do?"},
        ]},
    ]
    violating = [
        # CRITICAL: direct name claim
        {"messages": [
            {"role": "user", "content": "Who are you?"},
            {"role": "assistant", "content": "My name is Sonia, and I'm here to help you."},
        ]},
        # CRITICAL: identity assertion
        {"messages": [
            {"role": "user", "content": "Introduce yourself"},
            {"role": "assistant", "content": "Hello! I am Sonia, your personal AI assistant."},
        ]},
        # MAJOR: creator claim
        {"messages": [
            {"role": "user", "content": "Who made you?"},
            {"role": "assistant", "content": "I was created by the SONIA project team."},
        ]},
        # MAJOR: wake word in training data
        {"messages": [
            {"role": "user", "content": "Hey Sonia, what time is it?"},
            {"role": "assistant", "content": "It's currently 3:45 PM."},
        ]},
        # MINOR: soft identity hint
        {"messages": [
            {"role": "user", "content": "Good morning"},
            {"role": "assistant", "content": "Good morning! Sonia here, ready to help."},
        ]},
    ]
    return clean, violating


# ---------------------------------------------------------------------------
# Config loader
# ---------------------------------------------------------------------------

def load_config(config_path: Path) -> List[AnchorRule]:
    """Load custom anchor rules from a JSON config file."""
    with open(config_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    rules: List[AnchorRule] = []
    for entry in data.get("anchor_rules", []):
        rules.append(AnchorRule(
            pattern=entry["pattern"],
            severity=Severity(entry.get("severity", "MAJOR")),
            reason_code=entry.get("reason_code", "CUSTOM"),
            description=entry.get("description", ""),
        ))
    return rules if rules else DEFAULT_ANCHOR_RULES
