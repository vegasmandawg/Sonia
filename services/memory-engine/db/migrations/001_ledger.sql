-- Migration: Initialize ledger events table
CREATE TABLE IF NOT EXISTS ledger_events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  event_id TEXT UNIQUE NOT NULL,
  event_type TEXT NOT NULL,
  entity_id TEXT NOT NULL,
  timestamp TEXT NOT NULL,
  correlation_id TEXT,
  payload TEXT NOT NULL,
  signature TEXT,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_ledger_entity_id ON ledger_events(entity_id);
CREATE INDEX IF NOT EXISTS idx_ledger_event_type ON ledger_events(event_type);
CREATE INDEX IF NOT EXISTS idx_ledger_timestamp ON ledger_events(timestamp);
CREATE INDEX IF NOT EXISTS idx_ledger_correlation ON ledger_events(correlation_id);
