"""
Stage 5 — Capability Registry
Central registry of supported action intents, their risk classification,
and execution constraints.  The action pipeline consults this before
planning, validating, or executing any action.
"""

from typing import Any, Dict, List, Optional, Set
from dataclasses import dataclass, field
from schemas.action import RiskLevel
import re


# ── Capability descriptor ────────────────────────────────────────────────────

@dataclass
class Capability:
    """Descriptor for a single action capability."""
    intent: str                           # e.g. "file.read", "shell.run"
    display_name: str                     # Human-readable name
    description: str
    risk_level: RiskLevel                 # Default risk classification
    requires_confirmation: bool           # Default confirmation requirement
    implemented: bool                     # Whether an executor is wired
    required_params: List[str]            # Params that must be present
    optional_params: List[str] = field(default_factory=list)
    max_timeout_ms: int = 30000           # Hard ceiling for this action
    default_timeout_ms: int = 10000
    max_retries: int = 3
    idempotent: bool = False              # Safe to retry?
    reversible: bool = False              # Can be rolled back?
    tags: Set[str] = field(default_factory=set)  # e.g. {"filesystem", "readonly"}


# ── Registry ─────────────────────────────────────────────────────────────────

class CapabilityRegistry:
    """
    Singleton registry of all supported action intents.
    Populated at import time with known capabilities.
    Stage 5 extends with desktop adapters; the set is additive only.
    """

    def __init__(self):
        self._capabilities: Dict[str, Capability] = {}
        self._register_builtins()

    # ── Public API ───────────────────────────────────────────────────────

    def get(self, intent: str) -> Optional[Capability]:
        """Look up capability by intent key."""
        return self._capabilities.get(intent)

    def exists(self, intent: str) -> bool:
        return intent in self._capabilities

    def is_implemented(self, intent: str) -> bool:
        cap = self._capabilities.get(intent)
        return cap.implemented if cap else False

    def list_all(self) -> List[Capability]:
        return list(self._capabilities.values())

    def list_implemented(self) -> List[Capability]:
        return [c for c in self._capabilities.values() if c.implemented]

    def list_by_risk(self, level: RiskLevel) -> List[Capability]:
        return [c for c in self._capabilities.values() if c.risk_level == level]

    def list_by_tag(self, tag: str) -> List[Capability]:
        return [c for c in self._capabilities.values() if tag in c.tags]

    def register(self, cap: Capability):
        """Register or replace a capability."""
        self._capabilities[cap.intent] = cap

    def stats(self) -> Dict[str, Any]:
        all_caps = list(self._capabilities.values())
        return {
            "total": len(all_caps),
            "implemented": sum(1 for c in all_caps if c.implemented),
            "by_risk": {
                "safe": sum(1 for c in all_caps if c.risk_level == "safe"),
                "low": sum(1 for c in all_caps if c.risk_level == "low"),
                "medium": sum(1 for c in all_caps if c.risk_level == "medium"),
                "high": sum(1 for c in all_caps if c.risk_level == "high"),
                "critical": sum(1 for c in all_caps if c.risk_level == "critical"),
            },
            "confirmable": sum(1 for c in all_caps if c.requires_confirmation),
            "reversible": sum(1 for c in all_caps if c.reversible),
            "idempotent": sum(1 for c in all_caps if c.idempotent),
        }

    def validate_params(self, intent: str, params: Dict[str, Any]) -> List[str]:
        """
        Validate that required params are present.
        Returns list of error strings (empty = valid).
        """
        cap = self._capabilities.get(intent)
        if not cap:
            return [f"Unknown intent: {intent}"]
        errors = []
        for rp in cap.required_params:
            if rp not in params or params[rp] is None:
                errors.append(f"Missing required parameter: {rp}")
        return errors

    # ── Built-in registrations ───────────────────────────────────────────

    def _register_builtins(self):
        """Register capabilities that match existing OpenClaw executors."""

        # Existing Stage 2-4 tools already wired in openclaw
        self.register(Capability(
            intent="file.read",
            display_name="Read File",
            description="Read file contents from the S:\\ sandbox",
            risk_level="safe",
            requires_confirmation=False,
            implemented=True,
            required_params=["path"],
            idempotent=True,
            reversible=False,
            tags={"filesystem", "readonly"},
        ))

        self.register(Capability(
            intent="file.write",
            display_name="Write File",
            description="Write content to a file in S:\\ sandbox",
            risk_level="medium",
            requires_confirmation=True,
            implemented=True,
            required_params=["path", "content"],
            idempotent=False,
            reversible=False,   # will be True once rollback adapter lands in M3
            tags={"filesystem", "write"},
        ))

        self.register(Capability(
            intent="shell.run",
            display_name="Run Shell Command",
            description="Execute a PowerShell command from allowlist",
            risk_level="medium",
            requires_confirmation=True,
            implemented=True,
            required_params=["command"],
            idempotent=False,
            reversible=False,
            tags={"shell", "compute"},
        ))

        self.register(Capability(
            intent="browser.open",
            display_name="Open Browser",
            description="Open a URL in the default browser",
            risk_level="low",
            requires_confirmation=True,
            implemented=True,
            required_params=["url"],
            idempotent=True,
            reversible=False,
            tags={"browser", "network"},
        ))

        # ── Stage 5 M3 desktop capabilities (executors in openclaw) ────

        self.register(Capability(
            intent="app.launch",
            display_name="Launch Application",
            description="Launch a desktop application by name or path",
            risk_level="medium",
            requires_confirmation=True,
            implemented=True,
            required_params=["target"],
            optional_params=["args", "working_dir"],
            idempotent=False,
            reversible=True,
            tags={"desktop", "app"},
        ))

        self.register(Capability(
            intent="app.close",
            display_name="Close Application",
            description="Close a running application gracefully",
            risk_level="high",
            requires_confirmation=True,
            implemented=True,
            required_params=["target"],
            optional_params=["force"],
            idempotent=True,
            reversible=False,
            tags={"desktop", "app"},
        ))

        self.register(Capability(
            intent="window.focus",
            display_name="Focus Window",
            description="Bring a window to the foreground",
            risk_level="safe",
            requires_confirmation=False,
            implemented=True,
            required_params=["title"],
            idempotent=True,
            reversible=False,
            tags={"desktop", "window"},
        ))

        self.register(Capability(
            intent="window.list",
            display_name="List Windows",
            description="List all visible desktop windows",
            risk_level="safe",
            requires_confirmation=False,
            implemented=True,
            required_params=[],
            idempotent=True,
            reversible=False,
            tags={"desktop", "window", "readonly"},
        ))

        self.register(Capability(
            intent="keyboard.type",
            display_name="Type Text",
            description="Send keyboard input to the active window",
            risk_level="high",
            requires_confirmation=True,
            implemented=True,
            required_params=["text"],
            optional_params=["delay_ms"],
            idempotent=False,
            reversible=False,
            tags={"desktop", "input"},
        ))

        self.register(Capability(
            intent="keyboard.hotkey",
            display_name="Press Hotkey",
            description="Send a keyboard shortcut (e.g. Ctrl+S)",
            risk_level="high",
            requires_confirmation=True,
            implemented=True,
            required_params=["keys"],
            idempotent=False,
            reversible=False,
            tags={"desktop", "input"},
        ))

        self.register(Capability(
            intent="mouse.click",
            display_name="Mouse Click",
            description="Click at screen coordinates",
            risk_level="high",
            requires_confirmation=True,
            implemented=True,
            required_params=["x", "y"],
            optional_params=["button", "clicks"],
            idempotent=False,
            reversible=False,
            tags={"desktop", "input"},
        ))

        self.register(Capability(
            intent="clipboard.read",
            display_name="Read Clipboard",
            description="Read text from the system clipboard",
            risk_level="safe",
            requires_confirmation=False,
            implemented=True,
            required_params=[],
            idempotent=True,
            reversible=False,
            tags={"desktop", "clipboard", "readonly"},
        ))

        self.register(Capability(
            intent="clipboard.write",
            display_name="Write Clipboard",
            description="Write text to the system clipboard",
            risk_level="low",
            requires_confirmation=False,
            implemented=True,
            required_params=["text"],
            idempotent=True,
            reversible=True,
            tags={"desktop", "clipboard"},
        ))


# ── Singleton ────────────────────────────────────────────────────────────────

_registry: Optional[CapabilityRegistry] = None


def get_capability_registry() -> CapabilityRegistry:
    global _registry
    if _registry is None:
        _registry = CapabilityRegistry()
    return _registry
