"""
Memory Engine Contract Tests

Validates that Memory Engine meets the BOOT_CONTRACT.md requirements:
- Health endpoints working
- CRUD operations functional
- Data persistence across restarts
- Search functionality
"""

import pytest
import json
import tempfile
import sys
from pathlib import Path

SERVICE_DIR = Path(__file__).resolve().parent
if str(SERVICE_DIR) not in sys.path:
    sys.path.insert(0, str(SERVICE_DIR))

from db import MemoryDatabase


class TestMemoryEngineContract:
    """Test suite for Memory Engine contract compliance."""
    
    @pytest.fixture
    def temp_db(self):
        """Create temporary test database."""
        with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as f:
            db_path = f.name
        
        db = MemoryDatabase(db_path)
        yield db
        
        # Cleanup
        Path(db_path).unlink(missing_ok=True)
    
    # ─────────────────────────────────────────────────────────────────────────
    # CREATE Tests
    # ─────────────────────────────────────────────────────────────────────────
    
    def test_store_fact(self, temp_db):
        """Store a fact memory."""
        memory_id = temp_db.store(
            memory_type="fact",
            content="Paris is the capital of France",
            metadata={"source": "geography"}
        )
        
        assert memory_id.startswith("mem_")
        
        memory = temp_db.get(memory_id)
        assert memory is not None
        assert memory['type'] == "fact"
        assert memory['content'] == "Paris is the capital of France"
    
    def test_store_preference(self, temp_db):
        """Store a preference memory."""
        memory_id = temp_db.store(
            memory_type="preference",
            content="User prefers verbose explanations",
            metadata={"category": "communication_style"}
        )
        
        assert memory_id.startswith("mem_")
        memory = temp_db.get(memory_id)
        assert memory['type'] == "preference"
    
    def test_store_multiple(self, temp_db):
        """Store multiple memories."""
        ids = []
        for i in range(5):
            memory_id = temp_db.store(
                memory_type="fact",
                content=f"Fact number {i}",
                metadata={"index": i}
            )
            ids.append(memory_id)
        
        assert len(ids) == 5
        assert len(set(ids)) == 5  # All unique
    
    # ─────────────────────────────────────────────────────────────────────────
    # READ Tests
    # ─────────────────────────────────────────────────────────────────────────
    
    def test_get_memory(self, temp_db):
        """Retrieve a memory by ID."""
        memory_id = temp_db.store(
            memory_type="fact",
            content="Test content",
            metadata={"test": True}
        )
        
        memory = temp_db.get(memory_id)
        
        assert memory is not None
        assert memory['id'] == memory_id
        assert memory['content'] == "Test content"
        assert memory['archived_at'] is None
    
    def test_get_nonexistent(self, temp_db):
        """Get non-existent memory returns None."""
        memory = temp_db.get("mem_nonexistent")
        assert memory is None
    
    def test_search_by_content(self, temp_db):
        """Search memories by content."""
        temp_db.store("fact", "The Earth orbits the Sun", {"domain": "astronomy"})
        temp_db.store("fact", "The Moon orbits Earth", {"domain": "astronomy"})
        temp_db.store("fact", "Python is a language", {"domain": "programming"})
        
        results = temp_db.search("Earth", limit=10)
        
        assert len(results) == 2
        assert any("Earth orbits" in r['content'] for r in results)
    
    def test_search_empty(self, temp_db):
        """Search with no matches returns empty list."""
        temp_db.store("fact", "Test memory", {})
        
        results = temp_db.search("nonexistent_word", limit=10)
        
        assert results == []
    
    def test_list_by_type(self, temp_db):
        """List memories by type."""
        temp_db.store("fact", "Fact 1", {})
        temp_db.store("fact", "Fact 2", {})
        temp_db.store("preference", "Pref 1", {})
        
        facts = temp_db.list_by_type("fact", limit=100)
        prefs = temp_db.list_by_type("preference", limit=100)
        
        assert len(facts) == 2
        assert len(prefs) == 1
    
    # ─────────────────────────────────────────────────────────────────────────
    # UPDATE Tests
    # ─────────────────────────────────────────────────────────────────────────
    
    def test_update_content(self, temp_db):
        """Update memory content."""
        memory_id = temp_db.store("fact", "Old content", {})
        
        success = temp_db.update(memory_id, content="New content")
        
        assert success is True
        
        updated = temp_db.get(memory_id)
        assert updated['content'] == "New content"
    
    def test_update_metadata(self, temp_db):
        """Update memory metadata."""
        memory_id = temp_db.store("fact", "Content", {"old": "value"})
        
        success = temp_db.update(memory_id, metadata={"new": "value"})
        
        assert success is True
        
        updated = temp_db.get(memory_id)
        metadata = json.loads(updated['metadata'])
        assert metadata['new'] == "value"
    
    def test_update_nonexistent(self, temp_db):
        """Update non-existent memory returns False."""
        success = temp_db.update("mem_nonexistent", content="New")
        assert success is False
    
    # ─────────────────────────────────────────────────────────────────────────
    # DELETE Tests (Soft Delete = Archive)
    # ─────────────────────────────────────────────────────────────────────────
    
    def test_soft_delete(self, temp_db):
        """Soft-delete (archive) a memory."""
        memory_id = temp_db.store("fact", "Content", {})
        
        success = temp_db.delete(memory_id)
        
        assert success is True
        
        # Should not appear in active list
        memory = temp_db.get(memory_id)
        assert memory is None
    
    def test_delete_nonexistent(self, temp_db):
        """Delete non-existent memory returns False."""
        success = temp_db.delete("mem_nonexistent")
        assert success is False
    
    # ─────────────────────────────────────────────────────────────────────────
    # Persistence Tests
    # ─────────────────────────────────────────────────────────────────────────
    
    def test_persistence_across_instances(self):
        """Data persists across database instances."""
        with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as f:
            db_path = f.name
        
        try:
            # Instance 1: Store data
            db1 = MemoryDatabase(db_path)
            memory_id = db1.store("fact", "Persistent data", {"test": True})
            
            # Instance 2: Retrieve data
            db2 = MemoryDatabase(db_path)
            memory = db2.get(memory_id)
            
            assert memory is not None
            assert memory['content'] == "Persistent data"
        
        finally:
            Path(db_path).unlink(missing_ok=True)
    
    # ─────────────────────────────────────────────────────────────────────────
    # Statistics Tests
    # ─────────────────────────────────────────────────────────────────────────
    
    def test_count(self, temp_db):
        """Count active memories."""
        temp_db.store("fact", "Memory 1", {})
        temp_db.store("fact", "Memory 2", {})
        temp_db.store("preference", "Pref 1", {})
        
        count = temp_db.count()
        
        assert count == 3
    
    def test_count_excludes_archived(self, temp_db):
        """Count excludes archived memories."""
        memory_id = temp_db.store("fact", "Memory", {})
        temp_db.store("fact", "Active", {})
        
        temp_db.delete(memory_id)
        
        count = temp_db.count()
        assert count == 1
    
    def test_stats(self, temp_db):
        """Get statistics."""
        temp_db.store("fact", "Fact 1", {})
        temp_db.store("fact", "Fact 2", {})
        temp_db.store("preference", "Pref 1", {})
        
        stats = temp_db.get_stats()
        
        assert stats['total_memories'] == 3
        assert stats['active_memories'] == 3
        assert stats['by_type']['fact'] == 2
        assert stats['by_type']['preference'] == 1
    
    # ─────────────────────────────────────────────────────────────────────────
    # Integration Tests
    # ─────────────────────────────────────────────────────────────────────────
    
    def test_crud_workflow(self, temp_db):
        """Complete CRUD workflow."""
        # Create
        memory_id = temp_db.store(
            "project",
            "Implement memory engine",
            {"status": "in_progress", "priority": "high"}
        )
        assert memory_id.startswith("mem_")
        
        # Read
        memory = temp_db.get(memory_id)
        assert memory['content'] == "Implement memory engine"
        
        # Update
        success = temp_db.update(
            memory_id,
            metadata={"status": "complete"}
        )
        assert success is True
        
        # Verify update
        updated = temp_db.get(memory_id)
        metadata = json.loads(updated['metadata'])
        assert metadata['status'] == "complete"
        
        # Delete
        success = temp_db.delete(memory_id)
        assert success is True
        
        # Verify deletion
        deleted = temp_db.get(memory_id)
        assert deleted is None


# Run tests if executed directly
if __name__ == "__main__":
    pytest.main([__file__, "-v"])
