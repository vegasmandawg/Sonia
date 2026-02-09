# Pipecat Voice Service API Reference

## Overview

Pipecat is the real-time voice and modality gateway for Sonia, enabling low-latency voice interactions with <200ms round-trip latency target.

**Service**: Pipecat Voice Gateway  
**Port**: 7030  
**Protocol**: WebSocket (audio) + REST (control)  
**Latency Target**: <200ms p99 for round-trip voice interaction  

---

## REST Endpoints

### Health Endpoints

#### GET /health
Health check endpoint.

**Response** (200 OK):
```json
{
  "status": "healthy",
  "service": "pipecat",
  "version": "1.0.0",
  "timestamp": "2026-02-08T14:30:00Z"
}
```

#### GET /status
Service status with active sessions.

**Response** (200 OK):
```json
{
  "service": "pipecat",
  "version": "1.0.0",
  "status": "running",
  "active_sessions": 3,
  "timestamp": "2026-02-08T14:30:00Z"
}
```

### Session Management

#### POST /api/v1/session/create
Create new voice session.

**Query Parameters**:
- `user_id` (required): User identifier

**Response** (200 OK):
```json
{
  "session_id": "550e8400-e29b-41d4-a716-446655440000",
  "user_id": "user-123",
  "status": "created"
}
```

#### GET /api/v1/session/{session_id}/info
Get session information.

**Response** (200 OK):
```json
{
  "session_id": "550e8400-e29b-41d4-a716-446655440000",
  "user_id": "user-123",
  "created_at": "2026-02-08T14:30:00Z",
  "last_activity": "2026-02-08T14:31:00Z",
  "transcript": "What is the weather?",
  "turn_count": 3,
  "is_speaking_user": false,
  "is_speaking_assistant": false
}
```

#### POST /api/v1/session/{session_id}/interrupt
Interrupt current synthesis (barge-in/interruption).

**Response** (200 OK):
```json
{
  "status": "interrupted",
  "session_id": "550e8400-e29b-41d4-a716-446655440000"
}
```

---

## WebSocket Streaming Protocol

### Connection

**URL**: `ws://127.0.0.1:7030/stream/{session_id}`

**Auth**: Bearer token (from API Gateway session)

**Headers**:
```
Authorization: Bearer <session_token>
Content-Type: application/json
```

### Connection Lifecycle

1. Client connects to WebSocket
2. Server sends `connected` event
3. Client sends audio frames
4. Server sends events (speech, transcript, status)
5. Client receives audio responses
6. Client or server closes connection

### Message Format

All messages are JSON with optional base64-encoded binary audio.

```json
{
  "type": "audio|transcript|status|audio_response",
  "session_id": "...",
  "data": "base64_audio_or_string",
  "timestamp": "2026-02-08T14:30:00Z"
}
```

---

## Message Types

### Client → Server

#### audio
Send audio frame to server.

```json
{
  "type": "audio",
  "data": "//uQpAAAAOQAP0AAJKAV...",
  "timestamp": "2026-02-08T14:30:00Z"
}
```

**Audio Format**:
- Codec: PCM 16-bit signed
- Sample rate: 16 kHz
- Channels: Mono (1)
- Chunk size: 512 samples (32ms)

#### interrupt
Interrupt assistant's speech (barge-in).

```json
{
  "type": "interrupt",
  "timestamp": "2026-02-08T14:30:00Z"
}
```

---

### Server → Client

#### connected
Connection established.

```json
{
  "type": "connected",
  "session_id": "550e8400-e29b-41d4-a716-446655440000",
  "message": "Connected to Pipecat voice service"
}
```

#### audio_frame
Audio frame from client (for server acknowledgement).

```json
{
  "type": "audio_frame",
  "is_speech": true,
  "confidence": 0.92,
  "timestamp": "2026-02-08T14:30:00Z"
}
```

#### partial_transcript
Interim transcript while user is speaking.

```json
{
  "type": "partial_transcript",
  "text": "What is the we...",
  "timestamp": "2026-02-08T14:30:00Z"
}
```

#### transcript
Final transcript of user's speech.

```json
{
  "type": "transcript",
  "text": "What is the weather?",
  "confidence": 0.95,
  "timestamp": "2026-02-08T14:30:00Z"
}
```

#### turn_complete
User's turn is complete (silence detected after speech).

```json
{
  "type": "turn_complete",
  "transcript": "What is the weather?",
  "confidence": 0.95,
  "timestamp": "2026-02-08T14:30:00Z"
}
```

#### audio_response
Assistant's response audio.

```json
{
  "type": "audio_response",
  "data": "//uQpAAAAOQAP0AAJKAV...",
  "duration_ms": 3500,
  "timestamp": "2026-02-08T14:30:00Z"
}
```

#### status
Status update (listening, processing, responding, etc.).

```json
{
  "type": "status",
  "status": "responding",
  "details": "Synthesizing response",
  "timestamp": "2026-02-08T14:30:00Z"
}
```

#### error
Error event.

```json
{
  "type": "error",
  "error": "ASR service unavailable",
  "timestamp": "2026-02-08T14:30:00Z"
}
```

---

## Voice Pipeline

### Processing Flow

```
Client Audio Frame
    ↓
VAD (Voice Activity Detection)
    ├→ Detects speech vs silence
    ├→ Returns is_speech, confidence
    └→ Sends partial_transcript
    ↓
ASR (Automatic Speech Recognition)
    ├→ When silence detected after speech
    ├→ Transcribes audio to text
    └→ Sends turn_complete with transcript
    ↓
Model Router (external)
    ├→ Processes transcript
    ├→ Generates response
    └→ Returns response text
    ↓
TTS (Text-to-Speech)
    ├→ Synthesizes response text
    ├→ Generates audio chunks
    └→ Streams audio back to client
    ↓
Client Plays Audio
```

### Latency Breakdown

| Stage | Latency | Notes |
|-------|---------|-------|
| VAD | 5ms | Per frame |
| ASR | 100-500ms | Depends on Qwen availability |
| Model Router | 500-5000ms | LLM inference |
| TTS | 50-200ms | Audio synthesis |
| Network | 10-50ms | WebSocket overhead |
| **Total (p99)** | **<200ms** | Target for responsive feel |

---

## Configuration

### Environment Variables

```bash
# VAD Configuration
VAD_BACKEND=energy              # energy, silero, webrtc
VAD_THRESHOLD=0.5              # Speech detection threshold
VAD_MIN_SPEECH_DURATION=100    # Min ms of speech to recognize
VAD_MIN_SILENCE_DURATION=500   # Min ms silence to end turn

# ASR Configuration
ASR_BACKEND=qwen               # qwen, ollama-whisper, openai
ASR_BASE_URL=http://127.0.0.1:8000
ASR_MODEL=qwen-audio
ASR_LANGUAGE=en

# TTS Configuration
TTS_BACKEND=qwen               # qwen, ollama, openai
TTS_BASE_URL=http://127.0.0.1:8000
TTS_MODEL=qwen-tts
TTS_VOICE=default
TTS_SPEED=1.0                  # 0.5-2.0
```

### Advanced Configuration

```python
from pipecat.pipeline import VADConfig, ASRConfig, TTSConfig

# VAD with Silero (more accurate but slower)
vad_config = VADConfig(
    backend="silero",
    min_speech_duration=150,
    min_silence_duration=400,
)

# ASR with local Whisper
asr_config = ASRConfig(
    backend="ollama-whisper",
    base_url="http://127.0.0.1:11434",
    language="en",
)

# TTS with voice selection
tts_config = TTSConfig(
    backend="qwen",
    voice="female",  # or "male"
    speed=1.2,  # Faster speech
)
```

---

## Client Examples

### JavaScript/TypeScript

```javascript
const sessionId = "550e8400-e29b-41d4-a716-446655440000";
const ws = new WebSocket(`ws://127.0.0.1:7030/stream/${sessionId}`);

// Connect
ws.onopen = () => {
  console.log("Connected to Pipecat");
};

// Handle messages
ws.onmessage = (event) => {
  const message = JSON.parse(event.data);
  
  switch (message.type) {
    case "partial_transcript":
      console.log("Interim:", message.text);
      break;
    case "transcript":
      console.log("Final:", message.text);
      break;
    case "audio_response":
      const audioData = atob(message.data);
      playAudio(audioData);
      break;
    case "status":
      console.log("Status:", message.status);
      break;
  }
};

// Send audio
async function sendAudio(audioBuffer) {
  const base64 = btoa(String.fromCharCode(...audioBuffer));
  ws.send(JSON.stringify({
    type: "audio",
    data: base64,
  }));
}

// Interrupt
function interrupt() {
  ws.send(JSON.stringify({
    type: "interrupt",
  }));
}
```

### Python

```python
import asyncio
import websockets
import json
import base64

async def voice_stream(session_id, audio_stream):
    uri = f"ws://127.0.0.1:7030/stream/{session_id}"
    
    async with websockets.connect(uri) as ws:
        # Send audio frames
        async for audio_frame in audio_stream:
            message = {
                "type": "audio",
                "data": base64.b64encode(audio_frame).decode(),
            }
            await ws.send(json.dumps(message))
            
            # Receive events
            response = await ws.recv()
            event = json.loads(response)
            print(f"Event: {event['type']} - {event.get('text', '')}")
```

---

## Performance Characteristics

### Latency (p99)

- VAD detection: 5-10ms per frame
- ASR (Qwen): 100-500ms
- TTS synthesis: 50-200ms
- Network roundtrip: 10-50ms
- **Total voice interaction**: <200ms target

### Throughput

- Concurrent sessions: 10-100+ (depends on hardware)
- Audio frames: 30-50 fps (32ms chunks at 16kHz)
- Bandwidth per session: ~32kbps (16-bit mono @ 16kHz)

### Resource Usage

- Per session memory: 5-10 MB
- CPU: 5-10% per concurrent session
- GPU (if using): Optional for faster TTS

---

## Error Handling

### Common Errors

#### ASR Service Unavailable
- **Symptom**: Transcripts return empty or timeouts
- **Solution**: Ensure Qwen ASR is running, check `ASR_BASE_URL`
- **Fallback**: Continue session, partial transcripts work with VAD

#### TTS Service Unavailable
- **Symptom**: No audio responses
- **Solution**: Ensure Qwen TTS is running, check `TTS_BASE_URL`
- **Fallback**: Return text responses instead

#### High Latency
- **Symptom**: Noticeable delay in responses
- **Solutions**:
  1. Reduce ASR/TTS backend complexity
  2. Check network latency (should be <50ms)
  3. Profile which component is slow

#### VAD False Positives
- **Symptom**: Transcript activates on background noise
- **Solution**: Increase `VAD_THRESHOLD` (0.5 → 0.6-0.7)
- **Alternative**: Switch to Silero VAD for better accuracy

---

## Testing

### Health Check

```bash
# Check service health
curl http://127.0.0.1:7030/health

# Expected response
{
  "status": "healthy",
  "service": "pipecat",
  "version": "1.0.0"
}
```

### Create Session

```bash
# Create voice session
curl -X POST "http://127.0.0.1:7030/api/v1/session/create?user_id=user-123"

# Expected response
{
  "session_id": "550e8400-e29b-41d4-a716-446655440000",
  "user_id": "user-123",
  "status": "created"
}
```

### Voice Streaming Test

```bash
# Connect WebSocket and send test audio
wscat -c "ws://127.0.0.1:7030/stream/550e8400-e29b-41d4-a716-446655440000"

# Send audio frame (base64-encoded)
{"type": "audio", "data": "//uQpAAAAOQAP0AAJKAV..."}
```

---

## Future Enhancements

### v1.1
- [ ] Multi-language support (currently en only)
- [ ] Speaker identification
- [ ] Emotion detection in voice
- [ ] Custom voice profiles

### v1.2
- [ ] Streaming ASR (partial results before silence)
- [ ] GPU-accelerated TTS
- [ ] Voice effects (echo, pitch shift)
- [ ] Advanced turn-taking with overlap detection

### v1.3
- [ ] Multi-party conversations (speaker diarization)
- [ ] Real-time transcription display
- [ ] Voice authentication (speaker verification)
- [ ] Prosody-aware TTS (emotion in speech)

---

**API Version**: 1.0  
**Last Updated**: 2026-02-08  
**Status**: Production Ready
