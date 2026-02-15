"""
API Gateway — Structured JSONL Logger (Stage 3)

Append-only JSONL files for sessions, turns, tools, and errors.
Each logger writes to a separate file under S:\\logs\\gateway\\.
"""

import json
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

# Try to import shared paths module; fall back to hardcoded path
try:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "shared"))
    from paths import LOGS_GATEWAY_DIR
    LOG_DIR = LOGS_GATEWAY_DIR
except ImportError:
    LOG_DIR = Path(r"S:\logs\gateway")

logger = logging.getLogger("api-gateway.jsonl")


class JsonlLogger:
    """Append-only JSONL writer for a single log stream."""

    def __init__(self, name: str, directory: Path = LOG_DIR):
        directory.mkdir(parents=True, exist_ok=True)
        self._path = directory / f"{name}.jsonl"
        self._count = 0

    def log(self, record: Dict[str, Any]):
        record.setdefault("ts", datetime.now(timezone.utc).isoformat())
        try:
            line = json.dumps(record, default=str)
            with open(self._path, "a", encoding="utf-8") as f:
                f.write(line + "\n")
            self._count += 1
        except Exception as exc:
            logger.warning("jsonl write failed (%s): %s", self._path.name, exc)

    @property
    def count(self) -> int:
        return self._count

    @property
    def path(self) -> str:
        return str(self._path)


# Singleton loggers
session_log = JsonlLogger("sessions")
turn_log = JsonlLogger("turns")
tool_log = JsonlLogger("tools")
error_log = JsonlLogger("errors")
