"""
Memory Engine Service
=====================

Persistent, searchable memory with durable ledger, vector embeddings,
and provenance tracking. Core component of Sonia's reasoning system.

Features:
- Append-only event ledger with ACID guarantees
- Bi-temporal storage (valid_time + transaction_time)
- Semantic search via vector embeddings
- Full-text search via BM25
- Document ingestion pipeline
- Memory decay and forgetting strategies
- Snapshot management for context optimization
- Provenance tracking (source document + span location)
- Sensitive data redaction
- Audit trail for compliance

Version: 1.0.0
"""

__version__ = "1.0.0"
__author__ = "Sonia Team"
__license__ = "MIT"

import logging

logger = logging.getLogger(__name__)
logger.info(f"Memory Engine v{__version__} initialized")
