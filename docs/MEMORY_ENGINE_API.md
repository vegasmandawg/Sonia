# Memory Engine API Reference

## Overview

The Memory Engine service provides persistent, searchable memory with durable ledger, vector embeddings, and provenance tracking.

**Base URL**: `http://127.0.0.1:7020`

## Health Endpoints

### GET /health
Health check endpoint.

**Response** (200 OK):
```json
{
  "status": "healthy",
  "ledger": {"status": "healthy", "events_count": 1234},
  "workspace": {"status": "healthy", "documents_count": 45},
  "vector": {"status": "healthy", "vectors_count": 2345},
  "db": {"status": "healthy"},
  "timestamp": "2026-02-08T14:30:00Z"
}
```

### GET /status
Status endpoint with statistics.

**Response** (200 OK):
```json
{
  "service": "memory-engine",
  "version": "1.0.0",
  "health": {...},
  "stats": {
    "ledger_items": 1234,
    "documents": 45,
    "vector_embeddings": 2345,
    "snapshots": 12,
    "memory_usage_mb": 256.4,
    "vector_index_size_mb": 128.2,
    "timestamp": "2026-02-08T14:30:00Z"
  }
}
```

## Ledger Endpoints

### POST /api/v1/memory/append
Append event to ledger.

**Request**:
```json
{
  "event_type": "user_turn|tool_call|tool_result",
  "entity_id": "session-123",
  "payload": {
    "correlation_id": "...",
    "content": "...",
    "metadata": {...}
  }
}
```

**Response** (200 OK):
```json
{
  "event_id": "550e8400-e29b-41d4-a716-446655440000",
  "success": true,
  "timestamp": "2026-02-08T14:30:00Z"
}
```

### GET /api/v1/memory/query
Query ledger with optional filters.

**Query Parameters**:
- `entity_id` (optional): Filter by entity ID
- `event_type` (optional): Filter by event type
- `start_time` (optional): ISO-8601 start time
- `end_time` (optional): ISO-8601 end time
- `limit` (default: 100, max: 1000): Results limit

**Response** (200 OK):
```json
{
  "results": [
    {
      "event_id": "...",
      "event_type": "user_turn",
      "entity_id": "session-123",
      "timestamp": "2026-02-08T14:30:00Z",
      "correlation_id": "...",
      "payload": {...}
    }
  ],
  "count": 5
}
```

## Workspace Endpoints

### POST /api/v1/workspace/ingest
Ingest and chunk document.

**Request**:
```json
{
  "content": "Document content...",
  "doc_type": "markdown|pdf|code|web",
  "metadata": {
    "title": "...",
    "source": "...",
    "tags": ["..."]
  }
}
```

**Response** (200 OK):
```json
{
  "doc_id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "ingested"
}
```

### GET /api/v1/workspace/documents
List all documents.

**Query Parameters**:
- `doc_type` (optional): Filter by document type

**Response** (200 OK):
```json
{
  "documents": [
    {
      "doc_id": "...",
      "doc_type": "markdown",
      "content_preview": "First 200 chars...",
      "metadata": {...},
      "ingested_at": "2026-02-08T14:30:00Z"
    }
  ],
  "count": 5
}
```

## Search Endpoints

### POST /api/v1/search
Hybrid search (semantic + BM25).

**Request**:
```json
{
  "query": "What is the weather?",
  "limit": 10,
  "include_scores": true
}
```

**Response** (200 OK):
```json
{
  "query": "What is the weather?",
  "results": [
    {
      "chunk_id": "...",
      "content": "...",
      "score": 0.92,
      "relevance": 0.88,
      "provenance": {
        "source_doc_id": "...",
        "start_offset": 150,
        "end_offset": 300,
        "confidence": 0.95
      }
    }
  ],
  "count": 5
}
```

### GET /api/v1/search/entity/{entity_id}
Search memory for specific entity.

**Query Parameters**:
- `limit` (default: 50, max: 1000): Results limit

**Response** (200 OK):
```json
{
  "entity_id": "session-123",
  "results": [
    {
      "event_id": "...",
      "event_type": "user_turn",
      "timestamp": "2026-02-08T14:30:00Z",
      "payload": {...},
      "relevance": 1.0
    }
  ],
  "count": 15
}
```

## Snapshot Endpoints

### POST /api/v1/snapshots/create
Create memory snapshot.

**Request**:
```json
{
  "session_id": "session-123"
}
```

**Response** (200 OK):
```json
{
  "snapshot_id": "550e8400-e29b-41d4-a716-446655440000",
  "session_id": "session-123",
  "success": true,
  "timestamp": "2026-02-08T14:30:00Z"
}
```

### POST /api/v1/snapshots/restore/{snapshot_id}
Restore from snapshot.

**Response** (200 OK):
```json
{
  "snapshot_id": "550e8400-e29b-41d4-a716-446655440000",
  "restored": {
    "ledger_events": [...],
    "documents": [...],
    "vector_count": 2345
  }
}
```

## Error Responses

All endpoints return consistent error format:

**400 Bad Request**:
```json
{
  "detail": "Invalid query parameters",
  "status": 400
}
```

**500 Internal Server Error**:
```json
{
  "detail": "Database connection failed",
  "status": 500
}
```

## Rate Limits

- Search: 1000 requests/minute per IP
- Append: 10000 requests/minute per session
- Query: 500 requests/minute per IP

## SLA

- Search latency: <500ms (p99)
- Append latency: <100ms (p99)
- Query latency: <1s (p99)

---

**API Version**: 1.0
**Last Updated**: 2026-02-08
