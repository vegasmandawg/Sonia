-- Migration: Snapshot metadata
CREATE TABLE IF NOT EXISTS snapshots (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  snapshot_id TEXT UNIQUE NOT NULL,
  session_id TEXT NOT NULL,
  created_at TEXT NOT NULL,
  file_path TEXT NOT NULL,
  ledger_event_count INTEGER,
  document_count INTEGER,
  vector_count INTEGER
);

CREATE INDEX idx_snapshots_session ON snapshots(session_id);
CREATE INDEX idx_snapshots_created ON snapshots(created_at);
