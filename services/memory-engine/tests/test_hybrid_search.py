"""Integration tests for hybrid search (semantic + BM25)."""

import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock
from pathlib import Path
import sys

MEMORY_ENGINE_DIR = Path(__file__).resolve().parents[1]
if str(MEMORY_ENGINE_DIR) not in sys.path:
    sys.path.insert(0, str(MEMORY_ENGINE_DIR))


@pytest.fixture
async def retriever():
    """Create retriever with mock components."""
    from core.retriever import Retriever
    from core.bm25 import BM25
    
    # Mock components
    ledger = AsyncMock()
    workspace = AsyncMock()
    vector = AsyncMock()
    embeddings = AsyncMock()
    
    retriever = Retriever(ledger, workspace, vector, embeddings)
    await retriever.initialize()
    return retriever


@pytest.mark.asyncio
async def test_hybrid_search_combines_scores(retriever):
    """Test that hybrid search combines semantic and BM25 scores."""
    # Mock embeddings
    retriever.embeddings.embed = AsyncMock(
        return_value=[0.1] * 1536
    )
    
    # Mock vector search results
    retriever.vector.search = AsyncMock(return_value=[
        {
            "id": "chunk1",
            "similarity": 0.95,
            "metadata": {"content": "test content 1"},
        },
        {
            "id": "chunk2",
            "similarity": 0.85,
            "metadata": {"content": "test content 2"},
        },
    ])
    
    # Index documents for BM25
    retriever.index_chunk("chunk1", "test content 1", {})
    retriever.index_chunk("chunk2", "test content 2", {})
    
    # Perform search
    results = await retriever.search("test query", limit=2)
    
    # Verify results
    assert len(results) > 0
    assert "relevance" in results[0]
    assert 0 <= results[0]["relevance"] <= 1


@pytest.mark.asyncio
async def test_semantic_only_search(retriever):
    """Test semantic-only search mode."""
    retriever.embeddings.embed = AsyncMock(
        return_value=[0.1] * 1536
    )
    
    retriever.vector.search = AsyncMock(return_value=[
        {
            "id": "chunk1",
            "similarity": 0.95,
            "metadata": {},
        },
    ])
    
    # Search with semantic_only=True
    results = await retriever.search(
        "test query",
        limit=1,
        semantic_only=True,
    )
    
    assert len(results) > 0


@pytest.mark.asyncio
async def test_search_empty_index(retriever):
    """Test search on empty index."""
    retriever.embeddings.embed = AsyncMock(
        return_value=[0.1] * 1536
    )
    retriever.vector.search = AsyncMock(return_value=[])
    
    results = await retriever.search("query", limit=10)
    assert len(results) == 0


@pytest.mark.asyncio
async def test_bm25_index_document(retriever):
    """Test BM25 document indexing."""
    retriever.index_chunk(
        "chunk1",
        "the quick brown fox jumps",
        {},
    )
    retriever.index_chunk(
        "chunk2",
        "the lazy brown dog sleeps",
        {},
    )
    
    # Verify documents indexed
    stats = retriever.bm25_index.stats()
    assert stats["num_documents"] == 2
    assert stats["unique_tokens"] > 0


@pytest.mark.asyncio
async def test_combine_scores_normalization(retriever):
    """Test score normalization and combination."""
    results_by_id = {
        "chunk1": {
            "chunk_id": "chunk1",
            "content": "test",
            "semantic_score": 0.9,
            "bm25_score": 0.8,
            "metadata": {},
        },
        "chunk2": {
            "chunk_id": "chunk2",
            "content": "test",
            "semantic_score": 0.7,
            "bm25_score": 0.6,
            "metadata": {},
        },
    }
    
    combined = retriever._combine_scores(results_by_id)
    
    # Verify combined scores in valid range
    for result in combined:
        assert 0 <= result["combined_score"] <= 1
        
    # Verify ranking order
    assert combined[0]["combined_score"] >= combined[1]["combined_score"]
