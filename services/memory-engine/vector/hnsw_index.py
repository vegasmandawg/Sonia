"""HNSW vector index for approximate nearest neighbor search."""

import asyncio
import json
import logging
import math
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from collections import defaultdict

logger = logging.getLogger(__name__)


class HNSWIndex:
    """
    HNSW (Hierarchical Navigable Small World) vector index.

    Simplified implementation for approximate nearest neighbor search.
    Uses cosine similarity for distance metric.
    """

    def __init__(
        self,
        index_path: str = "S:\\data\\vector\\sonia.hnsw",
        dim: int = 1536,
        ef_construction: int = 200,
        M: int = 16,
        max_m: int = 32,
    ):
        """
        Initialize HNSW index.

        Args:
            index_path: Path to persist index
            dim: Vector dimension
            ef_construction: Effort parameter during construction
            M: Maximum number of connections for each node
            max_m: Limit for M (default 2*M)
        """
        self.index_path = Path(index_path)
        self.index_path.parent.mkdir(parents=True, exist_ok=True)
        self.dim = dim
        self.ef_construction = ef_construction
        self.M = M
        self.max_m = max_m
        
        # In-memory index structure
        self.vectors: Dict[str, List[float]] = {}  # id -> vector
        self.graph: Dict[str, List[str]] = defaultdict(list)  # id -> neighbors
        self.metadata: Dict[str, Dict[str, Any]] = {}  # id -> metadata
        self.entry_point: Optional[str] = None
        self._initialized = False

    async def initialize(self) -> None:
        """Initialize or load HNSW index."""
        try:
            logger.info(f"Initializing HNSW index: {self.index_path}")
            
            # Try to load existing index
            if self.index_path.exists():
                await self._load_index()
            else:
                logger.info("Creating new HNSW index")
            
            self._initialized = True
            logger.info(f"HNSW index initialized with {len(self.vectors)} vectors")
            
        except Exception as e:
            logger.error(f"HNSW initialization failed: {e}")
            self._initialized = False

    async def add_vectors(
        self,
        vectors: List[List[float]],
        ids: List[str],
        metadata: Optional[List[Dict[str, Any]]] = None,
    ) -> None:
        """
        Add vectors to index.

        Args:
            vectors: List of embedding vectors
            ids: List of corresponding IDs
            metadata: Optional metadata for each vector
        """
        if len(vectors) != len(ids):
            raise ValueError("Vectors and IDs must have same length")

        try:
            for i, (vec, vec_id) in enumerate(zip(vectors, ids)):
                if len(vec) != self.dim:
                    logger.warning(
                        f"Vector {vec_id} has {len(vec)} dims, "
                        f"expected {self.dim}, padding/truncating"
                    )
                    vec = self._normalize_vector(vec)

                self.vectors[vec_id] = vec
                if metadata and i < len(metadata):
                    self.metadata[vec_id] = metadata[i]

                # Insert into HNSW graph
                if not self.entry_point:
                    self.entry_point = vec_id
                else:
                    await self._insert_into_graph(vec_id, vec)

            logger.debug(f"Added {len(vectors)} vectors to index")
            
            # Persist index periodically
            if len(self.vectors) % 100 == 0:
                await self._save_index()

        except Exception as e:
            logger.error(f"Failed to add vectors: {e}")
            raise

    async def search(
        self,
        query_vector: List[float],
        k: int = 10,
        ef: int = 100,
    ) -> List[Dict[str, Any]]:
        """
        Search for k nearest neighbors.

        Args:
            query_vector: Query embedding vector
            k: Number of results to return
            ef: Effort parameter (trade-off between speed/accuracy)

        Returns:
            List of dicts with id, distance, metadata
        """
        if not self.vectors or not self.entry_point:
            logger.warning("Index is empty")
            return []

        try:
            # Normalize query vector
            query_vector = self._normalize_vector(query_vector)

            # Search graph starting from entry point
            results = await self._knn_search(
                query_vector, k=k, ef=ef
            )

            # Format results
            formatted_results = []
            for vec_id, distance in results:
                formatted_results.append({
                    "id": vec_id,
                    "distance": distance,
                    "similarity": 1.0 - distance,  # Convert distance to similarity
                    "metadata": self.metadata.get(vec_id, {}),
                })

            logger.debug(f"Search returned {len(formatted_results)} results")
            return formatted_results

        except Exception as e:
            logger.error(f"Vector search failed: {e}")
            return []

    async def _knn_search(
        self,
        query: List[float],
        k: int,
        ef: int,
    ) -> List[Tuple[str, float]]:
        """
        K-nearest neighbors search in HNSW graph.

        Args:
            query: Query vector
            k: Number of neighbors
            ef: Effort parameter

        Returns:
            List of (id, distance) tuples, sorted by distance
        """
        if not self.entry_point:
            return []

        # Greedy search for ef candidates
        visited = set()
        candidates = [(self._cosine_distance(query, self.vectors[self.entry_point]), 
                      self.entry_point)]
        w = [self.entry_point]

        while candidates:
            lowerbound = candidates[0][0]
            
            if lowerbound > min(
                [self._cosine_distance(query, self.vectors[vec_id]) 
                 for vec_id in w]
            ):
                break

            current_nearest = min(
                candidates, key=lambda x: x[0]
            )
            candidates.remove(current_nearest)

            if current_nearest[0] > lowerbound:
                break

            neighbors = self.graph.get(current_nearest[1], [])
            for neighbor_id in neighbors:
                if neighbor_id not in visited:
                    visited.add(neighbor_id)
                    distance = self._cosine_distance(
                        query, self.vectors[neighbor_id]
                    )

                    if distance < max(
                        [self._cosine_distance(query, self.vectors[v]) 
                         for v in w]
                    ) or len(w) < ef:
                        candidates.append((distance, neighbor_id))
                        w.append(neighbor_id)
                        w = sorted(w, 
                                  key=lambda x: self._cosine_distance(query, self.vectors[x]))[:ef]

        # Return top k
        w_sorted = sorted(
            w,
            key=lambda x: self._cosine_distance(query, self.vectors[x])
        )
        return [
            (vec_id, self._cosine_distance(query, self.vectors[vec_id]))
            for vec_id in w_sorted[:k]
        ]

    async def _insert_into_graph(
        self, vec_id: str, vector: List[float]
    ) -> None:
        """Insert new vector into HNSW graph."""
        # Find M nearest neighbors
        candidates = []
        for existing_id, existing_vec in list(self.vectors.items())[:100]:
            if existing_id != vec_id:
                distance = self._cosine_distance(vector, existing_vec)
                candidates.append((distance, existing_id))

        # Keep top M
        candidates = sorted(candidates)[:self.M]

        # Add edges
        for _, neighbor_id in candidates:
            self.graph[vec_id].append(neighbor_id)
            self.graph[neighbor_id].append(vec_id)

            # Prune if exceeds max_m
            if len(self.graph[neighbor_id]) > self.max_m:
                self.graph[neighbor_id] = sorted(
                    self.graph[neighbor_id],
                    key=lambda x: self._cosine_distance(
                        self.vectors[neighbor_id],
                        self.vectors[x]
                    )
                )[:self.max_m]

    @staticmethod
    def _cosine_distance(vec1: List[float], vec2: List[float]) -> float:
        """
        Compute cosine distance (1 - similarity).

        Args:
            vec1: First vector
            vec2: Second vector

        Returns:
            Distance in [0, 2]
        """
        dot_product = sum(a * b for a, b in zip(vec1, vec2))
        norm1 = math.sqrt(sum(a * a for a in vec1))
        norm2 = math.sqrt(sum(b * b for b in vec2))

        if norm1 == 0 or norm2 == 0:
            return 2.0  # Maximum distance for zero vectors

        similarity = dot_product / (norm1 * norm2)
        return 1.0 - max(-1.0, min(1.0, similarity))

    @staticmethod
    def _normalize_vector(vector: List[float]) -> List[float]:
        """Normalize vector to target dimension (pad or truncate)."""
        target_dim = 1536
        if len(vector) < target_dim:
            return vector + [0.0] * (target_dim - len(vector))
        return vector[:target_dim]

    async def count(self) -> int:
        """Count vectors in index."""
        return len(self.vectors)

    async def size_mb(self) -> float:
        """Get index size in MB."""
        try:
            if self.index_path.exists():
                return self.index_path.stat().st_size / (1024 * 1024)
            return 0.0
        except Exception as e:
            logger.error(f"Size check failed: {e}")
            return 0.0

    async def health(self) -> Dict[str, Any]:
        """Check index health."""
        try:
            count = await self.count()
            return {
                "status": "healthy",
                "vectors_count": count,
                "graph_nodes": len(self.graph),
                "initialized": self._initialized,
            }
        except Exception as e:
            return {"status": "unhealthy", "error": str(e)}

    async def _save_index(self) -> None:
        """Persist index to disk."""
        try:
            index_data = {
                "vectors": self.vectors,
                "graph": {k: list(v) for k, v in self.graph.items()},
                "metadata": self.metadata,
                "entry_point": self.entry_point,
                "dim": self.dim,
            }
            
            with open(self.index_path, 'w') as f:
                json.dump(index_data, f)
            
            logger.debug(f"Index saved to {self.index_path}")
        except Exception as e:
            logger.error(f"Failed to save index: {e}")

    async def _load_index(self) -> None:
        """Load index from disk."""
        try:
            with open(self.index_path, 'r') as f:
                index_data = json.load(f)

            self.vectors = index_data.get("vectors", {})
            self.graph = defaultdict(list, {
                k: list(v) for k, v in index_data.get("graph", {}).items()
            })
            self.metadata = index_data.get("metadata", {})
            self.entry_point = index_data.get("entry_point")
            
            logger.info(f"Loaded index with {len(self.vectors)} vectors")
        except Exception as e:
            logger.error(f"Failed to load index: {e}")

    async def shutdown(self) -> None:
        """Shutdown vector index (persist on exit)."""
        try:
            await self._save_index()
            logger.info("HNSW index shutdown")
        except Exception as e:
            logger.error(f"Shutdown error: {e}")
