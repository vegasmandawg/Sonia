-- Migration: Full-text search tables
CREATE VIRTUAL TABLE IF NOT EXISTS document_fts USING fts5(
  content,
  content='workspace_chunks'
);

-- Triggers to keep FTS index in sync
CREATE TRIGGER IF NOT EXISTS document_fts_ai AFTER INSERT ON workspace_chunks BEGIN
  INSERT INTO document_fts(rowid, content) VALUES (new.rowid, new.content);
END;

CREATE TRIGGER IF NOT EXISTS document_fts_ad AFTER DELETE ON workspace_chunks BEGIN
  INSERT INTO document_fts(document_fts, rowid, content) VALUES('delete', old.rowid, old.content);
END;
