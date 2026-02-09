-- Migration: Workspace documents and chunks
CREATE TABLE IF NOT EXISTS workspace_documents (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  doc_id TEXT UNIQUE NOT NULL,
  doc_type TEXT NOT NULL,
  content TEXT NOT NULL,
  metadata TEXT,
  ingested_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS document_chunks (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  chunk_id TEXT UNIQUE NOT NULL,
  doc_id TEXT NOT NULL,
  content TEXT NOT NULL,
  chunk_index INTEGER,
  start_offset INTEGER,
  end_offset INTEGER,
  embedding_id TEXT,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY(doc_id) REFERENCES workspace_documents(doc_id)
);

CREATE INDEX idx_workspace_doc_id ON workspace_documents(doc_id);
CREATE INDEX idx_workspace_type ON workspace_documents(doc_type);
CREATE INDEX idx_chunks_doc_id ON document_chunks(doc_id);
CREATE INDEX idx_chunks_embedding ON document_chunks(embedding_id);
