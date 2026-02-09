-- Migration: Full-text search tables
CREATE VIRTUAL TABLE IF NOT EXISTS document_fts USING fts5(
  content,
  content='document_chunks',
  content_rowid='id'
);

-- Triggers to keep FTS index in sync
CREATE TRIGGER IF NOT EXISTS document_fts_ai AFTER INSERT ON document_chunks BEGIN
  INSERT INTO document_fts(rowid, content) VALUES (new.id, new.content);
END;

CREATE TRIGGER IF NOT EXISTS document_fts_ad AFTER DELETE ON document_chunks BEGIN
  INSERT INTO document_fts(document_fts, rowid, content) VALUES('delete', old.id, old.content);
END;
