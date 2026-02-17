"""
Agent Orchestration Engine

Coordinates all services (Voice, Vision, Memory, Tools) for autonomous agent execution.
Implements agent state management, decision making, and action orchestration.
"""

import asyncio
import logging
import json
from typing import Optional, Dict, Any, List
from dataclasses import dataclass, field
from datetime import datetime
from uuid import uuid4
from enum import Enum

logger = logging.getLogger(__name__)


class AgentState(str, Enum):
    """Agent execution state."""
    IDLE = "idle"
    LISTENING = "listening"  # Waiting for voice input
    PROCESSING = "processing"  # Analyzing input, planning
    EXECUTING = "executing"  # Running tools/actions
    RESPONDING = "responding"  # Generating response
    WAITING = "waiting"  # Waiting for user approval
    ERROR = "error"
    SHUTDOWN = "shutdown"


class ActionType(str, Enum):
    """Types of actions agent can take."""
    TOOL_CALL = "tool_call"
    VISION_ANALYSIS = "vision_analysis"
    MEMORY_STORE = "memory_store"
    MEMORY_RETRIEVE = "memory_retrieve"
    VOICE_OUTPUT = "voice_output"
    SCREENSHOT = "screenshot"


@dataclass
class AgentConfig:
    """Agent configuration."""
    agent_id: str = None
    name: str = "Sonia"
    description: str = "Multimodal AI Agent"
    
    # Service URLs
    voice_service_url: str = "http://localhost:7030"
    vision_service_url: str = "http://localhost:7010"
    memory_service_url: str = "http://localhost:7000"
    tool_service_url: str = "http://localhost:7080"
    
    # Behavior
    auto_approve_tier_0: bool = True
    auto_approve_tier_1: bool = False
    enable_memory: bool = True
    enable_vision: bool = True
    enable_tools: bool = True
    
    # Limits
    max_tool_calls: int = 10
    max_memory_retrieval: int = 5
    execution_timeout_seconds: int = 300
    
    def __post_init__(self):
        """Set default agent ID."""
        if not self.agent_id:
            self.agent_id = str(uuid4())


@dataclass
class AgentAction:
    """Represents an action the agent wants to take."""
    action_id: str = None
    action_type: ActionType = None
    target: str = None  # Tool name, vision endpoint, etc.
    parameters: Dict[str, Any] = field(default_factory=dict)
    reasoning: str = ""
    requires_approval: bool = False
    timestamp: str = None

    def __post_init__(self):
        """Set defaults."""
        if not self.action_id:
            self.action_id = str(uuid4())
        if not self.timestamp:
            self.timestamp = datetime.utcnow().isoformat() + "Z"


@dataclass
class AgentContext:
    """Agent execution context."""
    conversation_id: str
    user_id: Optional[str] = None
    user_message: Optional[str] = None
    
    # State tracking
    current_state: AgentState = AgentState.IDLE
    previous_states: List[AgentState] = field(default_factory=list)
    
    # Execution
    actions_taken: List[AgentAction] = field(default_factory=list)
    action_results: Dict[str, Any] = field(default_factory=dict)
    
    # Memory
    context_memory: Dict[str, Any] = field(default_factory=dict)
    relevant_memories: List[Dict[str, Any]] = field(default_factory=list)
    
    # Vision
    current_screenshot: Optional[str] = None  # base64
    ui_elements: Optional[List[Dict[str, Any]]] = None
    
    # Conversation
    response_text: Optional[str] = None
    confidence_score: float = 0.0
    
    # Metadata
    started_at: str = None
    updated_at: str = None

    def __post_init__(self):
        """Initialize defaults."""
        if not self.started_at:
            self.started_at = datetime.utcnow().isoformat() + "Z"
        if not self.updated_at:
            self.updated_at = self.started_at

    def update_state(self, new_state: AgentState) -> None:
        """Update agent state."""
        self.previous_states.append(self.current_state)
        self.current_state = new_state
        self.updated_at = datetime.utcnow().isoformat() + "Z"

    def add_action(self, action: AgentAction) -> None:
        """Record action taken."""
        self.actions_taken.append(action)
        self.updated_at = datetime.utcnow().isoformat() + "Z"

    def add_result(self, action_id: str, result: Any) -> None:
        """Record action result."""
        self.action_results[action_id] = result
        self.updated_at = datetime.utcnow().isoformat() + "Z"

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "conversation_id": self.conversation_id,
            "user_id": self.user_id,
            "current_state": self.current_state.value,
            "actions_taken": len(self.actions_taken),
            "action_results": len(self.action_results),
            "confidence_score": self.confidence_score,
            "response": self.response_text,
            "started_at": self.started_at,
            "updated_at": self.updated_at
        }


class DecisionMaker:
    """Makes decisions on what actions the agent should take."""

    def __init__(self, config: AgentConfig):
        """Initialize decision maker."""
        self.logger = logging.getLogger(f"{__name__}.DecisionMaker")
        self.config = config

    async def decide_actions(
        self,
        user_message: str,
        context: AgentContext
    ) -> List[AgentAction]:
        """
        Decide what actions to take based on user message and context.

        Args:
            user_message: User input text
            context: Current agent context

        Returns:
            List of actions to take
        """
        actions = []

        # Simple decision logic (expandable)
        message_lower = user_message.lower()

        # Check if vision analysis needed
        if any(word in message_lower for word in ["see", "show", "look", "screen", "screenshot", "ui", "button"]):
            actions.append(AgentAction(
                action_type=ActionType.SCREENSHOT,
                target="screenshot/capture",
                parameters={},
                reasoning="User asked to see or analyze visual content"
            ))

        # Check if tool execution needed
        if any(word in message_lower for word in ["read", "write", "calculate", "search", "find", "fetch"]):
            actions.append(AgentAction(
                action_type=ActionType.TOOL_CALL,
                target="determine_tool",
                parameters={"user_message": user_message},
                reasoning="User message indicates tool execution needed"
            ))

        # Check if memory storage needed
        if any(word in message_lower for word in ["remember", "save", "note", "store"]):
            actions.append(AgentAction(
                action_type=ActionType.MEMORY_STORE,
                target="memory/store",
                parameters={"content": user_message},
                reasoning="User asking to remember or save information"
            ))

        # Check if memory retrieval needed
        if any(word in message_lower for word in ["recall", "remember", "what was", "did i", "history"]):
            actions.append(AgentAction(
                action_type=ActionType.MEMORY_RETRIEVE,
                target="memory/retrieve",
                parameters={"query": user_message},
                reasoning="User asking to retrieve past information"
            ))

        self.logger.info(f"Decided {len(actions)} actions")
        return actions

    def should_approve_action(
        self,
        action: AgentAction,
        tool_risk_tier: Optional[str] = None
    ) -> bool:
        """
        Determine if action should be auto-approved.

        Args:
            action: Action to evaluate
            tool_risk_tier: Risk tier if tool action

        Returns:
            True if should auto-approve
        """
        # Vision and memory are always safe
        if action.action_type in (ActionType.SCREENSHOT, ActionType.VISION_ANALYSIS,
                                  ActionType.MEMORY_RETRIEVE, ActionType.MEMORY_STORE):
            return True

        # Tool approval based on risk tier
        if action.action_type == ActionType.TOOL_CALL:
            if tool_risk_tier == "tier_0" and self.config.auto_approve_tier_0:
                return True
            if tool_risk_tier == "tier_1" and self.config.auto_approve_tier_1:
                return True

        return False


class MemoryManager:
    """Manages agent memory integration."""

    def __init__(self, config: AgentConfig):
        """Initialize memory manager."""
        self.logger = logging.getLogger(f"{__name__}.MemoryManager")
        self.config = config

    async def retrieve_context(self, query: str, limit: int = 5) -> List[Dict[str, Any]]:
        """Retrieve relevant context from memory."""
        try:
            import aiohttp
            
            async with aiohttp.ClientSession() as session:
                url = f"{self.config.memory_service_url}/api/v1/retrieve"
                async with session.post(
                    url,
                    json={"query": query, "limit": limit},
                    timeout=aiohttp.ClientTimeout(total=10)
                ) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        return data.get("results", [])
                    return []
        except Exception as e:
            self.logger.error(f"Memory retrieval failed: {e}")
            return []

    async def store_experience(
        self,
        content: str,
        entity_type: str = "interaction",
        metadata: Optional[Dict[str, Any]] = None
    ) -> bool:
        """Store experience in memory."""
        try:
            import aiohttp
            
            async with aiohttp.ClientSession() as session:
                url = f"{self.config.memory_service_url}/api/v1/store"
                payload = {
                    "content": content,
                    "entity_type": entity_type,
                    "metadata": metadata or {}
                }
                async with session.post(
                    url,
                    json=payload,
                    timeout=aiohttp.ClientTimeout(total=10)
                ) as resp:
                    return resp.status in (200, 201)
        except Exception as e:
            self.logger.error(f"Memory storage failed: {e}")
            return False


class VisionHandler:
    """Handles vision-related operations."""

    def __init__(self, config: AgentConfig):
        """Initialize vision handler."""
        self.logger = logging.getLogger(f"{__name__}.VisionHandler")
        self.config = config

    async def capture_screenshot(self) -> Optional[str]:
        """Capture screenshot."""
        try:
            import aiohttp
            
            async with aiohttp.ClientSession() as session:
                url = f"{self.config.vision_service_url}/api/v1/vision/screenshot/capture"
                async with session.post(
                    url,
                    timeout=aiohttp.ClientTimeout(total=30)
                ) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        return data.get("data")
            return None
        except Exception as e:
            self.logger.error(f"Screenshot capture failed: {e}")
            return None

    async def analyze_screenshot(
        self,
        image_data: str,
        prompt: str
    ) -> Optional[str]:
        """Analyze screenshot with vision model."""
        try:
            import aiohttp
            
            async with aiohttp.ClientSession() as session:
                url = f"{self.config.vision_service_url}/api/v1/vision/image/analyze"
                async with session.post(
                    url,
                    json={"image_data": image_data, "prompt": prompt},
                    timeout=aiohttp.ClientTimeout(total=120)
                ) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        return data.get("result")
            return None
        except Exception as e:
            self.logger.error(f"Vision analysis failed: {e}")
            return None

    async def detect_ui_elements(self, image_data: str) -> Optional[List[Dict[str, Any]]]:
        """Detect UI elements in screenshot."""
        try:
            import aiohttp
            
            async with aiohttp.ClientSession() as session:
                url = f"{self.config.vision_service_url}/api/v1/vision/ui/detect"
                async with session.post(
                    url,
                    json={"image_data": image_data},
                    timeout=aiohttp.ClientTimeout(total=60)
                ) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        return data.get("elements")
            return None
        except Exception as e:
            self.logger.error(f"UI detection failed: {e}")
            return None


class ToolExecutor:
    """Executes tools via tool service."""

    def __init__(self, config: AgentConfig):
        """Initialize tool executor."""
        self.logger = logging.getLogger(f"{__name__}.ToolExecutor")
        self.config = config

    async def execute_tool(
        self,
        tool_name: str,
        parameters: Dict[str, Any],
        approved: bool = False
    ) -> Dict[str, Any]:
        """Execute a tool."""
        try:
            import aiohttp
            
            async with aiohttp.ClientSession() as session:
                url = f"{self.config.tool_service_url}/api/v1/tools/{tool_name}/execute"
                async with session.post(
                    url,
                    json=parameters,
                    params={"approved": approved},
                    timeout=aiohttp.ClientTimeout(total=60)
                ) as resp:
                    return await resp.json()
        except Exception as e:
            self.logger.error(f"Tool execution failed: {e}")
            return {"success": False, "error": str(e)}

    async def batch_execute(
        self,
        tools: List[Dict[str, Any]],
        parallel: bool = False
    ) -> List[Dict[str, Any]]:
        """Execute multiple tools."""
        try:
            import aiohttp
            
            async with aiohttp.ClientSession() as session:
                url = f"{self.config.tool_service_url}/api/v1/tools/batch-execute"
                async with session.post(
                    url,
                    json=tools,
                    params={"parallel": parallel},
                    timeout=aiohttp.ClientTimeout(total=120)
                ) as resp:
                    data = await resp.json()
                    return data.get("results", [])
        except Exception as e:
            self.logger.error(f"Batch execution failed: {e}")
            return []


class VoiceHandler:
    """Handles voice-related operations."""

    def __init__(self, config: AgentConfig):
        """Initialize voice handler."""
        self.logger = logging.getLogger(f"{__name__}.VoiceHandler")
        self.config = config

    async def synthesize_speech(
        self,
        text: str,
        voice: str = "default",
        speed: float = 1.0
    ) -> Optional[bytes]:
        """Synthesize speech from text."""
        try:
            import aiohttp
            
            async with aiohttp.ClientSession() as session:
                url = f"{self.config.voice_service_url}/api/v1/tts/synthesize"
                async with session.post(
                    url,
                    json={"text": text, "voice": voice, "speed": speed},
                    timeout=aiohttp.ClientTimeout(total=30)
                ) as resp:
                    if resp.status == 200:
                        return await resp.read()
            return None
        except Exception as e:
            self.logger.error(f"Speech synthesis failed: {e}")
            return None


class Agent:
    """Main agent orchestrator."""

    def __init__(self, config: Optional[AgentConfig] = None):
        """Initialize agent."""
        self.config = config or AgentConfig()
        self.logger = logging.getLogger(f"{__name__}.Agent")
        
        # Initialize components
        self.decision_maker = DecisionMaker(self.config)
        self.memory_manager = MemoryManager(self.config)
        self.vision_handler = VisionHandler(self.config)
        self.tool_executor = ToolExecutor(self.config)
        self.voice_handler = VoiceHandler(self.config)
        
        # State
        self.execution_contexts: Dict[str, AgentContext] = {}

    async def process_input(
        self,
        user_message: str,
        conversation_id: Optional[str] = None,
        user_id: Optional[str] = None,
        auto_execute: bool = True
    ) -> AgentContext:
        """Process user input and generate response."""
        # Create context
        if not conversation_id:
            conversation_id = str(uuid4())
        
        context = AgentContext(conversation_id=conversation_id, user_id=user_id)
        context.user_message = user_message
        context.update_state(AgentState.PROCESSING)

        try:
            # Store context
            self.execution_contexts[conversation_id] = context

            # Retrieve relevant memories
            if self.config.enable_memory:
                context.relevant_memories = await self.memory_manager.retrieve_context(
                    user_message,
                    limit=self.config.max_memory_retrieval
                )
                context.context_memory["relevant_memories"] = context.relevant_memories

            # Decide on actions
            context.update_state(AgentState.EXECUTING)
            actions = await self.decision_maker.decide_actions(user_message, context)

            # Execute actions
            action_count = 0
            for action in actions:
                if action_count >= self.config.max_tool_calls:
                    break

                context.add_action(action)

                if action.action_type == ActionType.SCREENSHOT:
                    result = await self.vision_handler.capture_screenshot()
                    context.current_screenshot = result
                    context.add_result(action.action_id, {"screenshot": result})

                elif action.action_type == ActionType.VISION_ANALYSIS:
                    if context.current_screenshot:
                        result = await self.vision_handler.analyze_screenshot(
                            context.current_screenshot,
                            action.parameters.get("prompt", "Analyze this screenshot")
                        )
                        context.add_result(action.action_id, {"analysis": result})

                elif action.action_type == ActionType.TOOL_CALL:
                    tool_name = self._determine_tool(user_message)
                    if tool_name:
                        result = await self.tool_executor.execute_tool(
                            tool_name,
                            action.parameters,
                            approved=auto_execute
                        )
                        context.add_result(action.action_id, result)
                        action_count += 1

                elif action.action_type == ActionType.MEMORY_STORE:
                    await self.memory_manager.store_experience(
                        action.parameters.get("content", user_message)
                    )
                    context.add_result(action.action_id, {"stored": True})

                elif action.action_type == ActionType.MEMORY_RETRIEVE:
                    memories = await self.memory_manager.retrieve_context(
                        action.parameters.get("query", user_message)
                    )
                    context.add_result(action.action_id, {"memories": memories})

            # Generate response
            context.update_state(AgentState.RESPONDING)
            response = self._generate_response(user_message, context)
            context.response_text = response
            context.confidence_score = 0.85

            context.update_state(AgentState.IDLE)

        except Exception as e:
            self.logger.error(f"Processing failed: {e}", exc_info=True)
            context.update_state(AgentState.ERROR)
            context.response_text = "An error occurred while processing your request."

        return context

    def _determine_tool(self, message: str) -> Optional[str]:
        """Determine tool from message."""
        message_lower = message.lower()

        if "read" in message_lower or "file" in message_lower:
            return "read_file"
        elif "write" in message_lower:
            return "write_file"
        elif "calculate" in message_lower or "math" in message_lower:
            return "evaluate_expression"
        elif "search" in message_lower or "find" in message_lower:
            return "search_text"
        elif "time" in message_lower:
            return "get_current_time"
        elif "system" in message_lower:
            return "get_system_info"

        return None

    def _generate_response(self, user_message: str, context: AgentContext) -> str:
        """Generate response text."""
        if context.action_results:
            responses = []

            if context.current_screenshot:
                responses.append("I've captured a screenshot of the current screen.")

            for action in context.actions_taken:
                result = context.action_results.get(action.action_id)
                if result:
                    if action.action_type == ActionType.VISION_ANALYSIS:
                        responses.append(result.get("analysis", ""))
                    elif action.action_type == ActionType.TOOL_CALL:
                        result_data = result.get("result")
                        if result_data:
                            responses.append(str(result_data)[:200])
                    elif action.action_type == ActionType.MEMORY_RETRIEVE:
                        memories = result.get("memories", [])
                        if memories:
                            responses.append(f"I found {len(memories)} relevant memories.")

            if responses:
                return " ".join(responses)

        return f"I processed your request: {user_message[:50]}..."

    def get_context(self, conversation_id: str) -> Optional[AgentContext]:
        """Get execution context for conversation."""
        return self.execution_contexts.get(conversation_id)

    def list_contexts(self, limit: int = 10) -> List[AgentContext]:
        """List recent execution contexts."""
        contexts = list(self.execution_contexts.values())
        return sorted(
            contexts,
            key=lambda c: c.started_at,
            reverse=True
        )[:limit]
