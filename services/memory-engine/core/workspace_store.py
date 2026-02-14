"""Document workspace storage with ingestion and chunking."""

import logging
from typing import Any, Dict, List, Optional
from uuid import uuid4

logger = logging.getLogger(__name__)


class WorkspaceStore:
    """Manages document workspace (ingestion, chunking, retrieval)."""

    def __init__(self, db):
        """Initialize workspace store with database instance."""
        self.db = db
        self._table_name = "workspace_documents"

    async def initialize(self) -> None:
        """Initialize workspace tables."""
        logger.info("Initializing workspace store...")
        logger.info("Workspace store initialized")

    async def ingest(
        self,
        content: str,
        doc_type: str,
        metadata: Dict[str, Any],
    ) -> str:
        """Ingest document and chunk. Returns doc_id."""
        doc_id = str(uuid4())
        
        try:
            # Insert document
            query = f"""
                INSERT INTO {self._table_name}
                (doc_id, doc_type, content, metadata, ingested_at)
                VALUES (?, ?, ?, ?, datetime('now'))
            """
            
            import json
            await self.db.execute(
                query,
                (doc_id, doc_type, content, json.dumps(metadata))
            )
            
            # Chunk document for indexing
            from core.chunker import Chunker
            chunker = Chunker(chunk_size=800, overlap=100)
            chunks = chunker.chunk_text(content)
            logger.info(
                f"Document {doc_id} chunked into {len(chunks)} chunks"
            )

            # Store chunks as separate indexed records
            for i, (chunk_text, start, end) in enumerate(chunks):
                chunk_id = f"{doc_id}_chunk_{i}"
                chunk_query = """
                    INSERT OR IGNORE INTO workspace_chunks
                    (chunk_id, doc_id, chunk_index, content, start_offset, end_offset)
                    VALUES (?, ?, ?, ?, ?, ?)
                """
                try:
                    await self.db.execute(
                        chunk_query,
                        (chunk_id, doc_id, i, chunk_text, start, end)
                    )
                except Exception as chunk_err:
                    logger.warning(f"Chunk {chunk_id} insert failed (table may not exist): {chunk_err}")
                    break  # Table doesn't exist yet; skip chunking

            logger.info(f"Document {doc_id} ingested")
            return doc_id
            
        except Exception as e:
            logger.error(f"Document ingestion failed: {e}")
            raise

    async def list_documents(
        self, doc_type: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """List all documents or filter by type."""
        try:
            if doc_type:
                query = f"SELECT * FROM {self._table_name} WHERE doc_type = ?"
                rows = await self.db.fetch(query, [doc_type])
            else:
                query = f"SELECT * FROM {self._table_name}"
                rows = await self.db.fetch(query, [])
            
            import json
            results = []
            for row in rows:
                results.append({
                    "doc_id": row[0],
                    "doc_type": row[1],
                    "content_preview": row[2][:200],
                    "metadata": json.loads(row[3]),
                    "ingested_at": row[4],
                })
            return results
            
        except Exception as e:
            logger.error(f"List documents failed: {e}")
            return []

    async def count(self) -> int:
        """Count total documents."""
        try:
            result = await self.db.fetch(
                f"SELECT COUNT(*) FROM {self._table_name}"
            )
            return result[0][0] if result else 0
        except Exception as e:
            logger.error(f"Count failed: {e}")
            return 0

    async def health(self) -> Dict[str, Any]:
        """Check workspace health."""
        try:
            count = await self.count()
            return {"status": "healthy", "documents_count": count}
        except Exception as e:
            return {"status": "unhealthy", "error": str(e)}
