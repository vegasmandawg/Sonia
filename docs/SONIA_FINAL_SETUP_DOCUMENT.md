# SONIA v2.9.0 -- Final Setup & Completion Document

**Date:** 2026-02-13
**Branch:** `fix/sonia-system-audit-20260209`
**Commit:** `17d9f7bd` (v2.9.0 GA)
**Auditor:** Claude Opus 4.6 -- full codebase analysis (7 parallel agents, all services)

---

## EXECUTIVE SUMMARY

SONIA's backend architecture is **substantially complete** across 6 core services, 2 auxiliary services, and an Electron UI. The turn pipeline, session management, action pipeline, safety gates, observability, and reliability hardening are all implemented. However, **making SONIA actually functional end-to-end** requires addressing the items below, organized by priority.

**Overall readiness: ~75% to functional system**

The remaining 25% is almost entirely:
- Runtime configuration (API keys, .env, Ollama models)
- Memory engine quality issues (token budget, dual DB, dead code)
- Voice pipeline integration (ASR/TTS backends need real providers)
- UI build & wiring verification

---

## SECTION 1: BLOCKERS (Must Fix Before Any Operation)

### 1.1 No .env File Exists -- No API Keys Configured

**Impact:** Model router cannot reach cloud providers. System limited to Ollama-only.

**Files involved:**
- `S:\config\env\.env.template` -- template with `__REPLACE_ME__` placeholders
- `S:\.env.example` -- comprehensive 195-line reference
- `S:\services\model-router\providers.py:490-495` -- conditional provider init

**Required action:**
```
1. Copy S:\config\env\.env.template -> S:\.env
2. Set ANTHROPIC_API_KEY=sk-ant-...
3. Set OPENROUTER_API_KEY=sk-or-...
4. Set HUGGINGFACE_API_KEY=hf_... (optional)
5. Set GITHUB_TOKEN=ghp_... (optional)
```

**Note:** No `python-dotenv` in `requirements-frozen.txt`. Environment variables must be set in the shell or the stack launcher must be updated to source the .env file.

### 1.2 Ollama Not Verified Running / Models Not Installed

**Impact:** Default model routing targets Ollama. All text/vision generation fails without it.

**Files involved:**
- `S:\config\sonia-config.json:135` -- default model: `ollama/sonia-vlm:32b`
- `S:\services\model-router\providers.py:86` -- fallback default: `qwen2:7b`
- `S:\start-sonia-stack.ps1:173-186` -- pre-flight Ollama probe

**Required action:**
```
1. Install Ollama (https://ollama.ai)
2. Start: ollama serve
3. Pull models:
   ollama pull qwen2.5:7b
   ollama pull qwen3-vl:32b-instruct
   (or whatever models you actually intend to use)
4. Verify: curl http://127.0.0.1:11434/api/tags
```

**Config mismatch:** `sonia-config.json` says default is `ollama/sonia-vlm:32b` but `providers.py` defaults to `qwen2:7b`. These must be aligned.

### 1.3 Python Environment Not Verified

**Impact:** All 6 services fail to start.

**Files involved:**
- `S:\start-sonia-stack.ps1:163-170` -- checks `S:\envs\sonia-core\python.exe`
- `S:\scripts\lib\sonia-stack.ps1:124-125` -- uses Python for uvicorn

**Required action:**
```
1. Verify: S:\envs\sonia-core\python.exe --version  (need 3.9+)
2. Install deps: S:\envs\sonia-core\python.exe -m pip install -r S:\requirements-frozen.txt
3. Install dev deps: S:\envs\sonia-core\python.exe -m pip install -r S:\requirements-dev.txt
```

### 1.4 Runtime Directories Missing

**Impact:** Services crash on write operations (logs, PID files, database).

**Directories needed (some auto-created by scripts, others not):**

| Path | Auto-created? | Used by |
|------|:---:|---------|
| `S:\data\` | Yes (db.py) | memory-engine database |
| `S:\data\memory\` | Yes (db.py) | ledger storage |
| `S:\data\knowledge\` | No | knowledge workspace |
| `S:\logs\services\` | Yes (start script) | all service logs |
| `S:\logs\services\model-router\` | No | model router audit log |
| `S:\logs\services\pipecat\` | No | pipecat telemetry |
| `S:\logs\tools\` | No | OpenClaw tool call audit |
| `S:\logs\gateway\` | No | api-gateway JSONL logs |
| `S:\state\pids\` | Yes (start script) | service PID tracking |
| `S:\audit\` | No | OpenClaw audit trail |
| `S:\backups\state\` | No | state backup system |
| `S:\cache\hf\` | No | HuggingFace model cache |

**Required action:**
```powershell
$dirs = @(
    "S:\data\knowledge",
    "S:\logs\services\model-router",
    "S:\logs\services\pipecat",
    "S:\logs\tools",
    "S:\logs\gateway",
    "S:\audit",
    "S:\backups\state",
    "S:\cache\hf"
)
$dirs | ForEach-Object { New-Item -ItemType Directory -Path $_ -Force }
```

### 1.5 UI Not Built

**Impact:** Electron app has no `dist/` folder, so production mode fails.

**Files involved:**
- `S:\ui\sonia-avatar\package.json` -- build scripts
- `S:\ui\sonia-avatar\electron\main.js` -- loads `dist/index.html` in production

**Required action:**
```powershell
cd S:\ui\sonia-avatar
npm install
npm run build
```

---

## SECTION 2: CRITICAL CODE ISSUES (Must Fix for Correct Behavior)

### 2.1 Memory Engine: Dual Database Implementation

**Severity:** CRITICAL
**Impact:** Two separate, uncoordinated database implementations exist.

**Files involved:**
- `S:\services\memory-engine\db.py` -- **synchronous** MemoryDatabase using sqlite3
- `S:\services\memory-engine\db\sqlite.py` -- **asynchronous** SqliteDB using aiosqlite
- `S:\services\memory-engine\main.py:36` -- uses sync `db.py`
- `S:\services\memory-engine\memory_engine_service.py` -- uses async `db\sqlite.py`

**Problem:** main.py uses the sync implementation. memory_engine_service.py uses async. Routes in main.py are the active ones. The async path is dead code.

**Fix:** Remove the unused `memory_engine_service.py` and `db/sqlite.py`, or migrate main.py to use the async implementation. Consolidate to ONE database layer.

### 2.2 Memory Engine: Token Budget Enforcement is Broken

**Severity:** CRITICAL
**Impact:** Token budget uses characters, not tokens. Only applied on ONE endpoint.

**Files involved:**
- `S:\services\memory-engine\main.py:232-243` -- budget calculation
  - Line 234: `budget = request.max_tokens * 4` (hardcoded 4 chars/token approximation)
  - Line 238: Uses `len(content)` (character count, not token count)
- `/v1/search` endpoint -- **NO** token budget enforcement
- `/v1/query/by-type/{memory_type}` endpoint -- **NO** token budget enforcement
- `hybrid_search.py` -- **NO** token budget enforcement

**Fix:** Implement proper tokenizer-based budget enforcement, or at minimum apply the approximation consistently across ALL retrieval endpoints.

### 2.3 Memory Engine: Workspace Document Ingestion is a Stub

**Severity:** HIGH
**Impact:** Documents stored but NOT chunked, NOT embedded, NOT indexed for vector search.

**Files involved:**
- `S:\services\memory-engine\core\workspace_store.py:46-49` -- TODO comment, no chunking
- `S:\services\memory-engine\core\chunker.py:38` -- TODO: sentence-aware chunking incomplete

**Fix:** Implement actual document chunking + embedding pipeline in workspace_store. Wire to the HNSW vector index.

### 2.4 Memory Engine: Snapshot Manager is Non-Functional

**Severity:** HIGH
**Impact:** Snapshots return empty data. Memory state cannot be captured.

**Files involved:**
- `S:\services\memory-engine\core\snapshot_manager.py:33-41` -- hardcoded empty arrays with "Would fetch from..." comments

**Fix:** Implement actual data fetching from ledger, workspace, and vector index.

### 2.5 Memory Engine: Fallback Embedding Returns Zero Vectors

**Severity:** HIGH
**Impact:** When Ollama is down, all embeddings become `[0.0, 0.0, ...]`, making all search results equally scored (useless).

**Files involved:**
- `S:\services\memory-engine\embeddings_client.py:200-209` -- returns `[0.0] * dim`

**Fix:** At minimum, log a clear warning and return an error rather than silently returning zero vectors. Or implement a secondary embedding provider.

### 2.6 Model Router: httpx Not in requirements.lock

**Severity:** HIGH
**Impact:** Model router imports `httpx` but it's not in the service-level lock file.

**Files involved:**
- `S:\services\model-router\providers.py:8` -- `import httpx`
- `S:\services\model-router\requirements.lock` -- httpx missing

**Note:** httpx IS in the global `S:\requirements-frozen.txt:25` (httpx==0.28.1), so this will work at runtime if global deps are installed. But the service-level lock is incomplete.

### 2.7 Model Router: OpenRouter Provider is Hardcoded/Incomplete

**Severity:** MEDIUM
**Impact:** OpenRouter returns hardcoded model list, routes only TEXT tasks to GPT-4.

**Files involved:**
- `S:\services\model-router\providers.py:374-384` -- hardcoded models list (GPT-4, GPT-3.5, Claude-3-opus)
- `S:\services\model-router\providers.py:386-392` -- route() always returns GPT-4 for TEXT, None for everything else

**Fix:** Implement proper model listing via OpenRouter API. Support VISION routing.

### 2.8 Memory Engine: Health Endpoint Inconsistency

**Severity:** MEDIUM
**Impact:** Multiple health endpoint definitions, not all using canonical `/healthz`.

**Files involved:**
- `S:\services\memory-engine\main.py:77-88` -- implements `/healthz` (correct)
- `S:\services\memory-engine\api\routes_health.py:8-11` -- implements `/health` (wrong, NOT integrated)
- `S:\services\memory-engine\memory_engine_service.py:60-63` -- implements `/health` (wrong, NOT integrated)

**Fix:** Remove the unused `routes_health.py` and `memory_engine_service.py` health endpoints. Only `main.py:/healthz` should exist.

---

## SECTION 3: FUNCTIONALITY GAPS (Features That Don't Work Yet)

### 3.1 Voice Pipeline: No Real ASR/TTS Backend

**Impact:** Pipecat service has full session management and turn routing, but audio processing requires actual ASR/TTS providers.

**Current state:**
- `S:\services\pipecat\app\asr_client.py` -- wraps `pipeline.tts.TTS` (abstract)
- `S:\services\pipecat\app\tts_client.py` -- cancel-aware TTS wrapper (abstract)
- Text fallback works (WebSocket text messages route through turn pipeline)
- Audio frames are NOT processed

**What's needed:**
- Configure actual ASR provider (Whisper local, Deepgram, AssemblyAI)
- Configure actual TTS provider (Piper local, ElevenLabs, Azure)
- Wire audio frame processing in the WebSocket handler

### 3.2 OpenClaw: Tool Catalog vs Registry Mismatch

**Impact:** 18 tools defined in `tool_catalog.json` are NOT registered in the runtime registry.

**Registered (16 tools):** file.read, file.write, shell.run, browser.open, app.launch, app.close, window.focus, window.list, keyboard.type, keyboard.hotkey, mouse.click, clipboard.read, clipboard.write, web.search, web.fetch, notification.send

**In catalog but NOT implemented:**
filesystem.list_directory, filesystem.stat, filesystem.create_directory, filesystem.append_file, filesystem.move, filesystem.copy, filesystem.delete, process.list, process.start, process.stop, process.kill, shell.run_powershell_script, shell.run_command

**Impact:** Calling these returns `status: "not_implemented"`. This is by design (catalog is aspirational) but limits functionality.

### 3.3 EVA-OS: Task Endpoints Are Stubs

**Impact:** Task creation/listing returns hardcoded empty data.

**Files involved:**
- `S:\services\eva-os\main.py:134-158`
  - `GET /tasks` returns `{"tasks": [], "count": 0}`
  - `POST /tasks` returns `task_id: "task_001"` (hardcoded)

**Note:** Low priority. Not used by the core pipeline.

### 3.4 Vision Capture & Perception Services Not in Boot Sequence

**Impact:** Vision services (ports 7060, 7070) are defined in config but conditionally started.

**Files involved:**
- `S:\start-sonia-stack.ps1:106-122` -- conditional check for these services
- `S:\config\sonia-config.json:63-79` -- service definitions exist

**Note:** These are Track B (v2.6) features. They work but aren't part of the default 5-service boot.

### 3.5 Knowledge Ingestion: PDF Support Missing

**Impact:** `ingest-knowledge.py` handles .txt/.md but PDF fails without PyMuPDF.

**Files involved:**
- `S:\scripts\ingest-knowledge.py:56-78` -- PDF reader import
- `S:\requirements-frozen.txt` -- no PyMuPDF or pdfplumber

**Fix:** `pip install PyMuPDF` or `pip install pdfplumber`

---

## SECTION 4: CODE QUALITY ISSUES (Should Fix for Stability)

### 4.1 Memory Engine: Provenance Cache Grows Unbounded
- `S:\services\memory-engine\core\provenance.py:26` -- `self._index` dict never pruned
- Memory leak over long-running sessions

### 4.2 Memory Engine: BM25 Tokenization Too Naive
- `S:\services\memory-engine\core\bm25.py:149-166` -- whitespace split only
- No stemming, no stopwords, no language awareness
- Search quality degrades for natural language queries

### 4.3 Memory Engine: HNSW Vector Index Limitations
- `S:\services\memory-engine\vector\hnsw_index.py`
  - Not true HNSW algorithm (simplified greedy search)
  - Persistence dumps entire index to JSON (no compression, no incremental)
  - Entry point never updated after initialization
  - Silent vector dimension padding/truncation

### 4.4 Memory Engine: N+1 Query Pattern
- `S:\services\memory-engine\hybrid_search.py:110-128` -- loops `db.get(doc_id)` per BM25 result
- Should batch query

### 4.5 Memory Engine: Silent Error Swallowing
- `main.py:422-426` -- hybrid search init failure logged but service reports healthy
- `main.py:140-145` -- provenance tracking failure silently skipped
- `hybrid_search.py:135-137` -- index failure silently ignored

### 4.6 Memory Engine: Audit Log Transaction Safety
- `db.py:88-95, 177-184, 206-213` -- audit entries in same transaction as data writes
- If transaction rolls back, audit trail is lost

### 4.7 Memory Engine: Unused/Dead Code
- `core/chunker.py` -- defined but never imported
- `core/decay.py` -- defined but never imported
- `core/filters.py` -- defined but never imported
- `models/responses.py` -- defined but never imported in main.py
- `memory_engine_service.py` -- entire file is dead code
- `api/routes_health.py` -- not integrated

### 4.8 Model Router: Anthropic API Version Hardcoded
- `S:\services\model-router\providers.py:304` -- `"anthropic-version": "2023-06-01"`
- Old version, may cause compatibility issues

### 4.9 All Services: Hardcoded Windows Paths
- All services use `S:\...` absolute paths
- Not portable to other environments or Linux deployment
- Should use environment variables or config-driven paths

---

## SECTION 5: CONFIGURATION ALIGNMENT ISSUES

### 5.1 Default Model Mismatch (3 Different Defaults)
| Source | Default Model |
|--------|--------------|
| `sonia-config.json:135` | `ollama/sonia-vlm:32b` |
| `providers.py:86` | `qwen2:7b` (env: OLLAMA_MODEL) |
| `providers.py` profile | `ollama/qwen2:7b` |

**Fix:** Align all to ONE default. Set `OLLAMA_MODEL` env var explicitly.

### 5.2 OpenRouter HTTP-Referer Hardcoded
- `providers.py:418` -- `"HTTP-Referer": "https://sonia.local"` (fake domain)
- OpenRouter may reject or miscategorize requests

### 5.3 Health Endpoint Reports OK When Subsystems Failed
- `S:\services\model-router\main.py:91-100` -- returns `ok: true` even if profile infrastructure failed
- Should return degraded status

---

## SECTION 6: UI STATUS

### Current State
The Electron + React + Three.js UI is **structurally complete**:

- **Connection manager** (`src/state/connection.ts`) -- WebSocket to `ws://127.0.0.1:7000/v1/ui/stream`
- **State management** (`src/state/store.ts`) -- Zustand store with 5-state FSM
- **Components:**
  - `App.tsx` -- main layout, WebSocket lifecycle
  - `ControlBar.tsx` -- push-to-talk, status indicators
  - `ChatPanel.tsx` -- message display
  - `ErrorBoundary.tsx` -- crash recovery
- **Protocol:** handles `turn.assistant`, `turn.user`, `diagnostics`, `state.*` events
- **Electron IPC:** `get-backend-ws`, `window-minimize/maximize/close`

### UI Issues
1. **Uncommitted change:** `electron/main.js` changed `BACKEND_WS` from `/v1/stream` to `/v1/ui/stream` (correct fix, needs commit)
2. **No `npm install` run** -- `node_modules/` likely missing
3. **No `dist/` built** -- production mode won't work
4. **Three.js avatar** -- renders but no animation/lip-sync pipeline connected
5. **Voice UI** -- push-to-talk button wired but no actual audio capture/playback

---

## SECTION 7: TEST STATUS

### Test Inventory

| Test File | Count | Location | Status |
|-----------|:-----:|----------|--------|
| test_turn_pipeline.py | 8 | tests/integration/ | Needs live services |
| test_session_lifecycle.py | 5 | tests/integration/ | Needs live services |
| test_stream_text_fallback.py | 4 | tests/integration/ | Needs live services |
| test_tool_confirmation_gate.py | 9 | tests/integration/ | Needs live services |
| test_stage2_compat.py | 7 | tests/integration/ | Needs live services |
| test_stream_vision_ingest.py | 3 | tests/integration/ | Needs live services |
| test_multimodal_turn_pipeline.py | 3 | tests/integration/ | Needs live services |
| test_memory_quality_policy.py | 5 | tests/integration/ | Needs live services |
| test_confirmation_idempotency.py | 8 | tests/integration/ | Needs live services |
| test_stage3_compat.py | 7 | tests/integration/ | Needs live services |
| test_stage6_reliability.py | 27 | tests/integration/ | Needs live services |
| test_stage7_chaos_recovery.py | 15 | tests/integration/ | Needs live services |
| test_stage7_backup_restore.py | 10 | tests/integration/ | Needs live services |
| test_v26_cross_track.py | 17 | tests/integration/ | Needs live services |
| test_v28 milestone tests | 104 | tests/integration/ | Needs live services |
| test_v28 hardening tests | 52 | tests/integration/ | Needs live services |
| test_v29 routing/supervision/memory | 68 | tests/integration/ | Needs live services |
| test_ui_conversation_loop.py | ? | tests/integration/ | New, unverified |
| Memory engine unit tests | ~20 | services/memory-engine/tests/ | Use relative imports (may fail) |
| Model router contract tests | ~12 | services/model-router/test_contract.py | Mocked only |
| OpenClaw contract/executor tests | ~20 | services/openclaw/test_*.py | Mocked only |

### Test Infrastructure Issues
1. **No `conftest.py`** anywhere in the project -- no shared fixtures
2. **No `pytest.ini` configuration** beyond a minimal 29-byte file
3. **Memory engine tests use relative imports** (`from ..core.retriever`) -- will fail unless run as package
4. **All integration tests require live services** -- no test containers or mock servers
5. **No end-to-end test** that starts stack -> sends message -> verifies response

---

## SECTION 8: COMPLETE SETUP CHECKLIST

### Phase 1: Prerequisites

- [ ] Python 3.9+ installed at `S:\envs\sonia-core\python.exe`
- [ ] Ollama installed and running at `127.0.0.1:11434`
- [ ] Required Ollama models pulled (`qwen2.5:7b` minimum)
- [ ] Node.js 18+ installed (for UI)
- [ ] GPU drivers + CUDA (optional, for local inference)

### Phase 2: Configuration

- [ ] Create `S:\.env` from template with API keys
- [ ] Align `OLLAMA_MODEL` env var with `sonia-config.json` default
- [ ] Create missing runtime directories (see Section 1.4)
- [ ] Install Python dependencies: `pip install -r requirements-frozen.txt`
- [ ] Install PDF support: `pip install PyMuPDF` (if needed)
- [ ] Verify ports 7000-7050 are available

### Phase 3: Code Fixes (Critical)

- [ ] **Memory engine:** Remove dead code (`memory_engine_service.py`, `db/sqlite.py`, `api/routes_health.py`)
- [ ] **Memory engine:** Fix token budget enforcement (apply to all retrieval endpoints)
- [ ] **Memory engine:** Implement workspace document chunking (currently stub)
- [ ] **Memory engine:** Fix zero-vector fallback embedding
- [ ] **Model router:** Add `httpx` to service-level `requirements.lock`
- [ ] **Model router:** Implement OpenRouter model listing + VISION routing
- [ ] **Config alignment:** Unify default model references across all files

### Phase 4: Build & Launch

- [ ] Build UI: `cd S:\ui\sonia-avatar && npm install && npm run build`
- [ ] Start stack: `S:\start-sonia-stack.ps1`
- [ ] Verify health: `curl http://127.0.0.1:7000/healthz` (repeat for 7010-7050)
- [ ] Test turn pipeline: `S:\scripts\smoke_turn.ps1`
- [ ] Test UI: launch Electron app, send a text message

### Phase 5: Functional Verification

- [ ] Send text message through UI -> verify response
- [ ] Test tool execution through turn pipeline
- [ ] Test memory store/recall cycle
- [ ] Test session create/use/delete lifecycle
- [ ] Run integration test suite: `pytest S:\tests\integration\ -v`

### Phase 6: Optional Enhancements

- [ ] Configure ASR/TTS providers for voice pipeline
- [ ] Enable vision-capture + perception services
- [ ] Ingest knowledge base: `python S:\scripts\ingest-knowledge.py --source <dir>`
- [ ] Set up training pipeline (RunPod scripts)
- [ ] Configure MCP server for Claude Code integration

---

## SECTION 9: SERVICE ARCHITECTURE REFERENCE

```
                    +-----------+
                    |  Electron |
                    |    UI     |
                    +-----+-----+
                          | WS /v1/ui/stream
                          v
                  +-------+--------+
                  |  API Gateway   |  :7000
                  |  (orchestrator)|
                  +--+---+---+--+-+
                     |   |   |  |
          +----------+   |   |  +----------+
          v              v   v             v
    +-----+----+  +------+------+  +------+-----+
    |  Memory  |  |   Model     |  |  OpenClaw   |
    |  Engine  |  |   Router    |  |  (tools)    |
    |  :7020   |  |   :7010     |  |  :7040      |
    +----------+  +------+------+  +-------------+
                         |
              +----------+----------+
              v          v          v
           Ollama    Anthropic  OpenRouter
           :11434    (cloud)    (cloud)

    +----------+     +----------+
    | Pipecat  |     |  EVA-OS  |
    | (voice)  |     | (supervisor)
    |  :7030   |     |  :7050   |
    +----------+     +----------+
```

---

## SECTION 10: WHAT "FUNCTIONAL" MEANS

At minimum, for SONIA to be **functional** (text conversation through UI):

1. API Gateway running on :7000
2. Model Router running on :7010 with at least Ollama connected
3. Memory Engine running on :7020 with SQLite database
4. OpenClaw running on :7040 (for tool execution)
5. Ollama running on :11434 with a chat model
6. UI built and launched (Electron or browser at localhost:5173)
7. User types message -> WebSocket -> turn pipeline -> model -> response -> UI

**This is achievable with the current codebase** once the blockers in Section 1 are resolved and the critical code fixes in Section 2 are applied to the memory engine.

For **full functionality** (voice, vision, tool execution, knowledge base):
- ASR/TTS providers configured (Section 3.1)
- Vision services enabled (Section 3.4)
- Knowledge ingested (Section 3.5)
- All OpenClaw tools registered (Section 3.2)
