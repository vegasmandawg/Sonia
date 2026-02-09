"""
Tool Registry and Catalog

Manages tool definitions, discovery, and metadata.
Implements risk-based tool classification and execution policies.
"""

import logging
import json
from typing import Optional, Dict, Any, List, Callable
from dataclasses import dataclass, asdict
from enum import Enum
from datetime import datetime
from uuid import uuid4

logger = logging.getLogger(__name__)


class RiskTier(str, Enum):
    """Risk classification for tool execution."""
    TIER_0 = "tier_0"  # Read-only, no side effects
    TIER_1 = "tier_1"  # Local file I/O, limited scope
    TIER_2 = "tier_2"  # Network I/O, external APIs
    TIER_3 = "tier_3"  # Destructive operations, admin actions


class ToolCategory(str, Enum):
    """Tool functional categories."""
    FILESYSTEM = "filesystem"
    NETWORK = "network"
    COMPUTATION = "computation"
    MEDIA = "media"
    DATABASE = "database"
    SYSTEM = "system"
    COMMUNICATION = "communication"
    DEVELOPMENT = "development"
    MONITORING = "monitoring"
    SECURITY = "security"


@dataclass
class ToolParameter:
    """Represents a tool parameter."""
    name: str
    type: str  # string, integer, boolean, array, object
    required: bool
    description: str
    default: Optional[Any] = None
    enum: Optional[List[str]] = None
    min_value: Optional[float] = None
    max_value: Optional[float] = None
    pattern: Optional[str] = None  # regex for validation

    def validate(self, value: Any) -> bool:
        """Validate parameter value."""
        if value is None:
            return not self.required

        # Type checking
        type_map = {
            "string": str,
            "integer": int,
            "number": (int, float),
            "boolean": bool,
            "array": list,
            "object": dict
        }

        expected_type = type_map.get(self.type)
        if expected_type and not isinstance(value, expected_type):
            return False

        # Enum checking
        if self.enum and value not in self.enum:
            return False

        # Range checking
        if self.type in ("integer", "number"):
            if self.min_value is not None and value < self.min_value:
                return False
            if self.max_value is not None and value > self.max_value:
                return False

        # Pattern matching
        if self.pattern and isinstance(value, str):
            import re
            if not re.match(self.pattern, value):
                return False

        return True

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "name": self.name,
            "type": self.type,
            "required": self.required,
            "description": self.description,
            "default": self.default,
            "enum": self.enum,
            "min_value": self.min_value,
            "max_value": self.max_value,
            "pattern": self.pattern
        }


@dataclass
class ToolDefinition:
    """Represents a tool definition."""
    name: str
    description: str
    category: ToolCategory
    risk_tier: RiskTier
    parameters: List[ToolParameter]
    returns: str  # Description of return value
    examples: Optional[List[str]] = None
    aliases: Optional[List[str]] = None
    deprecated: bool = False
    version: str = "1.0.0"
    author: str = "system"
    tags: Optional[List[str]] = None
    requires_approval: bool = False  # For high-risk operations
    requires_authentication: bool = False
    rate_limit: Optional[int] = None  # calls per minute
    timeout_seconds: int = 30

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "name": self.name,
            "description": self.description,
            "category": self.category.value,
            "risk_tier": self.risk_tier.value,
            "parameters": [p.to_dict() for p in self.parameters],
            "returns": self.returns,
            "examples": self.examples or [],
            "aliases": self.aliases or [],
            "deprecated": self.deprecated,
            "version": self.version,
            "author": self.author,
            "tags": self.tags or [],
            "requires_approval": self.requires_approval,
            "requires_authentication": self.requires_authentication,
            "rate_limit": self.rate_limit,
            "timeout_seconds": self.timeout_seconds
        }

    def validate_parameters(self, params: Dict[str, Any]) -> tuple:
        """
        Validate parameters against definition.

        Returns:
            (is_valid, error_message)
        """
        # Check required parameters
        for param in self.parameters:
            if param.required and param.name not in params:
                return False, f"Missing required parameter: {param.name}"

        # Validate provided parameters
        for name, value in params.items():
            param_def = next((p for p in self.parameters if p.name == name), None)
            if not param_def:
                return False, f"Unknown parameter: {name}"

            if not param_def.validate(value):
                return False, f"Invalid value for parameter '{name}': {value}"

        return True, ""


@dataclass
class ToolUsageStats:
    """Tool usage statistics."""
    tool_name: str
    total_calls: int = 0
    successful_calls: int = 0
    failed_calls: int = 0
    total_execution_time_ms: float = 0.0
    last_called: Optional[str] = None
    last_error: Optional[str] = None
    average_execution_time_ms: float = 0.0

    @property
    def success_rate(self) -> float:
        """Calculate success rate."""
        if self.total_calls == 0:
            return 0.0
        return (self.successful_calls / self.total_calls) * 100

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "tool_name": self.tool_name,
            "total_calls": self.total_calls,
            "successful_calls": self.successful_calls,
            "failed_calls": self.failed_calls,
            "success_rate": round(self.success_rate, 2),
            "total_execution_time_ms": round(self.total_execution_time_ms, 2),
            "average_execution_time_ms": round(self.average_execution_time_ms, 2),
            "last_called": self.last_called,
            "last_error": self.last_error
        }


class ToolRegistry:
    """Central registry for all tools."""

    def __init__(self):
        """Initialize tool registry."""
        self.logger = logging.getLogger(f"{__name__}.ToolRegistry")
        self.tools: Dict[str, ToolDefinition] = {}
        self.aliases: Dict[str, str] = {}
        self.stats: Dict[str, ToolUsageStats] = {}
        self.implementations: Dict[str, Callable] = {}

    def register(
        self,
        definition: ToolDefinition,
        implementation: Optional[Callable] = None
    ) -> None:
        """
        Register a tool.

        Args:
            definition: Tool definition
            implementation: Optional implementation function
        """
        # Register main name
        self.tools[definition.name] = definition
        self.stats[definition.name] = ToolUsageStats(tool_name=definition.name)

        if implementation:
            self.implementations[definition.name] = implementation

        # Register aliases
        if definition.aliases:
            for alias in definition.aliases:
                if alias in self.aliases:
                    self.logger.warning(f"Alias '{alias}' already registered, overwriting")
                self.aliases[alias] = definition.name

        self.logger.info(f"Registered tool: {definition.name}")

    def unregister(self, tool_name: str) -> bool:
        """
        Unregister a tool.

        Args:
            tool_name: Tool name to unregister

        Returns:
            True if unregistered, False if not found
        """
        if tool_name not in self.tools:
            return False

        definition = self.tools[tool_name]

        # Remove main registration
        del self.tools[tool_name]

        # Remove aliases
        if definition.aliases:
            for alias in definition.aliases:
                if alias in self.aliases:
                    del self.aliases[alias]

        # Remove implementation
        if tool_name in self.implementations:
            del self.implementations[tool_name]

        # Keep stats for history
        self.logger.info(f"Unregistered tool: {tool_name}")
        return True

    def get_tool(self, tool_name: str) -> Optional[ToolDefinition]:
        """
        Get tool definition by name or alias.

        Args:
            tool_name: Tool name or alias

        Returns:
            Tool definition or None if not found
        """
        # Try direct name first
        if tool_name in self.tools:
            return self.tools[tool_name]

        # Try alias
        if tool_name in self.aliases:
            actual_name = self.aliases[tool_name]
            return self.tools.get(actual_name)

        return None

    def get_implementation(self, tool_name: str) -> Optional[Callable]:
        """
        Get tool implementation.

        Args:
            tool_name: Tool name (resolves aliases)

        Returns:
            Implementation function or None
        """
        # Resolve alias
        actual_name = self.aliases.get(tool_name, tool_name)
        return self.implementations.get(actual_name)

    def list_tools(
        self,
        category: Optional[ToolCategory] = None,
        risk_tier: Optional[RiskTier] = None,
        tag: Optional[str] = None
    ) -> List[ToolDefinition]:
        """
        List tools with optional filtering.

        Args:
            category: Filter by category
            risk_tier: Filter by risk tier
            tag: Filter by tag

        Returns:
            List of matching tool definitions
        """
        results = list(self.tools.values())

        if category:
            results = [t for t in results if t.category == category]

        if risk_tier:
            results = [t for t in results if t.risk_tier == risk_tier]

        if tag:
            results = [t for t in results if tag in (t.tags or [])]

        return results

    def get_stats(self, tool_name: str) -> Optional[ToolUsageStats]:
        """Get tool usage statistics."""
        return self.stats.get(tool_name)

    def get_all_stats(self) -> Dict[str, ToolUsageStats]:
        """Get statistics for all tools."""
        return self.stats.copy()

    def record_execution(
        self,
        tool_name: str,
        success: bool,
        execution_time_ms: float,
        error: Optional[str] = None
    ) -> None:
        """
        Record tool execution statistics.

        Args:
            tool_name: Tool name
            success: Whether execution succeeded
            execution_time_ms: Execution time
            error: Error message if failed
        """
        if tool_name not in self.stats:
            self.stats[tool_name] = ToolUsageStats(tool_name=tool_name)

        stats = self.stats[tool_name]
        stats.total_calls += 1

        if success:
            stats.successful_calls += 1
        else:
            stats.failed_calls += 1
            stats.last_error = error

        stats.total_execution_time_ms += execution_time_ms
        stats.last_called = datetime.utcnow().isoformat() + "Z"
        stats.average_execution_time_ms = (
            stats.total_execution_time_ms / stats.total_calls
        )

    def export_catalog(self) -> Dict[str, Any]:
        """
        Export complete tool catalog.

        Returns:
            JSON-serializable catalog
        """
        return {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "total_tools": len(self.tools),
            "tools": {
                name: tool.to_dict()
                for name, tool in self.tools.items()
            },
            "stats": {
                name: stats.to_dict()
                for name, stats in self.stats.items()
            }
        }

    def import_catalog(self, catalog_path: str) -> bool:
        """
        Import tools from catalog file.

        Args:
            catalog_path: Path to catalog JSON file

        Returns:
            True if successful
        """
        try:
            with open(catalog_path, 'r') as f:
                catalog = json.load(f)

            for tool_data in catalog.get("tools", {}).values():
                # Reconstruct ToolDefinition from data
                parameters = [
                    ToolParameter(
                        name=p["name"],
                        type=p["type"],
                        required=p["required"],
                        description=p["description"],
                        default=p.get("default"),
                        enum=p.get("enum"),
                        min_value=p.get("min_value"),
                        max_value=p.get("max_value"),
                        pattern=p.get("pattern")
                    )
                    for p in tool_data.get("parameters", [])
                ]

                definition = ToolDefinition(
                    name=tool_data["name"],
                    description=tool_data["description"],
                    category=ToolCategory(tool_data["category"]),
                    risk_tier=RiskTier(tool_data["risk_tier"]),
                    parameters=parameters,
                    returns=tool_data["returns"],
                    examples=tool_data.get("examples"),
                    aliases=tool_data.get("aliases"),
                    deprecated=tool_data.get("deprecated", False),
                    version=tool_data.get("version", "1.0.0"),
                    author=tool_data.get("author", "system"),
                    tags=tool_data.get("tags"),
                    requires_approval=tool_data.get("requires_approval", False),
                    requires_authentication=tool_data.get("requires_authentication", False),
                    rate_limit=tool_data.get("rate_limit"),
                    timeout_seconds=tool_data.get("timeout_seconds", 30)
                )

                self.register(definition)

            self.logger.info(f"Imported {len(self.tools)} tools from {catalog_path}")
            return True

        except Exception as e:
            self.logger.error(f"Failed to import catalog: {e}")
            return False

    def health_check(self) -> Dict[str, Any]:
        """
        Get health status of tool registry.

        Returns:
            Health status information
        """
        # Calculate aggregate stats
        total_calls = sum(s.total_calls for s in self.stats.values())
        successful_calls = sum(s.successful_calls for s in self.stats.values())
        failed_calls = sum(s.failed_calls for s in self.stats.values())

        overall_success_rate = (
            (successful_calls / total_calls * 100) if total_calls > 0 else 0
        )

        # Find problematic tools
        problematic_tools = [
            {
                "name": s.tool_name,
                "success_rate": s.success_rate,
                "last_error": s.last_error
            }
            for s in self.stats.values()
            if s.total_calls > 0 and s.success_rate < 90
        ]

        return {
            "status": "healthy" if overall_success_rate >= 95 else "degraded",
            "total_tools": len(self.tools),
            "total_calls": total_calls,
            "successful_calls": successful_calls,
            "failed_calls": failed_calls,
            "overall_success_rate": round(overall_success_rate, 2),
            "problematic_tools": problematic_tools,
            "timestamp": datetime.utcnow().isoformat() + "Z"
        }


# Global registry instance
_registry = None


def get_registry() -> ToolRegistry:
    """Get global tool registry instance."""
    global _registry
    if _registry is None:
        _registry = ToolRegistry()
    return _registry
