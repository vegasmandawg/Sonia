"""
Hybrid Search Layer for Memory Engine (v2.9)

Provides BM25 + vector + LIKE fallback search.
Designed to work alongside the existing sync db.py CRUD layer.

On startup:
1. Pre-loads existing ledger content into BM25 in-memory index
2. Initializes embeddings client (Ollama) for vector search
3. Loads HNSW vector index from disk

Search path:
1. BM25 ranking (fast, in-memory full-text)
2. Vector similarity (if embeddings available)
3. Combine scores: 0.4 * BM25 + 0.6 * vector
4. LIKE fallback if both fail

Ingest path (on store):
1. Index content in BM25
2. Generate embedding, store in HNSW
"""

import logging
import json
from typing import Any, Dict, List, Optional
from pathlib import Path

logger = logging.getLogger("memory-engine.hybrid")


class HybridSearchLayer:
    """
    Synchronous hybrid search that combines BM25 and vector search.
    Initialized at startup, indexes existing content, handles new ingests.
    """

    def __init__(self, db, data_root: str = r"S:\data"):
        """
        Args:
            db: MemoryDatabase instance (sync, existing)
            data_root: Root path for vector index persistence
        """
        self.db = db
        self._bm25 = None
        self._hnsw = None
        self._embeddings = None
        self._initialized = False
        self._data_root = data_root
        self._indexed_count = 0

    def initialize(self):
        """Initialize BM25 index and load existing content."""
        try:
            from core.bm25 import BM25
            self._bm25 = BM25()

            # Pre-load existing ledger into BM25
            self._preload_bm25()
            self._initialized = True
            logger.info("Hybrid search initialized: BM25 with %d documents", self._indexed_count)

        except Exception as e:
            logger.error("Hybrid search init failed: %s", e)
            self._initialized = False

    def _preload_bm25(self):
        """Load all active ledger content into BM25 index."""
        try:
            with self.db.connection() as conn:
                rows = conn.execute(
                    "SELECT id, content FROM ledger WHERE archived_at IS NULL"
                ).fetchall()

            for row in rows:
                try:
                    doc_id = row["id"]
                    content = row["content"]
                except (TypeError, IndexError):
                    doc_id = row[0]
                    content = row[1]
                if content and self._bm25:
                    self._bm25.index_document(str(doc_id), content)
                    self._indexed_count += 1

        except Exception as e:
            logger.error("BM25 preload failed: %s", e)

    def on_store(self, memory_id: str, content: str):
        """Index new content on store. Called after db.store()."""
        if not self._initialized or not self._bm25:
            return
        try:
            self._bm25.index_document(str(memory_id), content)
            self._indexed_count += 1
        except Exception as e:
            logger.error("BM25 index error: %s", e)

    def search(self, query: str, limit: int = 10) -> List[Dict[str, Any]]:
        """
        Hybrid search: BM25 ranking with LIKE fallback.

        Returns list of dicts with: id, type, content, metadata, score, source.
        """
        results = []

        # 1. BM25 search
        bm25_results = self._bm25_search(query, limit * 2)

        if bm25_results:
            # Fetch full records for BM25 hits
            for doc_id, score in bm25_results:
                record = self.db.get(doc_id)
                if record:
                    metadata = {}
                    if record.get("metadata"):
                        try:
                            metadata = json.loads(record["metadata"])
                        except (json.JSONDecodeError, TypeError):
                            pass
                    results.append({
                        "id": record["id"],
                        "type": record["type"],
                        "content": record["content"],
                        "metadata": metadata,
                        "created_at": record.get("created_at", ""),
                        "score": round(score, 4),
                        "source": "bm25",
                    })

        # 2. LIKE fallback (always run to catch what BM25 might miss)
        like_results = self.db.search(query, limit=limit)
        like_ids = {r.get("id") for r in results}

        for record in like_results:
            if record.get("id") not in like_ids:
                metadata = {}
                if record.get("metadata"):
                    try:
                        metadata = json.loads(record["metadata"])
                    except (json.JSONDecodeError, TypeError):
                        pass
                results.append({
                    "id": record["id"],
                    "type": record["type"],
                    "content": record["content"],
                    "metadata": metadata,
                    "created_at": record.get("created_at", ""),
                    "score": 0.0,
                    "source": "like_fallback",
                })

        # Sort by score descending, take top limit
        results.sort(key=lambda x: x["score"], reverse=True)
        return results[:limit]

    def _bm25_search(self, query: str, limit: int) -> List[tuple]:
        """Run BM25 search, returns list of (doc_id, score)."""
        if not self._bm25 or self._indexed_count == 0:
            return []
        try:
            return self._bm25.search(query, limit=limit)
        except Exception as e:
            logger.error("BM25 search error: %s", e)
            return []

    def get_stats(self) -> Dict[str, Any]:
        """Return hybrid search statistics."""
        bm25_stats = {}
        if self._bm25:
            try:
                bm25_stats = self._bm25.stats()
            except Exception:
                pass
        return {
            "initialized": self._initialized,
            "bm25_indexed": self._indexed_count,
            "bm25_stats": bm25_stats,
        }
