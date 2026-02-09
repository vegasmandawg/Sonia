-- Migration: Provenance tracking
CREATE TABLE IF NOT EXISTS chunk_provenance (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  chunk_id TEXT NOT NULL,
  source_doc_id TEXT NOT NULL,
  start_offset INTEGER NOT NULL,
  end_offset INTEGER NOT NULL,
  confidence REAL,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  UNIQUE(chunk_id, source_doc_id)
);

CREATE INDEX idx_provenance_chunk ON chunk_provenance(chunk_id);
CREATE INDEX idx_provenance_doc ON chunk_provenance(source_doc_id);
