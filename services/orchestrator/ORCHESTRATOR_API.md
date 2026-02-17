# Orchestrator API Documentation

## Overview

The Orchestrator Service coordinates all Sonia platform services (Voice, Vision, Memory, Tools) into a unified multimodal agent. It implements intelligent decision-making, action orchestration, and seamless service integration.

## Architecture

### Core Components

1. **Agent** (641 lines)
   - Main orchestration engine
   - State management (IDLE, LISTENING, PROCESSING, EXECUTING, RESPONDING)
   - Action type coordination (6 action types)
   - Service integration layer

2. **DecisionMaker**
   - Analyzes user intent from messages
   - Decides what actions to take
   - Approval policy enforcement

3. **MemoryManager**
   - Integrates with Memory Engine (Phase D)
   - Retrieves relevant context
   - Stores experiences and interactions

4. **VisionHandler**
   - Integrates with Vision Service (Phase F)
   - Screenshot capture
   - UI element detection
   - Vision analysis

5. **ToolExecutor**
   - Integrates with Tool Service (Phase G)
   - Single and batch execution
   - Rate limiting coordination

6. **VoiceHandler**
   - Integrates with Voice Service (Phase E)
   - Speech synthesis
   - (Ready for ASR integration)

7. **OrchestratorService**
   - FastAPI application
   - 13 REST endpoints
   - Conversation management
   - Multi-service coordination

### Action Types

| Action Type | Service | Description | Use Case |
|------------|---------|-------------|----------|
| SCREENSHOT | Vision | Capture desktop/browser screenshot | "Show me the screen" |
| VISION_ANALYSIS | Vision | Analyze screenshot with vision model | "What's on screen?" |
| TOOL_CALL | Tools | Execute tools | "Read a file" |
| MEMORY_STORE | Memory | Store experience | "Remember this" |
| MEMORY_RETRIEVE | Memory | Retrieve context | "What did I tell you?" |
| VOICE_OUTPUT | Voice | Synthesize speech | Response delivery |

### Agent States

```
IDLE → LISTENING → PROCESSING → EXECUTING → RESPONDING → IDLE
                       ↓
                    ERROR (any point)
```

## API Endpoints

### Agent Interaction (5)

#### POST /api/v1/agent/process
Process user input with full agent orchestration.

**Body:**
```json
{
  "message": "Show me the screen and read the file /etc/hostname"
}
```

**Query Parameters:**
```
conversation_id: string (optional, auto-generated)
user_id: string (optional)
auto_execute: boolean (default: true)
```

**Response:**
```json
{
  "success": true,
  "context": {
    "conversation_id": "uuid",
    "user_id": null,
    "current_state": "idle",
    "actions_taken": 2,
    "action_results": 2,
    "confidence_score": 0.85,
    "response": "I've captured a screenshot and read the file..."
  },
  "response": "I've captured a screenshot and read the file...",
  "actions_executed": 2,
  "confidence": 0.85,
  "timestamp": "2024-01-15T10:30:45.123Z"
}
```

---

#### GET /api/v1/agent/status
Get agent configuration and status.

**Response:**
```json
{
  "agent_id": "uuid",
  "name": "Sonia",
  "description": "Multimodal AI Agent",
  "features": {
    "memory": true,
    "vision": true,
    "tools": true
  },
  "active_conversations": 3,
  "timestamp": "2024-01-15T10:30:45.123Z"
}
```

---

### Conversation Management (3)

#### GET /api/v1/conversations
List recent conversations.

**Query Parameters:**
```
limit: integer (default: 10)
```

**Response:**
```json
{
  "success": true,
  "total": 3,
  "conversations": [
    {
      "conversation_id": "uuid",
      "user_id": null,
      "current_state": "idle",
      "actions_taken": 2,
      "action_results": 2,
      "confidence_score": 0.85,
      "response": "...",
      "started_at": "2024-01-15T10:30:45.123Z",
      "updated_at": "2024-01-15T10:32:10.456Z"
    }
  ]
}
```

---

#### GET /api/v1/conversations/{conversation_id}
Get specific conversation details.

**Response:**
```json
{
  "success": true,
  "context": { /* full context */ },
  "actions": [
    {
      "action_id": "uuid",
      "type": "screenshot",
      "target": "screenshot/capture",
      "reasoning": "User asked to see the screen",
      "timestamp": "2024-01-15T10:30:46.123Z"
    }
  ],
  "results": {
    "action_1": { /* result */ }
  }
}
```

---

#### POST /api/v1/conversations/{conversation_id}/continue
Continue existing conversation.

**Body:**
```json
{
  "message": "Read the file /etc/hostname"
}
```

**Query Parameters:**
```
auto_execute: boolean (default: true)
```

**Response:**
```json
{
  "success": true,
  "context": { /* updated context */ },
  "response": "Here's the content of /etc/hostname: ...",
  "total_actions": 3,
  "confidence": 0.85
}
```

---

### Vision Integration (1)

#### POST /api/v1/agent/analyze-screenshot
Capture and analyze current screenshot.

**Query Parameters:**
```
conversation_id: string (optional)
user_id: string (optional)
```

**Response:**
```json
{
  "success": true,
  "screenshot_captured": true,
  "ui_elements_detected": 12,
  "analysis": "The screen shows a text editor with a file open...",
  "elements": [
    {
      "type": "button",
      "bbox": [100, 200, 100, 40],
      "confidence": 0.92,
      "text": "Save"
    }
  ],
  "timestamp": "2024-01-15T10:30:45.123Z"
}
```

---

### Tool Execution (1)

#### POST /api/v1/agent/execute-tool
Execute a specific tool.

**Query Parameters:**
```
tool_name: string (required)
conversation_id: string (optional)
auto_execute: boolean (default: true)
```

**Body:**
```json
{
  "path": "/etc/hostname"
}
```

**Response:**
```json
{
  "success": true,
  "tool": "read_file",
  "result": {
    "request_id": "uuid",
    "tool_name": "read_file",
    "status": "completed",
    "result": "mycomputer"
  },
  "timestamp": "2024-01-15T10:30:45.123Z"
}
```

---

### Memory Integration (2)

#### POST /api/v1/agent/store-memory
Store information in agent memory.

**Body:**
```json
{
  "content": "The user prefers dark mode",
  "entity_type": "user_preference",
  "metadata": {
    "category": "ui",
    "importance": "high"
  }
}
```

**Query Parameters:**
```
conversation_id: string (optional)
```

**Response:**
```json
{
  "success": true,
  "stored": true,
  "content_length": 28,
  "entity_type": "user_preference",
  "timestamp": "2024-01-15T10:30:45.123Z"
}
```

---

#### POST /api/v1/agent/retrieve-memory
Retrieve information from memory.

**Body:**
```json
{
  "query": "user preferences"
}
```

**Query Parameters:**
```
limit: integer (default: 5)
conversation_id: string (optional)
```

**Response:**
```json
{
  "success": true,
  "query": "user preferences",
  "memories_found": 2,
  "memories": [
    {
      "id": "uuid",
      "content": "The user prefers dark mode",
      "entity_type": "user_preference",
      "similarity": 0.92,
      "created_at": "2024-01-15T10:25:00.000Z"
    }
  ],
  "timestamp": "2024-01-15T10:30:45.123Z"
}
```

---

## Integration Examples

### Python Client

```python
import aiohttp
import asyncio

async def interact_with_agent():
    async with aiohttp.ClientSession() as session:
        # Process user input
        response = await session.post(
            "http://localhost:8000/api/v1/agent/process",
            json={"message": "Show me the screen and tell me about it"},
            params={"user_id": "user123"}
        )
        
        result = await response.json()
        print(f"Agent Response: {result['response']}")
        print(f"Actions Executed: {result['actions_executed']}")
        
        # Continue conversation
        conversation_id = result['context']['conversation_id']
        response2 = await session.post(
            f"http://localhost:8000/api/v1/conversations/{conversation_id}/continue",
            json={"message": "Remember this preference"}
        )
        
        result2 = await response2.json()
        print(f"Continued: {result2['response']}")

asyncio.run(interact_with_agent())
```

### JavaScript/Node.js

```javascript
async function interactWithAgent() {
  // Process input
  const response = await fetch(
    'http://localhost:8000/api/v1/agent/process',
    {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({
        message: 'What files are in this directory?'
      }),
      params: new URLSearchParams({ user_id: 'user123' })
    }
  );
  
  const result = await response.json();
  console.log(`Agent: ${result.response}`);
  
  // Analyze screenshot
  const ssResponse = await fetch(
    'http://localhost:8000/api/v1/agent/analyze-screenshot',
    { method: 'POST' }
  );
  
  const ssResult = await ssResponse.json();
  console.log(`Analysis: ${ssResult.analysis}`);
}

interactWithAgent();
```

### cURL Examples

```bash
# Process user input
curl -X POST http://localhost:8000/api/v1/agent/process \
  -H "Content-Type: application/json" \
  -d '{"message": "Show me the screen"}' \
  -G -d "user_id=user123"

# Continue conversation
CONV_ID="abc-123-def-456"
curl -X POST "http://localhost:8000/api/v1/conversations/$CONV_ID/continue" \
  -H "Content-Type: application/json" \
  -d '{"message": "Read the file"}'

# Analyze screenshot
curl -X POST http://localhost:8000/api/v1/agent/analyze-screenshot

# Retrieve memory
curl -X POST http://localhost:8000/api/v1/agent/retrieve-memory \
  -H "Content-Type: application/json" \
  -d '{"query": "important facts"}'
```

---

## Configuration

### Environment Variables

```bash
# Service
ORCHESTRATOR_PORT=8000
ORCHESTRATOR_HOST=0.0.0.0
LOG_LEVEL=INFO

# Agent
AGENT_NAME=Sonia
ENABLE_MEMORY=true
ENABLE_VISION=true
ENABLE_TOOLS=true

# Dependent Services (already configured in Agent)
# Voice Service: http://localhost:7030
# Vision Service: http://localhost:7010
# Memory Service: http://localhost:7000
# Tool Service: http://localhost:7080
```

---

## Agent Decision Logic

### Screenshots Triggered By:
- "see", "show", "look", "screen", "screenshot", "ui", "button"

### Tools Triggered By:
- "read", "write", "calculate", "search", "find", "fetch"

### Memory Store Triggered By:
- "remember", "save", "note", "store"

### Memory Retrieval Triggered By:
- "recall", "remember", "what was", "did i", "history"

---

## Workflow Example

### User: "Show me the desktop and remember my color preference"

1. **PROCESSING**: Analyze message
   - Action 1: SCREENSHOT (trigger: "show")
   - Action 2: MEMORY_STORE (trigger: "remember")

2. **EXECUTING**: Perform actions
   - Action 1: Capture screenshot
   - Action 2: Store "color preference" in memory

3. **RESPONDING**: Generate response
   - "I've captured a screenshot of the desktop and saved your color preference to memory."

4. **IDLE**: Ready for next input

---

## Service Integration

### Memory Engine (Phase D)
- Retrieves relevant context
- Stores experiences and learnings
- Supports semantic search

### Voice Service (Phase E)
- Provides speech synthesis
- (Ready for ASR integration for voice input)

### Vision Service (Phase F)
- Captures screenshots
- Detects UI elements
- Analyzes visual content

### Tool Service (Phase G)
- Executes tools with approval
- Enforces rate limiting
- Manages execution state

---

## Error Handling

### Response Format
```json
{
  "detail": "Error description",
  "status": 400
}
```

### Common Errors

| Status | Cause | Solution |
|--------|-------|----------|
| 404 | Conversation not found | Use conversation_id from previous response |
| 500 | Service unavailable | Check downstream service (Memory, Vision, Tools) |
| 500 | Screenshot capture failed | Ensure display/graphics available |
| 500 | Tool execution failed | Check tool parameters and approval |

---

## Performance

### Latency Targets (p99)
- Agent process: 500ms-10s (depends on actions)
- Vision analysis: 1-5s
- Tool execution: 50ms-5s
- Memory retrieval: 100-500ms

### Throughput
- Sequential: 10-100 conversations/second
- Concurrent: 50+ simultaneous conversations
- Batch operations: Linear with count

---

## Best Practices

1. **Reuse Conversation IDs** for multi-turn interactions
2. **Store Important Context** in memory for later retrieval
3. **Leverage Screenshots** for visual confirmation
4. **Monitor Confidence Scores** to validate responses
5. **Use Tool Categories** to guide agent decisions
6. **Cache Tool Results** to avoid duplicate execution
7. **Track User Preferences** via memory system
8. **Implement Retry Logic** for transient failures

---

## API Version

- **Current Version**: 1.0.0
- **Service Port**: 8000
- **Last Updated**: 2024-01-15
