"""
Pipecat - Session Management
Session lifecycle and state management for WebSocket connections.
"""

from enum import Enum
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any
from datetime import datetime
import uuid
import json
from pathlib import Path


class SessionState(Enum):
    """Session lifecycle states."""
    CREATED = "CREATED"
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    CLOSED = "CLOSED"


@dataclass
class Message:
    """A message in session history."""
    role: str  # "user" or "assistant"
    content: str
    timestamp: datetime = field(default_factory=datetime.utcnow)
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "role": self.role,
            "content": self.content,
            "timestamp": self.timestamp.isoformat() + "Z",
            "metadata": self.metadata
        }


@dataclass
class Session:
    """A user session."""
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    state: SessionState = field(default=SessionState.CREATED)
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)
    metadata: Dict[str, Any] = field(default_factory=dict)
    messages: List[Message] = field(default_factory=list)
    
    def add_message(self, role: str, content: str, metadata: Optional[Dict[str, Any]] = None):
        """Add a message to session history."""
        msg = Message(role=role, content=content, metadata=metadata or {})
        self.messages.append(msg)
        self.updated_at = datetime.utcnow()
    
    def get_messages(self, limit: Optional[int] = None) -> List[Dict[str, Any]]:
        """Get message history (most recent first if limit provided)."""
        msgs = [m.to_dict() for m in self.messages]
        if limit:
            return msgs[-limit:]
        return msgs
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert session to dictionary."""
        return {
            "id": self.id,
            "state": self.state.value,
            "created_at": self.created_at.isoformat() + "Z",
            "updated_at": self.updated_at.isoformat() + "Z",
            "metadata": self.metadata,
            "message_count": len(self.messages)
        }


class SessionManager:
    """
    Manage session lifecycle.
    In-memory storage with optional persistence to disk.
    """
    
    def __init__(self, persist_dir: Optional[str] = None):
        """
        Initialize session manager.
        
        Args:
            persist_dir: Optional directory for session persistence
        """
        self.sessions: Dict[str, Session] = {}
        self.persist_dir = Path(persist_dir) if persist_dir else None
        
        if self.persist_dir:
            self.persist_dir.mkdir(parents=True, exist_ok=True)
    
    def create(self, user_id: Optional[str] = None, metadata: Optional[Dict[str, Any]] = None) -> Session:
        """
        Create new session.
        
        Args:
            user_id: Optional user ID
            metadata: Optional session metadata
        
        Returns:
            Created session
        """
        session = Session(
            metadata={
                "user_id": user_id,
                **(metadata or {})
            }
        )
        self.sessions[session.id] = session
        session.state = SessionState.ACTIVE
        
        self._persist(session)
        return session
    
    def get(self, session_id: str) -> Optional[Session]:
        """
        Get session by ID.
        
        Args:
            session_id: Session ID
        
        Returns:
            Session or None if not found
        """
        return self.sessions.get(session_id)
    
    def list(self, state: Optional[SessionState] = None) -> List[Session]:
        """
        List sessions, optionally filtered by state.
        
        Args:
            state: Optional state filter
        
        Returns:
            List of sessions
        """
        sessions = list(self.sessions.values())
        if state:
            sessions = [s for s in sessions if s.state == state]
        return sessions
    
    def update(self, session_id: str, state: Optional[SessionState] = None, 
              metadata_update: Optional[Dict[str, Any]] = None) -> Optional[Session]:
        """
        Update session state and/or metadata.
        
        Args:
            session_id: Session ID
            state: Optional new state
            metadata_update: Optional metadata to merge
        
        Returns:
            Updated session or None if not found
        """
        session = self.sessions.get(session_id)
        if not session:
            return None
        
        if state:
            session.state = state
        if metadata_update:
            session.metadata.update(metadata_update)
        
        session.updated_at = datetime.utcnow()
        self._persist(session)
        return session
    
    def close(self, session_id: str) -> Optional[Session]:
        """
        Close session (set state to CLOSED).
        
        Args:
            session_id: Session ID
        
        Returns:
            Closed session or None if not found
        """
        session = self.sessions.get(session_id)
        if not session:
            return None
        
        session.state = SessionState.CLOSED
        session.updated_at = datetime.utcnow()
        self._persist(session)
        return session
    
    def delete(self, session_id: str) -> bool:
        """
        Delete session.
        
        Args:
            session_id: Session ID
        
        Returns:
            True if deleted, False if not found
        """
        if session_id not in self.sessions:
            return False
        
        del self.sessions[session_id]
        
        # Also delete persisted file if exists
        if self.persist_dir:
            persist_file = self.persist_dir / f"{session_id}.json"
            persist_file.unlink(missing_ok=True)
        
        return True
    
    def _persist(self, session: Session):
        """Persist session to disk if persistence enabled."""
        if not self.persist_dir:
            return
        
        persist_file = self.persist_dir / f"{session.id}.json"
        
        data = {
            "id": session.id,
            "state": session.state.value,
            "created_at": session.created_at.isoformat() + "Z",
            "updated_at": session.updated_at.isoformat() + "Z",
            "metadata": session.metadata,
            "messages": [m.to_dict() for m in session.messages]
        }
        
        with open(persist_file, 'w') as f:
            json.dump(data, f, indent=2)
    
    def load_persisted(self):
        """Load persisted sessions from disk."""
        if not self.persist_dir or not self.persist_dir.exists():
            return
        
        for persist_file in self.persist_dir.glob("*.json"):
            try:
                with open(persist_file, 'r') as f:
                    data = json.load(f)
                
                session = Session(
                    id=data["id"],
                    state=SessionState(data["state"]),
                    created_at=datetime.fromisoformat(data["created_at"].rstrip("Z")),
                    updated_at=datetime.fromisoformat(data["updated_at"].rstrip("Z")),
                    metadata=data.get("metadata", {})
                )
                
                # Restore messages
                for msg_data in data.get("messages", []):
                    msg = Message(
                        role=msg_data["role"],
                        content=msg_data["content"],
                        timestamp=datetime.fromisoformat(msg_data["timestamp"].rstrip("Z")),
                        metadata=msg_data.get("metadata", {})
                    )
                    session.messages.append(msg)
                
                self.sessions[session.id] = session
            
            except Exception as e:
                print(f"Failed to load session from {persist_file}: {e}")
