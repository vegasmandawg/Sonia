-- Migration 009: Ledger V3 — Typed memory model, bi-temporal semantics,
-- version chains, redaction governance, conflict detection.
--
-- All new columns are nullable with defaults.  memory_subtype = NULL means
-- the row is a legacy (pre-v3) memory.  No destructive changes.

-- ─── New columns on ledger ──────────────────────────────────────────────

ALTER TABLE ledger ADD COLUMN memory_subtype TEXT;
-- FACT | PREFERENCE | PROJECT | SESSION_CONTEXT | SYSTEM_STATE | NULL(legacy)

ALTER TABLE ledger ADD COLUMN valid_from TEXT;
-- Business time: when fact became true (ISO 8601 UTC)

ALTER TABLE ledger ADD COLUMN valid_until TEXT;
-- Business time: when fact ceased (NULL = still valid)

ALTER TABLE ledger ADD COLUMN recorded_at TEXT;
-- System/assertion capture time (distinct from row created_at)

ALTER TABLE ledger ADD COLUMN superseded_by TEXT REFERENCES ledger(id);
-- Points to the next version (NULL = current)

ALTER TABLE ledger ADD COLUMN version_chain_head TEXT REFERENCES ledger(id);
-- Head of version chain (self-ref for head, NULL = legacy only)

ALTER TABLE ledger ADD COLUMN redacted INTEGER DEFAULT 0;
-- Redaction governance flag (0 = visible, 1 = redacted)

ALTER TABLE ledger ADD COLUMN validation_schema TEXT;
-- Schema version (e.g. "FACT:v1"); non-null = content must be JSON

ALTER TABLE ledger ADD COLUMN content_format TEXT DEFAULT 'text';
-- Discriminator: 'text' (legacy) vs 'json' (v3 typed)

-- ─── Indexes ────────────────────────────────────────────────────────────

-- Subtype filter
CREATE INDEX IF NOT EXISTS idx_ledger_subtype
    ON ledger(memory_subtype);

-- "Current memory" fast path: non-superseded, non-redacted, by subtype
CREATE INDEX IF NOT EXISTS idx_ledger_current
    ON ledger(memory_subtype, superseded_by)
    WHERE superseded_by IS NULL AND redacted = 0;

-- Temporal range queries
CREATE INDEX IF NOT EXISTS idx_ledger_valid_range
    ON ledger(valid_from, valid_until);

-- Version chain traversal
CREATE INDEX IF NOT EXISTS idx_ledger_version_chain
    ON ledger(version_chain_head, superseded_by);

-- Redacted row lookup
CREATE INDEX IF NOT EXISTS idx_ledger_redacted
    ON ledger(redacted) WHERE redacted = 1;

-- ─── Memory conflicts table ────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS memory_conflicts (
    conflict_id   TEXT PRIMARY KEY,
    memory_id_a   TEXT NOT NULL REFERENCES ledger(id),
    memory_id_b   TEXT NOT NULL REFERENCES ledger(id),
    conflict_type TEXT NOT NULL,
    severity      TEXT NOT NULL DEFAULT 'medium',
    detected_at   TEXT NOT NULL,
    resolved      INTEGER DEFAULT 0,
    resolution_note TEXT,
    metadata      TEXT
);

CREATE INDEX IF NOT EXISTS idx_conflicts_memory_a
    ON memory_conflicts(memory_id_a);

CREATE INDEX IF NOT EXISTS idx_conflicts_memory_b
    ON memory_conflicts(memory_id_b);

CREATE INDEX IF NOT EXISTS idx_conflicts_resolved
    ON memory_conflicts(resolved) WHERE resolved = 0;

-- ─── Redaction audit table ──────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS redaction_audit (
    redaction_id  TEXT PRIMARY KEY,
    memory_id     TEXT NOT NULL REFERENCES ledger(id),
    action        TEXT NOT NULL,           -- 'REDACT' | 'UNREDACT'
    reason        TEXT,
    performed_at  TEXT NOT NULL,
    performed_by  TEXT NOT NULL DEFAULT 'system',
    metadata      TEXT
);

CREATE INDEX IF NOT EXISTS idx_redaction_audit_memory
    ON redaction_audit(memory_id);

CREATE INDEX IF NOT EXISTS idx_redaction_audit_action
    ON redaction_audit(action);
