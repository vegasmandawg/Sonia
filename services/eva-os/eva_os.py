"""
EVA-OS: Sonia's Supervisory Control Plane

EVA-OS is the conductor that keeps the Sonia system coherent.
It owns: orchestration, policy gating, task state, health monitoring, and degradation.

The model is probabilistic. EVA-OS is deterministic.
EVA-OS decides; OpenClaw does; Model proposes.
"""

import json
import uuid
from datetime import datetime
from typing import Dict, List, Optional, Any
from enum import Enum
import hashlib
import logging

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s'
)
logger = logging.getLogger('EVA-OS')


class SoniaMode(Enum):
    """Operational modes that change behavior across the system."""
    CONVERSATION = "conversation"  # Propose, ask permission
    OPERATOR = "operator"          # Execute tasks, ask for destructive ops
    DIAGNOSTIC = "diagnostic"      # Health checks, logs, introspection
    DICTATION = "dictation"        # Capture only, no tool calls
    BUILD = "build"                # Complete artifacts, pinned versions


class ServiceName(Enum):
    """Names of services in the Sonia stack."""
    GATEWAY = "gateway"
    PIPECAT = "pipecat"
    MEMORY_ENGINE = "memory-engine"
    MODEL_ROUTER = "model-router"
    OPENCLAW = "openclaw"
    EVA_OS = "eva-os"


class ServiceHealth(Enum):
    """Health status of each service."""
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    OFFLINE = "offline"
    UNKNOWN = "unknown"


class RiskTier(Enum):
    """Risk classification for tool calls."""
    TIER_0_READONLY = "tier_0_readonly"
    TIER_1_LOW_RISK = "tier_1_low_risk"
    TIER_2_MEDIUM_RISK = "tier_2_medium_risk"
    TIER_3_DESTRUCTIVE = "tier_3_destructive"


class OperationalState:
    """Tracks the complete operational state of Sonia."""

    def __init__(self):
        self.mode: SoniaMode = SoniaMode.CONVERSATION
        
        # Service health map
        self.service_health: Dict[ServiceName, ServiceHealth] = {
            service: ServiceHealth.UNKNOWN for service in ServiceName
        }
        
        # Capabilities available (based on service health)
        self.capabilities = {
            "voice_input": False,
            "voice_output": False,
            "vision_input": False,
            "action_execution": False,
            "memory_recall": False,
        }
        
        # Interaction state
        self.speaking = False
        self.listening = False
        self.interruptible = False
        self.pending_approval: Optional[Dict] = None
        self.approval_token: Optional[str] = None
        
        # Task state
        self.active_task_id: Optional[str] = None
        self.task_steps: List[Dict] = []
        self.last_tool_call_id: Optional[str] = None
        self.last_tool_result: Optional[Dict] = None
        
        # Policy state
        self.action_allowlist: List[str] = []
        self.action_denylist: List[str] = []
        self.confirmation_rules: Dict[str, bool] = {}
        
        # Session state
        self.session_id = str(uuid.uuid4())
        self.root_contract = "S:\\"
        self.last_user_turn_id: Optional[str] = None
        self.last_assistant_turn_id: Optional[str] = None

    def update_service_health(self, service: ServiceName, health: ServiceHealth):
        """Update health of a service and recompute capabilities."""
        self.service_health[service] = health
        self._recompute_capabilities()
        logger.info(f"Service {service.value} health: {health.value}")

    def _recompute_capabilities(self):
        """Based on service health, determine what capabilities are available."""
        self.capabilities["voice_input"] = (
            self.service_health[ServiceName.PIPECAT] == ServiceHealth.HEALTHY
        )
        self.capabilities["voice_output"] = (
            self.service_health[ServiceName.PIPECAT] == ServiceHealth.HEALTHY
        )
        self.capabilities["vision_input"] = (
            self.service_health[ServiceName.PIPECAT] == ServiceHealth.HEALTHY
        )
        self.capabilities["action_execution"] = (
            self.service_health[ServiceName.OPENCLAW] == ServiceHealth.HEALTHY
        )
        self.capabilities["memory_recall"] = (
            self.service_health[ServiceName.MEMORY_ENGINE] == ServiceHealth.HEALTHY
        )

    def set_mode(self, mode: SoniaMode):
        """Change operational mode."""
        old_mode = self.mode
        self.mode = mode
        logger.info(f"Mode change: {old_mode.value} -> {mode.value}")

    def to_dict(self) -> Dict:
        """Serialize state to dict."""
        return {
            "session_id": self.session_id,
            "mode": self.mode.value,
            "service_health": {s.value: h.value for s, h in self.service_health.items()},
            "capabilities": self.capabilities,
            "interaction_state": {
                "speaking": self.speaking,
                "listening": self.listening,
                "interruptible": self.interruptible,
                "pending_approval": self.pending_approval is not None,
            },
            "task_state": {
                "active_task_id": self.active_task_id,
                "task_steps_count": len(self.task_steps),
                "last_tool_call_id": self.last_tool_call_id,
            },
        }


class ToolCallValidator:
    """Validates and classifies tool calls before execution."""

    def __init__(self, root_contract: str = "S:\\"):
        self.root_contract = root_contract
        self.tier_0_tools = {
            "filesystem.list_directory",
            "filesystem.read_file",
            "filesystem.stat",
            "process.list",
            "http.get",
        }
        self.tier_1_tools = {
            "filesystem.create_directory",
            "filesystem.write_file",
            "filesystem.append_file",
        }
        self.tier_2_tools = {
            "filesystem.move",
            "filesystem.copy",
            "filesystem.overwrite",
            "process.start",
            "process.stop",
            "shell.run_powershell_script",
        }
        self.tier_3_tools = {
            "filesystem.delete",
            "process.kill",
            "shell.run_command",
        }

    def classify_risk(self, tool_name: str) -> RiskTier:
        """Classify tool call by risk tier."""
        if tool_name in self.tier_0_tools:
            return RiskTier.TIER_0_READONLY
        elif tool_name in self.tier_1_tools:
            return RiskTier.TIER_1_LOW_RISK
        elif tool_name in self.tier_2_tools:
            return RiskTier.TIER_2_MEDIUM_RISK
        elif tool_name in self.tier_3_tools:
            return RiskTier.TIER_3_DESTRUCTIVE
        else:
            return RiskTier.TIER_2_MEDIUM_RISK  # Default: assume medium-risk

    def validate_root_contract(self, tool_name: str, args: Dict) -> bool:
        """Verify that file operations stay within root contract."""
        if not tool_name.startswith("filesystem."):
            return True  # Non-filesystem operations not constrained

        path = args.get("path") or args.get("destination") or args.get("source")
        if not path:
            return True  # No path specified; assume OK

        # Normalize path and check if under root
        normalized = path.replace("/", "\\")
        if not normalized.lower().startswith(self.root_contract.lower()):
            logger.warning(f"Root contract violation: {path} outside {self.root_contract}")
            return False
        return True

    def needs_approval(self, risk_tier: RiskTier, mode: SoniaMode) -> bool:
        """Determine if tool call needs explicit approval."""
        if risk_tier == RiskTier.TIER_0_READONLY:
            return False
        elif risk_tier == RiskTier.TIER_1_LOW_RISK:
            return mode in [SoniaMode.CONVERSATION, SoniaMode.DICTATION]
        elif risk_tier == RiskTier.TIER_2_MEDIUM_RISK:
            return mode in [SoniaMode.CONVERSATION, SoniaMode.DIAGNOSTIC]
        elif risk_tier == RiskTier.TIER_3_DESTRUCTIVE:
            return True  # Always require approval for destructive
        return True  # Default: require approval

    def compute_scope_hash(self, tool_name: str, args: Dict) -> str:
        """Compute hash of tool_name + args for approval token scope."""
        scope_str = json.dumps({"tool_name": tool_name, "args": args}, sort_keys=True)
        return hashlib.sha256(scope_str.encode()).hexdigest()[:16]


class EVAOSOrchestrator:
    """Main EVA-OS orchestrator."""

    def __init__(self, root_contract: str = "S:\\"):
        self.state = OperationalState()
        self.validator = ToolCallValidator(root_contract=root_contract)
        self.root_contract = root_contract
        self.approval_tokens: Dict[str, Dict] = {}  # token -> scope info
        logger.info(f"EVA-OS initialized with root contract: {root_contract}")

    def initialize_stack_health(self, service_health: Dict[str, str]):
        """Initialize service health from gateway or config."""
        for service_str, health_str in service_health.items():
            try:
                service = ServiceName[service_str.upper()]
                health = ServiceHealth[health_str.upper()]
                self.state.update_service_health(service, health)
            except KeyError:
                logger.warning(f"Unknown service or health status: {service_str}/{health_str}")

    def process_user_turn(self, turn: Dict) -> Dict:
        """Process an incoming UserTurn event."""
        self.state.last_user_turn_id = turn.get("id")
        self.state.listening = False
        
        logger.info(f"Processing turn {turn.get('id')}: mode={turn.get('mode')} text={turn.get('text')[:50]}...")
        
        # Update mode if specified
        if turn.get("mode"):
            try:
                mode = SoniaMode[turn["mode"].upper()]
                self.state.set_mode(mode)
            except KeyError:
                logger.warning(f"Unknown mode: {turn.get('mode')}")
        
        return {
            "status": "turn_received",
            "turn_id": turn.get("id"),
            "session_id": self.state.session_id,
            "current_capabilities": self.state.capabilities,
        }

    def validate_and_gate_tool_call(self, tool_call: Dict) -> Dict:
        """Validate a tool call and determine if approval is needed."""
        tool_name = tool_call.get("tool_name")
        args = tool_call.get("args", {})
        
        # Validate root contract
        if not self.validator.validate_root_contract(tool_name, args):
            return {
                "status": "blocked",
                "reason": f"Path outside root contract {self.root_contract}",
                "tool_call_id": tool_call.get("id"),
            }
        
        # Classify risk
        risk_tier = self.validator.classify_risk(tool_name)
        
        # Check if approval needed
        needs_approval = self.validator.needs_approval(risk_tier, self.state.mode)
        
        if needs_approval:
            # Generate approval request
            approval_token = str(uuid.uuid4())
            scope_hash = self.validator.compute_scope_hash(tool_name, args)
            
            approval_request = {
                "id": str(uuid.uuid4()),
                "tool_call_id": tool_call.get("id"),
                "action_summary": f"Execute {tool_name}",
                "exact_targets": self._extract_targets(tool_name, args),
                "expected_impact": self._describe_impact(tool_name, args),
                "risk_level": risk_tier.value,
                "approval_token": approval_token,
                "scope_hash": scope_hash,
                "timeout_seconds": 300,
            }
            
            self.state.pending_approval = approval_request
            self.approval_tokens[approval_token] = {
                "tool_call_id": tool_call.get("id"),
                "scope_hash": scope_hash,
                "timestamp": datetime.utcnow().isoformat(),
            }
            
            return {
                "status": "approval_required",
                "approval_request": approval_request,
                "tool_call_id": tool_call.get("id"),
            }
        
        # No approval needed; tool call can proceed
        return {
            "status": "approved",
            "tool_call_id": tool_call.get("id"),
            "risk_tier": risk_tier.value,
        }

    def process_approval_response(self, response: Dict) -> Dict:
        """Process user approval or denial."""
        approval_request_id = response.get("approval_request_id")
        decision = response.get("decision")
        approval_token = response.get("approval_token")
        
        # Verify token
        if approval_token not in self.approval_tokens:
            return {
                "status": "invalid_token",
                "reason": "Approval token not recognized or expired",
            }
        
        token_info = self.approval_tokens.pop(approval_token)
        tool_call_id = token_info["tool_call_id"]
        
        if decision == "approved":
            logger.info(f"Tool call {tool_call_id} approved by user")
            self.state.pending_approval = None
            return {
                "status": "approval_confirmed",
                "tool_call_id": tool_call_id,
                "can_execute": True,
            }
        else:  # denied
            logger.info(f"Tool call {tool_call_id} denied by user: {response.get('reason', 'no reason')}")
            self.state.pending_approval = None
            return {
                "status": "approval_denied",
                "tool_call_id": tool_call_id,
                "reason": response.get("reason", "User denied approval"),
            }

    def process_tool_result(self, result: Dict) -> Dict:
        """Process result from OpenClaw tool execution."""
        self.state.last_tool_call_id = result.get("tool_call_id")
        self.state.last_tool_result = result
        
        status = result.get("status")
        if status == "success":
            logger.info(f"Tool {result.get('tool_call_id')} succeeded")
        else:
            logger.warning(f"Tool {result.get('tool_call_id')} failed: {status}")
        
        return {
            "status": "tool_result_processed",
            "tool_call_id": result.get("tool_call_id"),
            "verification_status": result.get("verification_results", {}),
        }

    def handle_service_health_change(self, event: Dict) -> Dict:
        """Handle service health update from gateway."""
        source_service = event.get("source_service")
        payload = event.get("payload", {})
        new_health = payload.get("health_status")
        
        try:
            service = ServiceName[source_service.upper().replace("-", "_")]
            health = ServiceHealth[new_health.upper()]
            self.state.update_service_health(service, health)
        except KeyError:
            logger.warning(f"Unknown service or health in event: {event}")
            return {"status": "error", "reason": "Unknown service/health"}
        
        # If action_execution goes offline, stop issuing tool calls
        if service == ServiceName.OPENCLAW and health == ServiceHealth.OFFLINE:
            logger.warning("OpenClaw offline; will not execute tool calls")
        
        return {
            "status": "health_updated",
            "service": source_service,
            "new_health": new_health,
            "capabilities": self.state.capabilities,
        }

    def get_current_state(self) -> Dict:
        """Return current operational state (for UI dashboards)."""
        return self.state.to_dict()

    def _extract_targets(self, tool_name: str, args: Dict) -> List[str]:
        """Extract affected paths/targets from tool call."""
        targets = []
        for key in ["path", "destination", "source", "target"]:
            if key in args:
                targets.append(args[key])
        return targets

    def _describe_impact(self, tool_name: str, args: Dict) -> str:
        """Generate human-readable impact description."""
        if "delete" in tool_name.lower():
            return f"Will delete {len(self._extract_targets(tool_name, args))} item(s)"
        elif "write" in tool_name.lower() or "create" in tool_name.lower():
            return f"Will create/modify files at {', '.join(self._extract_targets(tool_name, args)[:2])}"
        elif "process" in tool_name.lower() and "stop" in tool_name.lower():
            return f"Will stop process(es)"
        elif "process" in tool_name.lower() and "start" in tool_name.lower():
            return f"Will start new process"
        else:
            return "Will execute action with side effects"


# Example usage and testing
if __name__ == "__main__":
    # Initialize EVA-OS
    eva = EVAOSOrchestrator(root_contract="S:\\")
    
    # Initialize service health
    eva.initialize_stack_health({
        "GATEWAY": "healthy",
        "PIPECAT": "healthy",
        "MEMORY_ENGINE": "healthy",
        "MODEL_ROUTER": "healthy",
        "OPENCLAW": "healthy",
    })
    
    # Process a user turn
    user_turn = {
        "id": "turn-001",
        "text": "Create a new script file",
        "mode": "operator",
    }
    print("\n=== Processing User Turn ===")
    print(json.dumps(eva.process_user_turn(user_turn), indent=2))
    
    # Process a tool call requiring approval
    tool_call = {
        "id": "tool-001",
        "tool_name": "filesystem.write_file",
        "args": {"path": "S:\\scripts\\test.ps1", "content": "Write-Host 'Hello'"},
    }
    print("\n=== Gating Tool Call ===")
    result = eva.validate_and_gate_tool_call(tool_call)
    print(json.dumps(result, indent=2))
    
    # Approve the tool call
    if result["status"] == "approval_required":
        approval_token = result["approval_request"]["approval_token"]
        print("\n=== Approving Tool Call ===")
        approval = {
            "approval_request_id": result["approval_request"]["id"],
            "decision": "approved",
            "approval_token": approval_token,
        }
        print(json.dumps(eva.process_approval_response(approval), indent=2))
    
    # Get current state
    print("\n=== Current State ===")
    print(json.dumps(eva.get_current_state(), indent=2))
