# SONIA v3.0.0 — Milestone 3: Memory Ledger V3

## Overview

M3 introduces a typed memory model with bi-temporal semantics, immutable
version chains, redaction governance, identity-key conflict detection, and
DB-level retrieval budget enforcement. All changes are backward-compatible
with the existing flat ledger.

## Schema Changes (Migration 009)

New **nullable** columns on `ledger` (NULL = legacy row):

| Column | Type | Purpose |
|--------|------|---------|
| `memory_subtype` | TEXT | FACT, PREFERENCE, PROJECT, SESSION_CONTEXT, SYSTEM_STATE |
| `valid_from` | TEXT | Business time: when fact became true (ISO 8601 UTC) |
| `valid_until` | TEXT | Business time: when fact ceased (NULL = still valid) |
| `recorded_at` | TEXT | System/assertion capture time |
| `superseded_by` | TEXT FK | Points to next version (NULL = current) |
| `version_chain_head` | TEXT FK | Head of version chain (self-ref for head) |
| `redacted` | INTEGER | 0 = visible, 1 = redacted |
| `validation_schema` | TEXT | Schema version (e.g. "FACT:v1") |
| `content_format` | TEXT | 'text' (legacy) or 'json' (v3 typed) |

New tables: `memory_conflicts`, `redaction_audit`.

Partial indexes for fast "current memory" queries.

## Architecture

### Typed Memory (`core/typed_memory.py`)

- **MemorySubtype** enum with Pydantic schemas per subtype
- **TypedMemoryValidator**: validates content JSON + temporal invariants
- **ConflictDetector**: identity-key conflict detection
  - FACT identity = `(subject, predicate)` — same object = no conflict
  - PREFERENCE identity = `(category, key)` — same value = no conflict
- **VersionChainManager**: immutable chains with optimistic concurrency
  - `UPDATE ... WHERE superseded_by IS NULL` — 409 on concurrent supersede
- **RedactionManager**: governance-audited REDACT/UNREDACT with audit trail

### DB Layer (`db.py`)

New methods: `store_typed()`, `query_with_budget()`, `get_conflicts()`,
`resolve_conflict()`, `get_version_history()`, `create_version()`,
`redact_memory()`, `unredact_memory()`, `get_redaction_audit()`.

Legacy `update()` on typed rows silently redirects to `create_version()`.

### V3 Endpoints (`main.py`)

All under `/v3/memory/`:

| Method | Path | Purpose |
|--------|------|---------|
| POST | `/v3/memory/store` | Typed store with validation + conflicts |
| POST | `/v3/memory/query` | Search with DB-level char budget |
| GET | `/v3/memory/{id}/versions` | Version history |
| POST | `/v3/memory/version` | Create new version (409 on concurrent) |
| POST | `/v3/memory/redact` | Redact memory |
| GET | `/v3/memory/{id}/redaction-audit` | Audit trail |
| GET | `/v3/memory/conflicts` | List conflicts |
| POST | `/v3/memory/conflicts/{id}/resolve` | Resolve conflict |

### Gateway Client (`memory_client.py`)

New methods: `store_typed()`, `query_with_budget()`, `get_version_history()`,
`create_version()`, `redact_memory()`, `list_conflicts()`.

### Memory Policy (`memory_policy.py`)

New: `MemoryRetrievalPolicyV3` class, `write_typed_memory()` helper.

## Key Invariants

1. ISO 8601 UTC strict: all temporal fields validated on write
2. `valid_until > valid_from` enforced in code
3. `version_chain_head = self.id` for head records (not NULL)
4. Content immutability: typed rows never overwritten, only versioned
5. Optimistic concurrency prevents split-brain on supersede
6. Redaction preserves chain pointers; content masked as `[REDACTED]`
7. Budget query returns at least 1 result (first-row bypass)

## Test Coverage

38 integration tests in `test_v300_m3_memory.py`:

| Group | Count |
|-------|-------|
| Typed storage + validation | 8 |
| Version chains | 6 |
| Redaction governance | 4 |
| Conflict detection | 5 |
| Budget enforcement | 4 |
| Backward compatibility | 3 |
| Adversarial / hardening | 6 |
| M3 invariant assertions | 2 |

Regression: M2 (28 tests) + M1 (18 tests) all green.

## Files Changed

| File | Action |
|------|--------|
| `services/memory-engine/db/migrations/009_ledger_v3.sql` | Create |
| `services/memory-engine/core/typed_memory.py` | Create |
| `services/memory-engine/db.py` | Modify |
| `services/memory-engine/main.py` | Modify |
| `services/api-gateway/clients/memory_client.py` | Modify |
| `services/api-gateway/memory_policy.py` | Modify |
| `tests/integration/test_v300_m3_memory.py` | Create |
| `docs/V3_M3_MEMORY_LEDGER.md` | Create |
