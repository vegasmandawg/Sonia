"""
Pipecat - Event Types
WebSocket event types and serialization.
"""

from enum import Enum
from dataclasses import dataclass, field, asdict
from typing import Dict, Any, Optional
from datetime import datetime
import json


class EventType(Enum):
    """WebSocket event types."""
    MESSAGE = "MESSAGE"
    SESSION_START = "SESSION_START"
    SESSION_STOP = "SESSION_STOP"
    STATUS = "STATUS"
    ERROR = "ERROR"


@dataclass
class Event:
    """WebSocket event."""
    type: EventType
    session_id: str
    data: Dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=datetime.utcnow)
    correlation_id: str = field(default_factory=lambda: "")
    
    def to_json(self) -> str:
        """Serialize event to JSON string."""
        return json.dumps(self.to_dict())
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert event to dictionary."""
        return {
            "type": self.type.value,
            "session_id": self.session_id,
            "data": self.data,
            "timestamp": self.timestamp.isoformat() + "Z",
            "correlation_id": self.correlation_id
        }
    
    @staticmethod
    def from_dict(data: Dict[str, Any]) -> "Event":
        """Create event from dictionary."""
        return Event(
            type=EventType(data["type"]),
            session_id=data["session_id"],
            data=data.get("data", {}),
            timestamp=datetime.fromisoformat(data.get("timestamp", datetime.utcnow().isoformat()).rstrip("Z")),
            correlation_id=data.get("correlation_id", "")
        )
    
    @staticmethod
    def from_json(json_str: str) -> "Event":
        """Create event from JSON string."""
        return Event.from_dict(json.loads(json_str))


class MessageEvent(Event):
    """A message event."""
    
    def __init__(self, session_id: str, text: str, role: str = "user",
                 timestamp: Optional[datetime] = None, correlation_id: str = ""):
        """
        Create message event.
        
        Args:
            session_id: Session ID
            text: Message text
            role: Message role (user, assistant)
            timestamp: Optional timestamp
            correlation_id: Optional correlation ID
        """
        super().__init__(
            type=EventType.MESSAGE,
            session_id=session_id,
            data={
                "text": text,
                "role": role
            },
            timestamp=timestamp or datetime.utcnow(),
            correlation_id=correlation_id
        )


class SessionStartEvent(Event):
    """Session start event."""
    
    def __init__(self, session_id: str, metadata: Optional[Dict[str, Any]] = None,
                 timestamp: Optional[datetime] = None, correlation_id: str = ""):
        """
        Create session start event.
        
        Args:
            session_id: Session ID
            metadata: Optional session metadata
            timestamp: Optional timestamp
            correlation_id: Optional correlation ID
        """
        super().__init__(
            type=EventType.SESSION_START,
            session_id=session_id,
            data={
                "metadata": metadata or {}
            },
            timestamp=timestamp or datetime.utcnow(),
            correlation_id=correlation_id
        )


class SessionStopEvent(Event):
    """Session stop event."""
    
    def __init__(self, session_id: str, reason: str = "user_requested",
                 timestamp: Optional[datetime] = None, correlation_id: str = ""):
        """
        Create session stop event.
        
        Args:
            session_id: Session ID
            reason: Reason for stopping (user_requested, timeout, error, etc.)
            timestamp: Optional timestamp
            correlation_id: Optional correlation ID
        """
        super().__init__(
            type=EventType.SESSION_STOP,
            session_id=session_id,
            data={
                "reason": reason
            },
            timestamp=timestamp or datetime.utcnow(),
            correlation_id=correlation_id
        )


class StatusEvent(Event):
    """Status event."""
    
    def __init__(self, session_id: str, status: str, details: Optional[Dict[str, Any]] = None,
                 timestamp: Optional[datetime] = None, correlation_id: str = ""):
        """
        Create status event.
        
        Args:
            session_id: Session ID
            status: Status string (online, processing, idle, error, etc.)
            details: Optional status details
            timestamp: Optional timestamp
            correlation_id: Optional correlation ID
        """
        super().__init__(
            type=EventType.STATUS,
            session_id=session_id,
            data={
                "status": status,
                "details": details or {}
            },
            timestamp=timestamp or datetime.utcnow(),
            correlation_id=correlation_id
        )


class ErrorEvent(Event):
    """Error event."""
    
    def __init__(self, session_id: str, error_code: str, error_message: str,
                 details: Optional[Dict[str, Any]] = None,
                 timestamp: Optional[datetime] = None, correlation_id: str = ""):
        """
        Create error event.
        
        Args:
            session_id: Session ID
            error_code: Error code
            error_message: Human-readable error message
            details: Optional error details
            timestamp: Optional timestamp
            correlation_id: Optional correlation ID
        """
        super().__init__(
            type=EventType.ERROR,
            session_id=session_id,
            data={
                "code": error_code,
                "message": error_message,
                "details": details or {}
            },
            timestamp=timestamp or datetime.utcnow(),
            correlation_id=correlation_id
        )
