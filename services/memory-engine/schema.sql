-- Sonia Memory Engine Schema
-- SQLite Database
-- Generated: 2026-02-08

-- Schema version tracking
CREATE TABLE IF NOT EXISTS schema_version (
    id INTEGER PRIMARY KEY,
    version INTEGER NOT NULL,
    applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- Insert initial version
INSERT OR IGNORE INTO schema_version (id, version) VALUES (1, 1);

-- Ledger table - core memory storage
CREATE TABLE IF NOT EXISTS ledger (
    id TEXT PRIMARY KEY,
    type TEXT NOT NULL,  -- fact, preference, project, belief
    content TEXT NOT NULL,
    embedding BLOB,  -- Vector embedding (optional)
    metadata TEXT,  -- JSON metadata
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    expires_at TEXT,  -- Optional expiration
    archived_at TEXT   -- When archived (null = active)
);

-- Indexes for efficient retrieval
CREATE INDEX IF NOT EXISTS idx_ledger_type ON ledger(type);
CREATE INDEX IF NOT EXISTS idx_ledger_created ON ledger(created_at);
CREATE INDEX IF NOT EXISTS idx_ledger_archived ON ledger(archived_at);
CREATE INDEX IF NOT EXISTS idx_ledger_active ON ledger(archived_at) WHERE archived_at IS NULL;

-- Search index table for full-text search
CREATE VIRTUAL TABLE IF NOT EXISTS ledger_search USING fts5(
    id,
    type,
    content,
    metadata
);

-- Snapshots for point-in-time recovery
CREATE TABLE IF NOT EXISTS snapshots (
    id TEXT PRIMARY KEY,
    timestamp TEXT NOT NULL,
    ledger_count INTEGER,
    metadata TEXT,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_snapshots_timestamp ON snapshots(timestamp);

-- Audit log
CREATE TABLE IF NOT EXISTS audit_log (
    id TEXT PRIMARY KEY,
    operation TEXT NOT NULL,  -- CREATE, UPDATE, DELETE, ARCHIVE
    ledger_id TEXT,
    details TEXT,
    performed_at TEXT NOT NULL,
    performed_by TEXT
);

CREATE INDEX IF NOT EXISTS idx_audit_ledger_id ON audit_log(ledger_id);
CREATE INDEX IF NOT EXISTS idx_audit_operation ON audit_log(operation);
CREATE INDEX IF NOT EXISTS idx_audit_timestamp ON audit_log(performed_at);
