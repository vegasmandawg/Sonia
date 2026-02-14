"""Hybrid retrieval engine (semantic + BM25)."""

import logging
from typing import Any, Dict, List, Optional
import numpy as np

from .bm25 import BM25
from .embeddings_client import EmbeddingsClient

logger = logging.getLogger(__name__)


class Retriever:
    """Hybrid search combining semantic and BM25 ranking."""

    def __init__(
        self,
        ledger,
        workspace,
        vector_index,
        embeddings_client: Optional[EmbeddingsClient] = None,
        semantic_weight: float = 0.6,
        bm25_weight: float = 0.4,
    ):
        """
        Initialize retriever with storage backends.

        Args:
            ledger: LedgerStore instance
            workspace: WorkspaceStore instance
            vector_index: HNSWIndex instance
            embeddings_client: EmbeddingsClient instance
            semantic_weight: Weight for semantic search (0-1)
            bm25_weight: Weight for BM25 search (0-1)
        """
        self.ledger = ledger
        self.workspace = workspace
        self.vector = vector_index
        self.embeddings = embeddings_client or EmbeddingsClient()
        self.semantic_weight = semantic_weight
        self.bm25_weight = bm25_weight
        self.bm25_index = BM25()
        self._indexed_chunks: set = set()  # Track indexed chunks

    async def initialize(self) -> None:
        """Initialize retriever components."""
        try:
            await self.embeddings.initialize()
            logger.info("Retriever initialized")
        except Exception as e:
            logger.error(f"Retriever initialization failed: {e}")

    async def search(
        self,
        query: str,
        limit: int = 10,
        include_scores: bool = True,
        semantic_only: bool = False,
    ) -> List[Dict[str, Any]]:
        """
        Hybrid search: semantic + BM25 ranking.

        1. Generate query embedding
        2. Vector search (cosine similarity)
        3. BM25 full-text search
        4. Normalize scores
        5. Combine (weighted average)
        6. Sort by combined score

        Args:
            query: Search query string
            limit: Number of results to return
            include_scores: Include detailed scores in results
            semantic_only: Skip BM25, semantic search only

        Returns:
            List of results with score, relevance, and metadata
        """
        try:
            results_by_id = {}
            
            # 1. Semantic search (vector similarity)
            semantic_results = await self._semantic_search(
                query, limit=limit * 2
            )
            
            for result in semantic_results:
                chunk_id = result["id"]
                results_by_id[chunk_id] = {
                    "chunk_id": chunk_id,
                    "content": result.get("metadata", {}).get("content", ""),
                    "semantic_score": result["similarity"],
                    "bm25_score": 0.0,
                    "metadata": result.get("metadata", {}),
                }

            # 2. BM25 search (unless disabled)
            if not semantic_only:
                bm25_results = await self._bm25_search(query, limit=limit * 2)
                
                for chunk_id, bm25_score in bm25_results:
                    if chunk_id in results_by_id:
                        results_by_id[chunk_id]["bm25_score"] = bm25_score
                    else:
                        # Add BM25-only result
                        results_by_id[chunk_id] = {
                            "chunk_id": chunk_id,
                            "content": "",
                            "semantic_score": 0.0,
                            "bm25_score": bm25_score,
                            "metadata": {},
                        }

            # 3. Normalize and combine scores
            combined_results = self._combine_scores(results_by_id)

            # 4. Sort by combined score
            combined_results.sort(
                key=lambda x: x["combined_score"], reverse=True
            )

            # 5. Format results
            final_results = []
            for result in combined_results[:limit]:
                formatted = {
                    "chunk_id": result["chunk_id"],
                    "content": result["content"],
                    "relevance": result["combined_score"],
                    "provenance": result.get("metadata", {}),
                }
                
                if include_scores:
                    formatted["scores"] = {
                        "semantic": result["semantic_score"],
                        "bm25": result["bm25_score"],
                        "combined": result["combined_score"],
                    }

                final_results.append(formatted)

            logger.info(f"Search '{query}': {len(final_results)} results")
            return final_results

        except Exception as e:
            logger.error(f"Search failed: {e}")
            raise

    async def _semantic_search(
        self, query: str, limit: int = 20
    ) -> List[Dict[str, Any]]:
        """
        Semantic search using vector embeddings.

        Args:
            query: Search query
            limit: Number of results

        Returns:
            List of results from vector search
        """
        try:
            # Generate query embedding
            query_embedding = await self.embeddings.embed(query)
            status_fn = getattr(self.embeddings, "status", None)
            if callable(status_fn):
                embedding_status = status_fn()
                if embedding_status.get("degraded"):
                    logger.warning(
                        "Semantic search running with degraded embeddings: %s",
                        embedding_status.get("degraded_reason"),
                    )
            
            # Search vector index
            results = await self.vector.search(
                query_embedding, k=limit, ef=100
            )
            
            logger.debug(f"Semantic search returned {len(results)} results")
            return results

        except Exception as e:
            logger.error(f"Semantic search failed: {e}")
            return []

    async def _bm25_search(
        self, query: str, limit: int = 20
    ) -> List[tuple]:
        """
        BM25 full-text search.

        Args:
            query: Search query
            limit: Number of results

        Returns:
            List of (chunk_id, score) tuples
        """
        try:
            # BM25 search
            results = self.bm25_index.search(query, limit=limit)
            
            logger.debug(f"BM25 search returned {len(results)} results")
            return results

        except Exception as e:
            logger.error(f"BM25 search failed: {e}")
            return []

    def _combine_scores(
        self, results_by_id: Dict[str, Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """
        Combine semantic and BM25 scores.

        Normalizes both to [0, 1] and combines with weighted average.

        Args:
            results_by_id: Dict mapping chunk_id to scores

        Returns:
            List of results with combined_score
        """
        # Find max scores for normalization
        max_semantic = max(
            (r["semantic_score"] for r in results_by_id.values()),
            default=1.0,
        )
        max_bm25 = max(
            (r["bm25_score"] for r in results_by_id.values()),
            default=1.0,
        )

        # Normalize and combine
        combined = []
        for chunk_id, result in results_by_id.items():
            sem_norm = (result["semantic_score"] / max_semantic) if max_semantic > 0 else 0
            bm25_norm = (result["bm25_score"] / max_bm25) if max_bm25 > 0 else 0

            combined_score = (
                self.semantic_weight * sem_norm +
                self.bm25_weight * bm25_norm
            )

            result["combined_score"] = combined_score
            combined.append(result)

        return combined

    async def search_by_entity(
        self, entity_id: str, limit: int = 50
    ) -> List[Dict[str, Any]]:
        """
        Search all memory related to specific entity.

        Args:
            entity_id: Entity identifier
            limit: Maximum results

        Returns:
            List of related events/items
        """
        try:
            # Query ledger for entity events
            events = await self.ledger.query(
                entity_id=entity_id,
                limit=limit,
            )
            
            # Format as results
            results = []
            for event in events:
                results.append({
                    "event_id": event["event_id"],
                    "event_type": event["event_type"],
                    "timestamp": event["timestamp"],
                    "payload": event["payload"],
                    "relevance": 1.0,
                })
            
            logger.info(
                f"Entity search for {entity_id}: {len(results)} results"
            )
            return results

        except Exception as e:
            logger.error(f"Entity search failed: {e}")
            raise

    def index_chunk(
        self, chunk_id: str, content: str, metadata: Dict[str, Any]
    ) -> None:
        """
        Index chunk for full-text search.

        Args:
            chunk_id: Unique chunk identifier
            content: Chunk text content
            metadata: Associated metadata
        """
        if chunk_id not in self._indexed_chunks:
            self.bm25_index.index_document(chunk_id, content)
            self._indexed_chunks.add(chunk_id)
            logger.debug(f"Indexed chunk {chunk_id} for BM25")

    async def shutdown(self) -> None:
        """Shutdown retriever components."""
        try:
            await self.embeddings.shutdown()
            logger.info("Retriever shutdown complete")
        except Exception as e:
            logger.error(f"Shutdown error: {e}")
