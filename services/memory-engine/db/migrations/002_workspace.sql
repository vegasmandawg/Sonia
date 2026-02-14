-- Migration: Workspace documents and chunks
CREATE TABLE IF NOT EXISTS workspace_documents (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  doc_id TEXT UNIQUE NOT NULL,
  doc_type TEXT NOT NULL,
  content TEXT NOT NULL,
  metadata TEXT,
  ingested_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS workspace_chunks (
  chunk_id TEXT PRIMARY KEY,
  doc_id TEXT NOT NULL,
  content TEXT NOT NULL,
  chunk_index INTEGER NOT NULL,
  start_offset INTEGER,
  end_offset INTEGER,
  embedding_id TEXT,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY(doc_id) REFERENCES workspace_documents(doc_id)
);

CREATE INDEX IF NOT EXISTS idx_workspace_doc_id ON workspace_documents(doc_id);
CREATE INDEX IF NOT EXISTS idx_workspace_type ON workspace_documents(doc_type);
CREATE INDEX IF NOT EXISTS idx_chunks_doc_id ON workspace_chunks(doc_id);
CREATE INDEX IF NOT EXISTS idx_chunks_embedding ON workspace_chunks(embedding_id);
