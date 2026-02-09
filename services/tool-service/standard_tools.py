"""
Standard Tool Implementations

Core tools for file operations, computation, and system operations.
"""

import asyncio
import json
import logging
import os
from typing import Any, Dict, List
from pathlib import Path

logger = logging.getLogger(__name__)


# ============================================================================
# Filesystem Tools
# ============================================================================

async def read_file(path: str, encoding: str = "utf-8") -> str:
    """
    Read file contents.

    Args:
        path: File path
        encoding: File encoding (default: utf-8)

    Returns:
        File contents

    Raises:
        FileNotFoundError: If file doesn't exist
        IOError: If read fails
    """
    try:
        def _read():
            with open(path, 'r', encoding=encoding) as f:
                return f.read()

        return await asyncio.to_thread(_read)

    except Exception as e:
        logger.error(f"Failed to read file {path}: {e}")
        raise


async def write_file(path: str, content: str, encoding: str = "utf-8") -> Dict[str, Any]:
    """
    Write content to file.

    Args:
        path: File path
        content: Content to write
        encoding: File encoding (default: utf-8)

    Returns:
        Dictionary with write result

    Raises:
        IOError: If write fails
    """
    try:
        def _write():
            # Ensure directory exists
            Path(path).parent.mkdir(parents=True, exist_ok=True)
            
            with open(path, 'w', encoding=encoding) as f:
                f.write(content)
            
            return {
                "path": path,
                "bytes_written": len(content.encode(encoding)),
                "encoding": encoding
            }

        return await asyncio.to_thread(_write)

    except Exception as e:
        logger.error(f"Failed to write file {path}: {e}")
        raise


async def append_file(path: str, content: str, encoding: str = "utf-8") -> Dict[str, Any]:
    """
    Append content to file.

    Args:
        path: File path
        content: Content to append
        encoding: File encoding

    Returns:
        Dictionary with append result
    """
    try:
        def _append():
            # Ensure directory exists
            Path(path).parent.mkdir(parents=True, exist_ok=True)
            
            with open(path, 'a', encoding=encoding) as f:
                f.write(content)
            
            return {
                "path": path,
                "bytes_appended": len(content.encode(encoding))
            }

        return await asyncio.to_thread(_append)

    except Exception as e:
        logger.error(f"Failed to append to file {path}: {e}")
        raise


async def list_directory(path: str, recursive: bool = False) -> List[str]:
    """
    List directory contents.

    Args:
        path: Directory path
        recursive: Include subdirectories

    Returns:
        List of file paths
    """
    try:
        def _list():
            base_path = Path(path)
            if not base_path.exists():
                raise FileNotFoundError(f"Directory not found: {path}")

            if recursive:
                return [str(p) for p in base_path.rglob('*')]
            else:
                return [str(p) for p in base_path.iterdir()]

        return await asyncio.to_thread(_list)

    except Exception as e:
        logger.error(f"Failed to list directory {path}: {e}")
        raise


async def get_file_info(path: str) -> Dict[str, Any]:
    """
    Get file metadata.

    Args:
        path: File path

    Returns:
        Dictionary with file info
    """
    try:
        def _info():
            file_path = Path(path)
            if not file_path.exists():
                raise FileNotFoundError(f"File not found: {path}")

            stat = file_path.stat()
            return {
                "path": str(file_path.absolute()),
                "exists": True,
                "is_file": file_path.is_file(),
                "is_dir": file_path.is_dir(),
                "size_bytes": stat.st_size,
                "created_timestamp": stat.st_ctime,
                "modified_timestamp": stat.st_mtime,
                "permissions": oct(stat.st_mode)[-3:]
            }

        return await asyncio.to_thread(_info)

    except Exception as e:
        logger.error(f"Failed to get file info for {path}: {e}")
        raise


async def file_exists(path: str) -> bool:
    """
    Check if file exists.

    Args:
        path: File path

    Returns:
        True if file exists
    """
    def _exists():
        return Path(path).exists()

    return await asyncio.to_thread(_exists)


# ============================================================================
# Computation Tools
# ============================================================================

async def evaluate_expression(expression: str) -> Any:
    """
    Safely evaluate mathematical expression.

    Args:
        expression: Mathematical expression

    Returns:
        Result of evaluation

    Raises:
        ValueError: If expression is invalid
    """
    try:
        # Safe evaluation - only numbers and operators
        import re
        
        # Validate expression contains only safe characters
        if not re.match(r'^[\d\s\+\-\*/\(\)\.]+$', expression):
            raise ValueError("Expression contains invalid characters")

        # Use ast.literal_eval for safety
        import ast
        result = eval(compile(ast.parse(expression, mode='eval'), '<string>', 'eval'))
        return result

    except Exception as e:
        logger.error(f"Failed to evaluate expression: {e}")
        raise ValueError(f"Invalid expression: {expression}")


async def search_text(text: str, pattern: str, case_sensitive: bool = False) -> List[Dict[str, Any]]:
    """
    Search for pattern in text.

    Args:
        text: Text to search
        pattern: Search pattern (regex)
        case_sensitive: Whether search is case-sensitive

    Returns:
        List of matches with positions
    """
    try:
        import re
        
        flags = 0 if case_sensitive else re.IGNORECASE
        regex = re.compile(pattern, flags)
        
        matches = []
        for match in regex.finditer(text):
            matches.append({
                "text": match.group(),
                "start": match.start(),
                "end": match.end(),
                "groups": match.groups()
            })
        
        return matches

    except Exception as e:
        logger.error(f"Text search failed: {e}")
        raise


async def parse_json(json_string: str) -> Dict[str, Any]:
    """
    Parse JSON string.

    Args:
        json_string: JSON string

    Returns:
        Parsed JSON object

    Raises:
        json.JSONDecodeError: If JSON is invalid
    """
    try:
        return json.loads(json_string)
    except json.JSONDecodeError as e:
        logger.error(f"JSON parsing failed: {e}")
        raise


# ============================================================================
# System Tools
# ============================================================================

async def get_environment_variable(name: str) -> str:
    """
    Get environment variable (read-only, safe variables).

    Args:
        name: Variable name

    Returns:
        Variable value

    Raises:
        KeyError: If variable not set
    """
    # Whitelist safe environment variables
    safe_vars = {
        "PATH", "HOME", "USER", "SHELL", "LANG",
        "TZ", "TERM", "PWD", "LOGNAME"
    }

    if name not in safe_vars:
        raise ValueError(f"Cannot access environment variable: {name}")

    value = os.environ.get(name)
    if value is None:
        raise KeyError(f"Environment variable not set: {name}")

    return value


async def get_system_info() -> Dict[str, Any]:
    """
    Get system information.

    Returns:
        Dictionary with system info
    """
    try:
        import platform
        import psutil
        
        return {
            "platform": platform.system(),
            "platform_release": platform.release(),
            "processor": platform.processor(),
            "python_version": platform.python_version(),
            "cpu_count": psutil.cpu_count(),
            "memory_total_gb": round(psutil.virtual_memory().total / (1024**3), 2),
            "memory_available_gb": round(psutil.virtual_memory().available / (1024**3), 2),
            "disk_usage_percent": psutil.disk_usage('/').percent
        }

    except Exception as e:
        logger.error(f"Failed to get system info: {e}")
        raise


async def get_current_time() -> Dict[str, str]:
    """
    Get current time.

    Returns:
        Dictionary with current time
    """
    from datetime import datetime
    
    now = datetime.utcnow()
    return {
        "iso_format": now.isoformat() + "Z",
        "unix_timestamp": now.timestamp(),
        "formatted": now.strftime("%Y-%m-%d %H:%M:%S UTC")
    }


# ============================================================================
# Network Tools
# ============================================================================

async def fetch_url(url: str, timeout: int = 30) -> Dict[str, Any]:
    """
    Fetch URL content.

    Args:
        url: URL to fetch
        timeout: Request timeout in seconds

    Returns:
        Dictionary with response data
    """
    try:
        import aiohttp
        
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=timeout) as response:
                content = await response.text()
                
                return {
                    "url": url,
                    "status_code": response.status,
                    "content_type": response.content_type,
                    "content_length": len(content),
                    "content": content[:10000]  # Limit to 10KB
                }

    except Exception as e:
        logger.error(f"Failed to fetch URL {url}: {e}")
        raise


async def resolve_hostname(hostname: str) -> Dict[str, Any]:
    """
    Resolve hostname to IP address.

    Args:
        hostname: Hostname to resolve

    Returns:
        Dictionary with DNS information
    """
    try:
        import socket
        
        def _resolve():
            ips = socket.gethostbyname_ex(hostname)
            return {
                "hostname": ips[0],
                "alias_list": ips[1],
                "ip_address_list": ips[2]
            }

        return await asyncio.to_thread(_resolve)

    except Exception as e:
        logger.error(f"Failed to resolve hostname {hostname}: {e}")
        raise


# ============================================================================
# Tool Registration Helpers
# ============================================================================

def register_standard_tools(registry) -> None:
    """
    Register all standard tools with registry.

    Args:
        registry: ToolRegistry instance
    """
    from tool_registry import (
        ToolDefinition,
        ToolParameter,
        ToolCategory,
        RiskTier
    )

    # Filesystem tools
    registry.register(
        ToolDefinition(
            name="read_file",
            description="Read file contents",
            category=ToolCategory.FILESYSTEM,
            risk_tier=RiskTier.TIER_0,
            parameters=[
                ToolParameter("path", "string", True, "File path"),
                ToolParameter("encoding", "string", False, "File encoding", default="utf-8")
            ],
            returns="File contents as string",
            tags=["io", "read-only"]
        ),
        implementation=read_file
    )

    registry.register(
        ToolDefinition(
            name="write_file",
            description="Write content to file",
            category=ToolCategory.FILESYSTEM,
            risk_tier=RiskTier.TIER_1,
            parameters=[
                ToolParameter("path", "string", True, "File path"),
                ToolParameter("content", "string", True, "Content to write"),
                ToolParameter("encoding", "string", False, "File encoding", default="utf-8")
            ],
            returns="Dictionary with write result",
            tags=["io", "write"],
            requires_approval=True
        ),
        implementation=write_file
    )

    registry.register(
        ToolDefinition(
            name="list_directory",
            description="List directory contents",
            category=ToolCategory.FILESYSTEM,
            risk_tier=RiskTier.TIER_0,
            parameters=[
                ToolParameter("path", "string", True, "Directory path"),
                ToolParameter("recursive", "boolean", False, "Include subdirectories", default=False)
            ],
            returns="List of file paths",
            tags=["io", "read-only"]
        ),
        implementation=list_directory
    )

    registry.register(
        ToolDefinition(
            name="get_file_info",
            description="Get file metadata",
            category=ToolCategory.FILESYSTEM,
            risk_tier=RiskTier.TIER_0,
            parameters=[
                ToolParameter("path", "string", True, "File path")
            ],
            returns="Dictionary with file metadata",
            tags=["io", "read-only"]
        ),
        implementation=get_file_info
    )

    # Computation tools
    registry.register(
        ToolDefinition(
            name="evaluate_expression",
            description="Safely evaluate mathematical expression",
            category=ToolCategory.COMPUTATION,
            risk_tier=RiskTier.TIER_0,
            parameters=[
                ToolParameter("expression", "string", True, "Mathematical expression")
            ],
            returns="Result of evaluation",
            tags=["math", "compute"]
        ),
        implementation=evaluate_expression
    )

    registry.register(
        ToolDefinition(
            name="search_text",
            description="Search for pattern in text",
            category=ToolCategory.COMPUTATION,
            risk_tier=RiskTier.TIER_0,
            parameters=[
                ToolParameter("text", "string", True, "Text to search"),
                ToolParameter("pattern", "string", True, "Search pattern (regex)"),
                ToolParameter("case_sensitive", "boolean", False, "Case-sensitive search", default=False)
            ],
            returns="List of matches with positions",
            tags=["text", "search"]
        ),
        implementation=search_text
    )

    registry.register(
        ToolDefinition(
            name="parse_json",
            description="Parse JSON string",
            category=ToolCategory.COMPUTATION,
            risk_tier=RiskTier.TIER_0,
            parameters=[
                ToolParameter("json_string", "string", True, "JSON string to parse")
            ],
            returns="Parsed JSON object",
            tags=["json", "parse"]
        ),
        implementation=parse_json
    )

    # System tools
    registry.register(
        ToolDefinition(
            name="get_current_time",
            description="Get current time",
            category=ToolCategory.SYSTEM,
            risk_tier=RiskTier.TIER_0,
            parameters=[],
            returns="Dictionary with current time",
            tags=["system", "time"]
        ),
        implementation=get_current_time
    )

    registry.register(
        ToolDefinition(
            name="get_system_info",
            description="Get system information",
            category=ToolCategory.SYSTEM,
            risk_tier=RiskTier.TIER_0,
            parameters=[],
            returns="Dictionary with system information",
            tags=["system", "info"]
        ),
        implementation=get_system_info
    )

    # Network tools
    registry.register(
        ToolDefinition(
            name="fetch_url",
            description="Fetch URL content",
            category=ToolCategory.NETWORK,
            risk_tier=RiskTier.TIER_2,
            parameters=[
                ToolParameter("url", "string", True, "URL to fetch"),
                ToolParameter("timeout", "integer", False, "Timeout in seconds", default=30, min_value=1, max_value=300)
            ],
            returns="Dictionary with response data",
            tags=["network", "http"],
            rate_limit=10  # 10 calls per minute
        ),
        implementation=fetch_url
    )

    registry.register(
        ToolDefinition(
            name="resolve_hostname",
            description="Resolve hostname to IP address",
            category=ToolCategory.NETWORK,
            risk_tier=RiskTier.TIER_1,
            parameters=[
                ToolParameter("hostname", "string", True, "Hostname to resolve")
            ],
            returns="Dictionary with DNS information",
            tags=["network", "dns"]
        ),
        implementation=resolve_hostname
    )

    logger.info("Registered standard tools")
