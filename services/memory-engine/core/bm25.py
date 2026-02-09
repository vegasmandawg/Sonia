"""BM25 full-text search ranking algorithm."""

import logging
import math
from typing import Dict, List, Set
from collections import defaultdict

logger = logging.getLogger(__name__)


class BM25:
    """BM25 (Best Matching 25) ranking algorithm for full-text search."""

    def __init__(
        self,
        k1: float = 1.5,
        b: float = 0.75,
        min_df: int = 1,
    ):
        """
        Initialize BM25 ranker.

        Args:
            k1: Controls term saturation (default 1.5)
            b: Controls length normalization (default 0.75)
            min_df: Minimum document frequency for term
        """
        self.k1 = k1
        self.b = b
        self.min_df = min_df
        
        # Index data structures
        self.documents: Dict[str, str] = {}  # doc_id -> content
        self.doc_freqs: Dict[str, Dict[str, int]] = defaultdict(lambda: defaultdict(int))
        self.idf_cache: Dict[str, float] = {}
        self.doc_lengths: Dict[str, int] = {}
        self.avg_doc_length = 0.0
        self.num_docs = 0

    def index_document(self, doc_id: str, content: str) -> None:
        """
        Index a document for BM25 ranking.

        Args:
            doc_id: Unique document identifier
            content: Document text content
        """
        # Tokenize (simple whitespace + lowercase)
        tokens = self._tokenize(content)
        
        self.documents[doc_id] = content
        self.doc_lengths[doc_id] = len(tokens)
        
        # Update document frequencies
        unique_tokens = set(tokens)
        for token in unique_tokens:
            self.doc_freqs[token][doc_id] += 1
        
        # Recompute statistics
        self.num_docs = len(self.documents)
        total_length = sum(self.doc_lengths.values())
        self.avg_doc_length = total_length / self.num_docs if self.num_docs > 0 else 0
        
        # Invalidate IDF cache
        self.idf_cache.clear()
        
        logger.debug(f"Indexed document {doc_id} ({len(tokens)} tokens)")

    def index_batch(self, documents: Dict[str, str]) -> None:
        """Index multiple documents."""
        for doc_id, content in documents.items():
            self.index_document(doc_id, content)

    def search(
        self,
        query: str,
        limit: int = 10,
    ) -> List[tuple]:
        """
        Search documents using BM25 ranking.

        Args:
            query: Search query string
            limit: Maximum results to return

        Returns:
            List of (doc_id, score) tuples, sorted by score descending
        """
        query_tokens = self._tokenize(query)
        
        if not query_tokens or not self.documents:
            logger.warning("Empty query or index")
            return []

        # Calculate BM25 scores
        scores: Dict[str, float] = defaultdict(float)

        for token in set(query_tokens):
            # Skip rare tokens
            doc_freq = len(self.doc_freqs.get(token, {}))
            if doc_freq < self.min_df:
                continue

            idf = self._get_idf(token)
            
            # Score each document containing this token
            for doc_id, freq in self.doc_freqs.get(token, {}).items():
                doc_len = self.doc_lengths.get(doc_id, 0)
                
                # BM25 formula
                numerator = freq * (self.k1 + 1)
                denominator = (
                    freq + self.k1 * (
                        1 - self.b + self.b * (doc_len / self.avg_doc_length)
                    )
                )
                
                scores[doc_id] += idf * (numerator / denominator)

        # Sort by score descending
        ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)
        
        logger.debug(
            f"BM25 search '{query}': {len(ranked)} results, "
            f"top score {ranked[0][1] if ranked else 0:.2f}"
        )
        
        return ranked[:limit]

    def _get_idf(self, token: str) -> float:
        """Compute IDF (Inverse Document Frequency) for token."""
        if token in self.idf_cache:
            return self.idf_cache[token]

        doc_freq = len(self.doc_freqs.get(token, {}))
        
        if doc_freq == 0:
            idf = 0.0
        else:
            # IDF formula: log((N - df + 0.5) / (df + 0.5))
            idf = math.log(
                (self.num_docs - doc_freq + 0.5) / (doc_freq + 0.5)
            )
        
        self.idf_cache[token] = idf
        return idf

    @staticmethod
    def _tokenize(text: str) -> List[str]:
        """
        Simple tokenization (whitespace + lowercase).

        In production, would use advanced tokenizer (spaCy, NLTK, etc.)
        """
        # Convert to lowercase, split on whitespace
        tokens = text.lower().split()
        
        # Remove punctuation and empty tokens
        cleaned = []
        for token in tokens:
            # Remove common punctuation
            cleaned_token = token.strip(".,;:!?\"'()[]{}").strip()
            if cleaned_token and len(cleaned_token) > 1:  # Skip single chars
                cleaned.append(cleaned_token)
        
        return cleaned

    def clear(self) -> None:
        """Clear all indexed documents."""
        self.documents.clear()
        self.doc_freqs.clear()
        self.idf_cache.clear()
        self.doc_lengths.clear()
        self.num_docs = 0
        self.avg_doc_length = 0.0
        logger.info("BM25 index cleared")

    def stats(self) -> Dict[str, any]:
        """Return index statistics."""
        unique_tokens = len(self.doc_freqs)
        return {
            "num_documents": self.num_docs,
            "unique_tokens": unique_tokens,
            "avg_doc_length": self.avg_doc_length,
            "idf_cache_size": len(self.idf_cache),
        }
