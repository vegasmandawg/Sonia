-- Migration: Snapshot metadata (canonical runtime shape)
CREATE TABLE IF NOT EXISTS snapshots (
  id TEXT PRIMARY KEY,
  timestamp TEXT NOT NULL,
  ledger_count INTEGER,
  metadata TEXT,
  created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_snapshots_created ON snapshots(created_at);
CREATE INDEX IF NOT EXISTS idx_snapshots_timestamp ON snapshots(timestamp);
