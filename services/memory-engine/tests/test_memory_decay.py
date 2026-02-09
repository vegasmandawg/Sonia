"""Tests for memory decay and forgetting."""

import pytest
from datetime import datetime, timedelta
from ..core.decay import MemoryDecay, DecayStrategy, MemoryConsolidation


class TestMemoryDecay:
    """Test memory decay computation."""

    def test_exponential_decay(self):
        """Test exponential decay computation."""
        decay = MemoryDecay(
            strategy=DecayStrategy.EXPONENTIAL,
            half_life_days=30.0,
        )
        
        # Fresh item
        now = datetime.utcnow().isoformat() + "Z"
        score = decay.compute_decay_score(now)
        assert score > 0.9
        
        # Item from 30 days ago (should be ~0.5)
        old = (datetime.utcnow() - timedelta(days=30)).isoformat() + "Z"
        score = decay.compute_decay_score(old)
        assert 0.4 < score < 0.6

    def test_linear_decay(self):
        """Test linear decay computation."""
        decay = MemoryDecay(
            strategy=DecayStrategy.LINEAR,
            half_life_days=30.0,
        )
        
        # Fresh item
        now = datetime.utcnow().isoformat() + "Z"
        score = decay.compute_decay_score(now)
        assert score > 0.95
        
        # Item from 15 days ago (should be ~0.5)
        old = (datetime.utcnow() - timedelta(days=15)).isoformat() + "Z"
        score = decay.compute_decay_score(old)
        assert 0.45 < score < 0.55

    def test_threshold_decay(self):
        """Test threshold decay computation."""
        decay = MemoryDecay(
            strategy=DecayStrategy.THRESHOLD,
            half_life_days=30.0,
        )
        
        # Fresh item (within threshold)
        now = datetime.utcnow().isoformat() + "Z"
        score = decay.compute_decay_score(now)
        assert score == 1.0
        
        # Old item (beyond threshold)
        old = (datetime.utcnow() - timedelta(days=40)).isoformat() + "Z"
        score = decay.compute_decay_score(old)
        assert score == 0.0

    def test_access_boost(self):
        """Test that accessed items decay slower."""
        decay = MemoryDecay(
            strategy=DecayStrategy.EXPONENTIAL,
            half_life_days=30.0,
        )
        
        created = (datetime.utcnow() - timedelta(days=20)).isoformat() + "Z"
        
        # No access
        score1 = decay.compute_decay_score(created, access_count=0)
        
        # With access
        score2 = decay.compute_decay_score(created, access_count=5)
        
        assert score2 > score1

    def test_should_forget(self):
        """Test forgetting decision."""
        decay = MemoryDecay(
            strategy=DecayStrategy.LINEAR,
            half_life_days=30.0,
            threshold_score=0.3,
        )
        
        # Fresh item should not be forgotten
        now = datetime.utcnow().isoformat() + "Z"
        assert not decay.should_forget(now)
        
        # Very old item should be forgotten
        old = (datetime.utcnow() - timedelta(days=100)).isoformat() + "Z"
        assert decay.should_forget(old)

    def test_compute_batch_decay(self):
        """Test batch decay computation."""
        decay = MemoryDecay(
            strategy=DecayStrategy.LINEAR,
            half_life_days=30.0,
            threshold_score=0.3,
        )
        
        items = [
            {
                "event_id": "e1",
                "created_time": datetime.utcnow().isoformat() + "Z",
                "access_count": 0,
                "relevance": 1.0,
            },
            {
                "event_id": "e2",
                "created_time": (
                    datetime.utcnow() - timedelta(days=100)
                ).isoformat() + "Z",
                "access_count": 0,
                "relevance": 1.0,
            },
        ]
        
        decayed = decay.compute_batch_decay(items)
        
        # Fresh item retained, old forgotten
        assert len(decayed) == 1
        assert decayed[0]["event_id"] == "e1"

    def test_adjust_ranking(self):
        """Test ranking adjustment by decay."""
        decay = MemoryDecay(
            strategy=DecayStrategy.EXPONENTIAL,
            half_life_days=30.0,
        )
        
        results = [
            {
                "chunk_id": "c1",
                "timestamp": datetime.utcnow().isoformat() + "Z",
                "relevance": 0.5,
                "access_count": 0,
            },
            {
                "chunk_id": "c2",
                "timestamp": (
                    datetime.utcnow() - timedelta(days=50)
                ).isoformat() + "Z",
                "relevance": 0.9,
                "access_count": 0,
            },
        ]
        
        adjusted = decay.adjust_ranking(results, decay_weight=0.5)
        
        # Fresh item ranks higher despite lower original relevance
        assert adjusted[0]["relevance"] > adjusted[1]["relevance"]


class TestMemoryConsolidation:
    """Test memory consolidation."""

    def test_consolidate_similar(self):
        """Test similar item consolidation."""
        items = [
            {"event_type": "user_turn", "content": "hello"},
            {"event_type": "user_turn", "content": "world"},
            {"event_type": "tool_call", "content": "action"},
        ]
        
        consolidated = MemoryConsolidation.consolidate_similar(items)
        
        # Should have fewer items (grouped by type)
        assert len(consolidated) < len(items)

    def test_compress_old_events(self):
        """Test separation of old and recent events."""
        now = datetime.utcnow()
        items = [
            {
                "event_id": "recent",
                "timestamp": now.isoformat() + "Z",
            },
            {
                "event_id": "old",
                "timestamp": (now - timedelta(days=50)).isoformat() + "Z",
            },
        ]
        
        compressed = MemoryConsolidation.compress_old_events(
            items,
            days_threshold=30,
        )
        
        # Check separation
        assert len(compressed["recent"]) == 1
        assert len(compressed["archived"]) == 1
        assert compressed["recent"][0]["event_id"] == "recent"
        assert compressed["archived"][0]["event_id"] == "old"
