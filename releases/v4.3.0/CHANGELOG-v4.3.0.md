# SONIA v4.3.0-rc1 Changelog

## Release: v4.3.0-rc1
**Commit:** bb511d4  
**Tag:** v4.3.0-rc1  
**Schema:** 10.0  
**Date:** 2026-02-17

## Epic A: Session Durability + Restart Recovery
- NEW: DurableStateStore (SQLite WAL) for crash-safe persistence
- Sessions, confirmations, dead letters write-through to SQLite
- Outbox pattern for at-least-once memory write-back delivery
- Full restore on startup: sessions, confirmations, DLQ, outbox
- Lifespan wiring in api-gateway main.py

## Epic B: Persistent Retrieval + Deterministic Recall
- HNSW vector index wired into hybrid search (0.4*BM25 + 0.6*vector)
- Backfill on startup: existing BM25 docs embedded and indexed
- Index manifest with SHA-256 checksums for integrity verification
- Deterministic token budget in retriever (greedy fill, at-least-one)
- Vector save on shutdown with manifest update

## Epic C: Consent/Privacy Hardening
- 5-state consent FSM: OFF -> REQUESTED -> GRANTED -> ACTIVE -> REVOKED
- Fail-closed enforcement: inference blocked unless state is ACTIVE
- Perception consent gate before any inference call
- BackpressurePolicy: per-session queue depth with oldest-first shedding
- LatencyBudget: per-stage p95/p99 tracking with SLO compliance check
- Stream.py wired with backpressure + latency recording

## Promotion Gate
- 18/18 structural gates PASS (schema v10.0)
- Reproducible: identical results across two independent runs
