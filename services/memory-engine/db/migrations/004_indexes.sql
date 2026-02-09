-- Migration: Additional indexes for performance
CREATE INDEX IF NOT EXISTS idx_ledger_timestamp_entity 
  ON ledger_events(timestamp DESC, entity_id);

CREATE INDEX IF NOT EXISTS idx_chunks_doc_index 
  ON document_chunks(doc_id, chunk_index);

-- Full-text search indexes (if using SQLite FTS)
CREATE VIRTUAL TABLE IF NOT EXISTS ledger_fts USING fts5(
  payload,
  content='ledger_events',
  content_rowid='id'
);
