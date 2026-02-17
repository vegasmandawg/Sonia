"""
Hybrid Search Layer for Memory Engine (v4.3 Epic B)

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

import asyncio
import logging
import json
import time
from typing import Any, Dict, List, Optional
from pathlib import Path

logger = logging.getLogger("memory-engine.hybrid")


class HybridSearchLayer:
    """
    Synchronous hybrid search that combines BM25 and vector search.
    Initialized at startup, indexes existing content, handles new ingests.

    Vector search (HNSW + embeddings) is initialized separately via
    initialize_vector() and used through async_search().  The sync
    search() method remains as BM25 + LIKE fallback for callers that
    cannot await.
    """

    def __init__(
        self,
        db,
        data_root: str = r"S:\data",
        embeddings_client=None,
        hnsw_index=None,
    ):
        """
        Args:
            db: MemoryDatabase instance (sync, existing)
            data_root: Root path for vector index persistence
            embeddings_client: Optional pre-built EmbeddingsClient
            hnsw_index: Optional pre-built HNSWIndex
        """
        self.db = db
        self._bm25 = None
        self._hnsw = hnsw_index
        self._embeddings = embeddings_client
        self._initialized = False
        self._vector_initialized = False
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

    async def initialize_vector(self):
        """Initialize HNSW vector index and embeddings client.

        Steps:
        1. Create EmbeddingsClient and verify connectivity.
        2. Create/load HNSWIndex from disk.
        3. If HNSW is empty but BM25 has documents, backfill vectors.
        4. Save HNSW index after backfill.
        """
        try:
            # 1. Embeddings client
            if self._embeddings is None:
                from core.embeddings_client import EmbeddingsClient
                self._embeddings = EmbeddingsClient()
            await self._embeddings.initialize()

            # 2. HNSW index
            if self._hnsw is None:
                from vector.hnsw_index import HNSWIndex
                index_path = str(Path(self._data_root) / "vector" / "sonia.hnsw")
                self._hnsw = HNSWIndex(index_path=index_path)
            await self._hnsw.initialize()

            hnsw_count = await self._hnsw.count()
            logger.info(
                "Vector subsystem loaded: %d vectors, embeddings provider=%s",
                hnsw_count,
                self._embeddings.provider,
            )

            # 3. Backfill: BM25 has docs but HNSW is empty
            if hnsw_count == 0 and self._indexed_count > 0:
                await self._backfill_vectors()

            self._vector_initialized = True
            logger.info("Vector search initialized successfully")

        except Exception as e:
            logger.error("Vector search init failed (BM25+LIKE still active): %s", e)
            self._vector_initialized = False

    async def _backfill_vectors(self):
        """Embed all existing ledger content and add to HNSW index."""
        logger.info("Backfilling HNSW from %d BM25 documents...", self._indexed_count)
        t0 = time.monotonic()
        try:
            with self.db.connection() as conn:
                rows = conn.execute(
                    "SELECT id, content FROM ledger WHERE archived_at IS NULL"
                ).fetchall()

            if not rows:
                return

            batch_size = 32
            total_added = 0
            for i in range(0, len(rows), batch_size):
                batch = rows[i : i + batch_size]
                ids = []
                texts = []
                for row in batch:
                    try:
                        doc_id = row["id"]
                        content = row["content"]
                    except (TypeError, IndexError):
                        doc_id = row[0]
                        content = row[1]
                    if content:
                        ids.append(str(doc_id))
                        texts.append(content)

                if not texts:
                    continue

                embeddings = await self._embeddings.embed_batch(texts)
                await self._hnsw.add_vectors(
                    vectors=embeddings,
                    ids=ids,
                    metadata=[{"content": t[:200]} for t in texts],
                )
                total_added += len(ids)

            # Persist after backfill
            await self._hnsw._save_index()

            elapsed_ms = (time.monotonic() - t0) * 1000
            logger.info(
                "Backfill complete: %d vectors added in %.0f ms",
                total_added,
                elapsed_ms,
            )

            # Write manifest after backfill
            try:
                from vector.index_manifest import IndexManifest
                manifest = IndexManifest(str(self._hnsw.index_path))
                await manifest.write(
                    entry_count=total_added,
                    build_duration_ms=elapsed_ms,
                )
            except Exception as me:
                logger.warning("Manifest write after backfill failed: %s", me)

        except Exception as e:
            logger.error("Vector backfill failed: %s", e)

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
        """Index new content in BM25. Called after db.store()."""
        if not self._initialized or not self._bm25:
            return
        try:
            self._bm25.index_document(str(memory_id), content)
            self._indexed_count += 1
        except Exception as e:
            logger.error("BM25 index error: %s", e)

    async def on_store_async(self, memory_id: str, content: str):
        """Generate embedding and add to HNSW index (fire-and-forget safe).

        Should be called after on_store() for vector indexing.
        Errors are logged but never raised to avoid blocking the store path.
        """
        if not self._vector_initialized or not self._embeddings or not self._hnsw:
            return
        try:
            embedding = await self._embeddings.embed(content)
            await self._hnsw.add_vectors(
                vectors=[embedding],
                ids=[str(memory_id)],
                metadata=[{"content": content[:200]}],
            )
            logger.debug("Vector indexed: %s", memory_id)
        except Exception as e:
            logger.warning("Vector index for %s failed (non-fatal): %s", memory_id, e)

    def search(self, query: str, limit: int = 10) -> List[Dict[str, Any]]:
        """
        Sync hybrid search: BM25 ranking with LIKE fallback.
        Does NOT use vector search (use async_search for full hybrid).

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

    async def async_search(self, query: str, limit: int = 10) -> List[Dict[str, Any]]:
        """
        Full hybrid search: BM25 + Vector + LIKE fallback.

        Scoring:
        - 0.4 * normalized BM25 score
        - 0.6 * normalized vector similarity
        - LIKE fallback fills gaps with score 0.0

        Returns list of dicts with: id, type, content, metadata, score, source.
        """
        results_by_id: Dict[str, Dict[str, Any]] = {}

        # ── 1. BM25 search ───────────────────────────────────────────────
        bm25_results = self._bm25_search(query, limit * 2)
        bm25_scores: Dict[str, float] = {}
        for doc_id, score in bm25_results:
            record = self.db.get(doc_id)
            if record:
                metadata = {}
                if record.get("metadata"):
                    try:
                        metadata = json.loads(record["metadata"])
                    except (json.JSONDecodeError, TypeError):
                        pass
                results_by_id[record["id"]] = {
                    "id": record["id"],
                    "type": record["type"],
                    "content": record["content"],
                    "metadata": metadata,
                    "created_at": record.get("created_at", ""),
                    "bm25_score": score,
                    "vector_score": 0.0,
                    "source": "bm25",
                }
                bm25_scores[record["id"]] = score

        # ── 2. Vector search ─────────────────────────────────────────────
        vector_scores: Dict[str, float] = {}
        if self._vector_initialized and self._embeddings and self._hnsw:
            try:
                query_embedding = await self._embeddings.embed(query)
                vector_results = await self._hnsw.search(query_embedding, k=limit * 2)
                for vr in vector_results:
                    vec_id = vr["id"]
                    similarity = vr.get("similarity", 0.0)
                    vector_scores[vec_id] = similarity

                    if vec_id not in results_by_id:
                        # Fetch full record for vector-only hit
                        record = self.db.get(vec_id)
                        if record:
                            metadata = {}
                            if record.get("metadata"):
                                try:
                                    metadata = json.loads(record["metadata"])
                                except (json.JSONDecodeError, TypeError):
                                    pass
                            results_by_id[vec_id] = {
                                "id": record["id"],
                                "type": record["type"],
                                "content": record["content"],
                                "metadata": metadata,
                                "created_at": record.get("created_at", ""),
                                "bm25_score": 0.0,
                                "vector_score": similarity,
                                "source": "vector",
                            }
                        else:
                            # Vector hit without ledger record -- skip
                            continue
                    else:
                        results_by_id[vec_id]["vector_score"] = similarity
                        results_by_id[vec_id]["source"] = "hybrid"

            except Exception as e:
                logger.warning("Vector search failed (BM25 still active): %s", e)

        # ── 3. Combine scores ────────────────────────────────────────────
        max_bm25 = max(bm25_scores.values(), default=1.0) or 1.0
        max_vector = max(vector_scores.values(), default=1.0) or 1.0

        for rid, entry in results_by_id.items():
            norm_bm25 = entry["bm25_score"] / max_bm25
            norm_vector = entry["vector_score"] / max_vector
            entry["score"] = round(0.4 * norm_bm25 + 0.6 * norm_vector, 4)

        # ── 4. LIKE fallback for anything missed ─────────────────────────
        like_results = self.db.search(query, limit=limit)
        for record in like_results:
            if record.get("id") not in results_by_id:
                metadata = {}
                if record.get("metadata"):
                    try:
                        metadata = json.loads(record["metadata"])
                    except (json.JSONDecodeError, TypeError):
                        pass
                results_by_id[record["id"]] = {
                    "id": record["id"],
                    "type": record["type"],
                    "content": record["content"],
                    "metadata": metadata,
                    "created_at": record.get("created_at", ""),
                    "bm25_score": 0.0,
                    "vector_score": 0.0,
                    "score": 0.0,
                    "source": "like_fallback",
                }

        # ── 5. Sort and return ───────────────────────────────────────────
        combined = list(results_by_id.values())
        combined.sort(key=lambda x: x["score"], reverse=True)

        # Strip internal score fields before returning
        final = []
        for entry in combined[:limit]:
            final.append({
                "id": entry["id"],
                "type": entry["type"],
                "content": entry["content"],
                "metadata": entry["metadata"],
                "created_at": entry["created_at"],
                "score": entry["score"],
                "source": entry["source"],
            })
        return final

    def _bm25_search(self, query: str, limit: int) -> List[tuple]:
        """Run BM25 search, returns list of (doc_id, score)."""
        if not self._bm25 or self._indexed_count == 0:
            return []
        try:
            return self._bm25.search(query, limit=limit)
        except Exception as e:
            logger.error("BM25 search error: %s", e)
            return []

    async def save_index(self):
        """Persist HNSW index to disk (call on shutdown)."""
        if not self._vector_initialized or not self._hnsw:
            return
        try:
            t0 = time.monotonic()
            await self._hnsw._save_index()
            elapsed_ms = (time.monotonic() - t0) * 1000
            count = await self._hnsw.count()
            logger.info("HNSW index saved: %d vectors in %.0f ms", count, elapsed_ms)

            # Write manifest
            try:
                from vector.index_manifest import IndexManifest
                manifest = IndexManifest(str(self._hnsw.index_path))
                await manifest.write(
                    entry_count=count,
                    build_duration_ms=elapsed_ms,
                )
            except Exception as me:
                logger.warning("Manifest write on save failed: %s", me)

        except Exception as e:
            logger.error("HNSW save failed: %s", e)

    def get_stats(self) -> Dict[str, Any]:
        """Return hybrid search statistics."""
        bm25_stats = {}
        if self._bm25:
            try:
                bm25_stats = self._bm25.stats()
            except Exception:
                pass

        vector_stats = {
            "initialized": self._vector_initialized,
            "vector_count": 0,
            "embeddings_degraded": False,
        }
        if self._hnsw and self._vector_initialized:
            try:
                vector_stats["vector_count"] = len(self._hnsw.vectors)
                vector_stats["graph_nodes"] = len(self._hnsw.graph)
            except Exception:
                pass
        if self._embeddings:
            try:
                es = self._embeddings.status()
                vector_stats["embeddings_provider"] = es.get("provider")
                vector_stats["embeddings_degraded"] = es.get("degraded", False)
            except Exception:
                pass

        return {
            "initialized": self._initialized,
            "bm25_indexed": self._indexed_count,
            "bm25_stats": bm25_stats,
            "vector": vector_stats,
        }
