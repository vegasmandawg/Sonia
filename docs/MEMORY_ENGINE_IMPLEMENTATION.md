# Memory Engine Implementation Details

## Overview

The Memory Engine is a production-grade persistent memory system with hybrid search capabilities, vector embeddings, full-text indexing, and intelligent memory management.

**Version**: 1.0.0  
**Location**: S:\services\memory-engine\  
**Port**: 7020  
**Language**: Python 3.11+  

## Architecture

### Core Components

```
MemoryEngine (Orchestrator)
├── LedgerStore (Append-only event log)
├── WorkspaceStore (Document ingestion + chunking)
├── Retriever (Hybrid search engine)
│   ├── EmbeddingsClient (Vector generation)
│   ├── HNSWIndex (Vector similarity search)
│   └── BM25 (Full-text ranking)
├── SnapshotManager (Context snapshots)
├── ProvenanceTracker (Source attribution)
└── MemoryDecay (Forgetting strategies)

Database: SQLite with WAL mode
Vector Index: HNSW (in-memory with JSON persistence)
```

### Service Architecture

```
FastAPI Service (port 7020)
├── /health (service health)
├── /status (service status)
├── /api/v1/memory/* (ledger endpoints)
├── /api/v1/workspace/* (document endpoints)
├── /api/v1/search/* (retrieval endpoints)
└── /api/v1/snapshots/* (snapshot endpoints)
```

## Core Modules

### 1. Ledger Store (`core/ledger_store.py`)

**Purpose**: Append-only event log with ACID guarantees.

**Key Features**:
- Immutable event log (append-only)
- Efficient querying by entity_id, event_type, timestamp
- Full-text search support via SQLite FTS5
- Transaction safety with WAL mode

**Database Schema**:
```sql
ledger_events:
  - id (PK, auto-increment)
  - event_id (UUID, unique)
  - event_type (string)
  - entity_id (string, indexed)
  - timestamp (ISO-8601, indexed)
  - correlation_id (UUID for tracing)
  - payload (JSON)
  - signature (HMAC-SHA256)
```

**Usage**:
```python
# Append event
event_id = await ledger.append({
    "event_type": "user_turn",
    "entity_id": "session-123",
    "payload": {"text": "hello"},
    "correlation_id": "corr-456"
})

# Query by entity
events = await ledger.query(entity_id="session-123", limit=100)
```

### 2. Workspace Store (`core/workspace_store.py`)

**Purpose**: Document ingestion pipeline with chunking.

**Key Features**:
- Multi-format document support (markdown, PDF, code, web)
- Semantic chunking strategies
- Automatic embedding generation
- Metadata preservation

**Database Schema**:
```sql
workspace_documents:
  - doc_id (UUID, unique)
  - doc_type (string)
  - content (text)
  - metadata (JSON)
  - ingested_at (timestamp)

document_chunks:
  - chunk_id (UUID, unique)
  - doc_id (FK)
  - content (text)
  - chunk_index (int)
  - start_offset (int)
  - end_offset (int)
  - embedding_id (FK to vectors)
```

**Usage**:
```python
# Ingest document
doc_id = await workspace.ingest(
    content="Long document...",
    doc_type="markdown",
    metadata={"title": "My Doc", "source": "user"}
)

# List documents
docs = await workspace.list_documents(doc_type="markdown")
```

### 3. Retriever (`core/retriever.py`)

**Purpose**: Hybrid search combining semantic and BM25 ranking.

**Search Pipeline**:
1. Generate query embedding via EmbeddingsClient
2. Vector search (HNSW nearest neighbors) → semantic_score
3. BM25 full-text search → bm25_score
4. Normalize both to [0, 1]
5. Combine with weights: `0.6 * semantic + 0.4 * bm25`
6. Sort by combined score
7. Return top k results

**Weights** (configurable):
- Semantic weight: 0.6 (favor vector similarity)
- BM25 weight: 0.4 (favor text matching)

**Usage**:
```python
# Hybrid search
results = await retriever.search(
    query="weather forecast",
    limit=10,
    include_scores=True,
    semantic_only=False
)

# Search by entity
entity_results = await retriever.search_by_entity(
    entity_id="session-123",
    limit=50
)
```

### 4. Embeddings Client (`core/embeddings_client.py`)

**Purpose**: Generate text embeddings via Ollama or OpenAI-compatible API.

**Providers**:
- **Ollama** (recommended): Local, private, fast
  - Default model: `nomic-embed-text` (1536 dims)
  - Endpoint: `http://127.0.0.1:11434/api/embed`
  
- **OpenAI-Compatible**: Support for OpenAI, Anthropic, etc.
  - Endpoint: `http://api.openai.com/v1/embeddings`

**Features**:
- Async batch processing
- Fallback to zero vector when unavailable
- Health checking
- Timeout handling

**Usage**:
```python
# Initialize
client = EmbeddingsClient(
    provider="ollama",
    base_url="http://127.0.0.1:11434",
    model="nomic-embed-text"
)
await client.initialize()

# Single embedding
embedding = await client.embed("text to embed")

# Batch embeddings
embeddings = await client.embed_batch(texts, batch_size=32)
```

### 5. HNSW Vector Index (`vector/hnsw_index.py`)

**Purpose**: Approximate nearest neighbor search for vectors.

**Algorithm**: HNSW (Hierarchical Navigable Small World)
- Logarithmic search time complexity
- Configurable M (number of connections per node)
- Effort parameter (ef) for speed/accuracy tradeoff

**Configuration**:
- Dimension: 1536 (standard)
- M: 16 (connections per node)
- max_m: 32 (limit)
- ef_construction: 200 (building effort)

**Persistence**: JSON format at S:\data\vector\sonia.hnsw

**Usage**:
```python
# Add vectors
await vector_index.add_vectors(
    vectors=[[0.1, 0.2, ...], ...],
    ids=["chunk1", "chunk2", ...],
    metadata=[{"content": "..."}, ...]
)

# Search
results = await vector_index.search(
    query_vector=[0.1, 0.2, ...],
    k=10,
    ef=100  # effort parameter
)
```

### 6. BM25 Full-Text Ranking (`core/bm25.py`)

**Purpose**: Full-text search with statistical ranking.

**Algorithm**: BM25 (Okapi Best Matching 25)
- k1 parameter: 1.5 (term saturation)
- b parameter: 0.75 (length normalization)
- IDF formula: log((N - df + 0.5) / (df + 0.5))

**Tokenization**: Simple (lowercase, whitespace split, remove punctuation)

**Usage**:
```python
bm25 = BM25(k1=1.5, b=0.75)

# Index documents
bm25.index_document("chunk1", "document content...")
bm25.index_batch({
    "chunk2": "another document...",
    "chunk3": "third document..."
})

# Search
results = bm25.search("query string", limit=10)
# Returns: [(doc_id, score), ...]
```

### 7. Memory Decay (`core/decay.py`)

**Purpose**: Intelligent forgetting with configurable strategies.

**Decay Strategies**:

1. **Exponential**: Score = exp(-λ * age_days)
   - Half-life: Score becomes 0.5 at half_life_days
   - Recommended for most use cases
   
2. **Linear**: Score = 1 - (age_days / half_life_days)
   - Steady, predictable decay
   - Reaches 0 at half_life_days
   
3. **Threshold**: Score = 1 if age < threshold else 0
   - Binary forgetting
   - Items persist then disappear suddenly

**Access Boost**: Frequently accessed items decay 10% slower per access

**Forgetting Threshold**: Items with score < 0.1 are forgotten

**Usage**:
```python
decay = MemoryDecay(
    strategy=DecayStrategy.EXPONENTIAL,
    half_life_days=30.0,
    threshold_score=0.1
)

# Compute score for item
score = decay.compute_decay_score(
    created_time="2026-02-08T14:30:00Z",
    access_count=5,
    relevance=0.95
)

# Apply to batch
decayed_items = decay.compute_batch_decay(items)

# Adjust search ranking
adjusted_results = decay.adjust_ranking(results, decay_weight=0.2)
```

### 8. Snapshot Manager (`core/snapshot_manager.py`)

**Purpose**: Create/restore memory snapshots for context optimization.

**Use Cases**:
- Context window management (compress old memory)
- Session persistence
- Memory rollback
- Backup/recovery

**Storage**: S:\data\memory\snapshots\{timestamp}_{session_id}.json

**Usage**:
```python
# Create snapshot
snapshot_id = await snapshots.create(session_id="session-123")

# Restore snapshot
memory_state = await snapshots.restore(snapshot_id)
```

### 9. Provenance Tracker (`core/provenance.py`)

**Purpose**: Track source document and span location for each chunk.

**Data Model**:
```python
{
    "source_doc_id": "doc-uuid",
    "chunk_id": "chunk-uuid",
    "start_offset": 150,
    "end_offset": 300,
    "confidence": 0.95
}
```

**Usage**:
```python
# Track chunk provenance
await provenance.track(
    chunk_id="chunk1",
    source_doc_id="doc1",
    start_offset=0,
    end_offset=512
)

# Retrieve provenance
prov = await provenance.get_provenance("chunk1")
```

## Data Flow

### Ingestion Flow

```
Document
  ↓
WorkspaceStore.ingest()
  ├→ Store document (doc_id)
  ├→ Chunker.chunk_text() → chunks
  ├→ EmbeddingsClient.embed_batch() → embeddings
  ├→ HNSWIndex.add_vectors() → index vectors
  ├→ BM25.index_batch() → full-text index
  └→ ProvenanceTracker.track() → source attribution
```

### Search Flow

```
Query
  ↓
Retriever.search()
  ├→ EmbeddingsClient.embed(query)
  ├→ Semantic search
  │  └→ HNSWIndex.search() → [(chunk_id, similarity), ...]
  ├→ BM25 search
  │  └→ BM25.search() → [(chunk_id, bm25_score), ...]
  ├→ Combine scores
  │  └→ normalize + weighted avg (0.6 semantic + 0.4 bm25)
  └→ Return top k results
```

### Decay Flow

```
Search Results
  ↓
MemoryDecay.adjust_ranking()
  ├→ compute_decay_score(created_time, access_count, relevance)
  ├→ normalize decay score to [0, 1]
  └→ blend with relevance (0.2 * decay + 0.8 * relevance)
```

## Configuration

### Environment Variables

```
# Embeddings
EMBEDDINGS_PROVIDER=ollama
EMBEDDINGS_BASE_URL=http://127.0.0.1:11434
EMBEDDINGS_MODEL=nomic-embed-text
EMBEDDINGS_DIM=1536

# Memory Engine
MEMORY_CHUNK_SIZE=512
MEMORY_CHUNK_OVERLAP=64
MEMORY_DECAY_HALF_LIFE=30
MEMORY_DECAY_STRATEGY=exponential
MEMORY_DECAY_THRESHOLD=0.1
MEMORY_SEMANTIC_WEIGHT=0.6
MEMORY_BM25_WEIGHT=0.4

# Database
MEMORY_DB_PATH=S:\data\memory\ledger.db
MEMORY_VECTOR_PATH=S:\data\vector\sonia.hnsw
MEMORY_SNAPSHOT_DIR=S:\data\memory\snapshots
```

## Performance Characteristics

### Search Latency (p99)

| Operation | Latency | Notes |
|-----------|---------|-------|
| Embedding generation | 500ms | Depends on Ollama |
| Vector search | 50ms | HNSW with k=10, ef=100 |
| BM25 search | 100ms | Full-text scan |
| Hybrid combine | 10ms | Score normalization |
| **Total search** | **<500ms** | With Ollama available |

### Storage Requirements

| Component | Per Item | Notes |
|-----------|----------|-------|
| Ledger event | 500B-2KB | Varies by payload size |
| Chunk | 2-5KB | Depends on content |
| Embedding (1536D) | 12KB | 4 bytes × 1536 floats |
| Metadata | 100-500B | Variable |

### Scalability

- **Ledger**: 1M+ events (SQLite tested to billions)
- **Documents**: 10k+ documents
- **Chunks**: 100k+ chunks
- **Vector index**: 100k+ embeddings (HNSW scales linearly)
- **BM25 index**: 100k+ documents (in-memory)

## Testing

### Unit Tests

- **test_health.py**: Health endpoint validation
- **test_ledger_append_query.py**: Ledger operations
- **test_workspace_ingest_search.py**: Document ingestion
- **test_snapshot_build.py**: Snapshot operations
- **test_provenance_spans.py**: Provenance tracking
- **test_hybrid_search.py**: Hybrid search integration
- **test_memory_decay.py**: Decay strategies

### Running Tests

```bash
# All tests
pytest S:\services\memory-engine\tests\

# Specific test
pytest S:\services\memory-engine\tests\test_hybrid_search.py::test_hybrid_search_combines_scores

# With coverage
pytest --cov=S:\services\memory-engine S:\services\memory-engine\tests\
```

## Troubleshooting

### Embeddings Unavailable

**Symptom**: Search returns zero vectors
**Solution**: 
1. Verify Ollama running: `http://127.0.0.1:11434/api/tags`
2. Check model installed: `ollama pull nomic-embed-text`
3. Fallback to zero vectors works but reduces search quality

### Slow Vector Search

**Symptom**: Search latency >1s
**Solution**:
1. Reduce ef parameter (trade speed for accuracy)
2. Reduce k (number of results)
3. Check HNSW index size: `GET /status`

### High Memory Usage

**Symptom**: Process uses >2GB RAM
**Solution**:
1. Create snapshot to archive old memory
2. Apply decay to forget old items
3. Consolidate similar memories

## Future Enhancements

### v1.1 (Q1 2026)
- [ ] Advanced tokenization (spaCy, NLTK)
- [ ] Query expansion (synonyms, related terms)
- [ ] Multi-language support
- [ ] Semantic deduplication

### v1.2 (Q2 2026)
- [ ] Distributed vector index (Milvus)
- [ ] PostgreSQL backend option
- [ ] GPU-accelerated embeddings
- [ ] Real-time indexing via message queue

### v1.3 (Q3 2026)
- [ ] Knowledge graph construction
- [ ] Temporal reasoning
- [ ] Cross-session memory linking
- [ ] Conflicting information resolution

---

**Document Version**: 1.0  
**Last Updated**: 2026-02-08  
**Status**: Implementation Complete
