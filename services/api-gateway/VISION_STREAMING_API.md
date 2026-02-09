# Vision and Streaming API Documentation

## Overview

The Vision and Streaming API provides comprehensive capabilities for:
- **Screenshot Capture**: Desktop and browser screenshot acquisition
- **Vision Analysis**: Multi-provider image analysis with streaming support
- **OCR**: Text extraction from images with multiple backend options
- **UI Detection**: Automated detection and localization of UI elements
- **Streaming Responses**: Real-time SSE (Server-Sent Events) streaming of results
- **Image Processing**: Compression, resizing, cropping, format conversion

## Architecture

### Core Modules

#### 1. **vision.py** (718 lines)
Handles image capture and vision model integration.

**Classes:**
- `ScreenCapture`: Captures desktop/browser screenshots
- `ImageProcessor`: Image preprocessing and optimization
- `VisionClient`: Multi-provider vision API client
  - Supports: Ollama, OpenAI, Claude, Qwen

**Key Features:**
- Cross-platform screenshot via mss or PIL ImageGrab
- Image compression with configurable quality
- Automatic format conversion (JPEG, PNG, WebP)
- Batch vision analysis with concurrent processing
- Graceful degradation when PIL unavailable

#### 2. **ocr.py** (631 lines)
Optical Character Recognition with multiple backends.

**Classes:**
- `TesseractOCR`: Tesseract engine wrapper
- `PaddleOCR`: PaddlePaddle-based OCR
- `OllamaOCR`: Vision model-based OCR
- `OCREngine`: Main orchestrator with fallback logic

**Key Features:**
- Multi-language support (10+ languages)
- Bounding box extraction with confidence scores
- Automatic provider fallback
- Language detection
- Memory decay optimization (box consolidation)

**Supported Providers:**
- Tesseract (local, free)
- PaddleOCR (local, fast, accurate)
- Ollama (local, flexible)
- OpenAI (cloud, high quality)
- Google (cloud, standard)

#### 3. **ui_detection.py** (649 lines)
UI element detection and semantic classification.

**Classes:**
- `UIElementDetector`: Detects UI elements in screenshots
- `ElementClassifier`: Classifies elements by type
- `AccessibilityAnalyzer`: Analyzes UI for accessibility
- `UIElement`: Represents single UI element with metadata

**Element Types:**
- Button, Input, Link, Image
- Checkbox, Radio, Dropdown
- Menu, Modal, Form, Navigation
- Text, Unknown

**Detection Models:**
- YOLOv8 (fast, accurate)
- Faster R-CNN (slower, precise)
- Custom Ollama (flexible, local)
- PaddleDetection (fast, alternative)

#### 4. **streaming.py** (351 lines)
Real-time streaming response engine.

**Classes:**
- `StreamingResponse`: SSE event accumulation and emission
- `WebSocketStream`: Bidirectional WebSocket communication

**Event Types:**
- `stream_start`, `stream_complete`, `stream_error`
- `text_chunk`, `thinking`, `tool_call`, `tool_result`
- `metadata`, `status`

### API Gateway

**api_gateway.py** (294 lines)
- Main FastAPI application
- Service orchestration and routing
- Health checks for dependent services
- CORS and request ID middleware
- Centralized error handling

## API Endpoints

### Screenshot Capture

#### POST `/api/v1/vision/screenshot/capture`

Capture desktop screenshot with optional region selection.

**Query Parameters:**
```
region: [left, top, width, height] - Optional partial capture region
format: "png" | "jpeg" | "webp" - Output format (default: png)
quality: 1-100 - Compression quality for JPEG/WebP (default: 85)
```

**Response:**
```json
{
  "success": true,
  "data": "base64-encoded-image",
  "metadata": {
    "width": 1920,
    "height": 1080,
    "format": "png",
    "mode": "RGB",
    "size_bytes": 524288,
    "aspect_ratio": 1.778
  },
  "timestamp": "2024-01-15T10:30:45.123Z"
}
```

**Example:**
```bash
curl -X POST http://localhost:7010/api/v1/vision/screenshot/capture \
  -H "Content-Type: application/json"
```

---

### Image Analysis

#### POST `/api/v1/vision/image/analyze`

Analyze image with vision model.

**Body:**
```json
{
  "image_data": "base64-encoded-image",
  "prompt": "What objects are in this image?"
}
```

**Query Parameters:**
```
provider: "ollama" | "openai" | "claude" - Vision provider (default: ollama)
model: string - Model name (optional, uses provider default)
max_tokens: int - Max response tokens (default: 1024)
temperature: 0.0-1.0 - Response temperature (default: 0.7)
stream: boolean - Enable SSE streaming (default: false)
```

**Response (Non-streaming):**
```json
{
  "success": true,
  "result": "The image shows a laptop with a cup of coffee...",
  "provider": "ollama",
  "model": "llava",
  "timestamp": "2024-01-15T10:30:45.123Z"
}
```

**Response (Streaming - SSE):**
```
data: {"type":"analysis_start","provider":"ollama","model":"llava","timestamp":"..."}

data: {"type":"text_chunk","content":"The image shows"}

data: {"type":"text_chunk","content":" a laptop with"}

data: {"type":"analysis_complete","total_length":45}
```

**Example:**
```python
import requests
import base64

with open("screenshot.png", "rb") as f:
    image_b64 = base64.b64encode(f.read()).decode()

response = requests.post(
    "http://localhost:7010/api/v1/vision/image/analyze",
    json={
        "image_data": image_b64,
        "prompt": "Describe the UI layout"
    },
    params={"provider": "ollama", "stream": True}
)

for line in response.iter_lines():
    if line:
        print(line)
```

---

### OCR Text Extraction

#### POST `/api/v1/vision/ocr/extract`

Extract text from image using OCR.

**Body:**
```json
{
  "image_data": "base64-encoded-image"
}
```

**Query Parameters:**
```
provider: "tesseract" | "paddle" | "ollama" - OCR provider (default: tesseract)
language: string - Language code (e.g., "eng", "spa", "chi_sim")
return_boxes: boolean - Include bounding boxes (default: false)
```

**Response (Text Only):**
```json
{
  "success": true,
  "text": "Extracted text content from image...",
  "provider": "tesseract",
  "timestamp": "2024-01-15T10:30:45.123Z"
}
```

**Response (With Boxes):**
```json
{
  "success": true,
  "text": "Extracted text content from image...",
  "boxes": [
    {
      "text": "Extracted",
      "confidence": 0.95,
      "bbox": [10, 20, 80, 30],
      "language": "eng"
    },
    {
      "text": "text",
      "confidence": 0.93,
      "bbox": [100, 20, 50, 30],
      "language": "eng"
    }
  ],
  "provider": "tesseract",
  "total_boxes": 2
}
```

**Example:**
```bash
curl -X POST http://localhost:7010/api/v1/vision/ocr/extract \
  -H "Content-Type: application/json" \
  -d '{
    "image_data": "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
  }' \
  -G -d "provider=tesseract&return_boxes=true"
```

---

### UI Element Detection

#### POST `/api/v1/vision/ui/detect`

Detect UI elements in screenshot.

**Body:**
```json
{
  "image_data": "base64-encoded-image"
}
```

**Query Parameters:**
```
confidence_threshold: 0.0-1.0 - Min detection confidence (default: 0.5)
extract_text: boolean - Extract text from elements (default: true)
stream: boolean - Enable SSE streaming (default: false)
```

**Response (Non-streaming):**
```json
{
  "success": true,
  "elements": [
    {
      "type": "button",
      "bbox": [100, 200, 100, 40],
      "confidence": 0.92,
      "label": "button",
      "text": "Click Me"
    },
    {
      "type": "input",
      "bbox": [100, 300, 200, 30],
      "confidence": 0.88,
      "label": "input",
      "text": null
    }
  ],
  "total_elements": 2,
  "image_dimensions": {
    "width": 1920,
    "height": 1080
  },
  "detection_time_ms": 234.5,
  "model": "yolov8"
}
```

**Response (Streaming - SSE):**
```
data: {"type":"detection_start","timestamp":"..."}

data: {"type":"detection_progress","total_elements":5}

data: {"type":"element_detected","element":{"type":"button","bbox":[100,200,100,40],...}}

data: {"type":"element_detected","element":{"type":"input","bbox":[100,300,200,30],...}}

data: {"type":"detection_complete","detection_time_ms":234.5}
```

---

### Element Localization

#### POST `/api/v1/vision/ui/localize`

Find specific UI element by label.

**Body:**
```json
{
  "image_data": "base64-encoded-image",
  "element_label": "Submit Button"
}
```

**Query Parameters:**
```
fuzzy_match: boolean - Allow approximate matching (default: true)
```

**Response:**
```json
{
  "success": true,
  "element": {
    "type": "button",
    "bbox": [500, 600, 120, 40],
    "confidence": 0.95,
    "label": "button",
    "text": "Submit"
  },
  "timestamp": "2024-01-15T10:30:45.123Z"
}
```

**Error Response (404):**
```json
{
  "success": false,
  "error": "Element 'Login Button' not found"
}
```

---

### Accessibility Analysis

#### POST `/api/v1/vision/accessibility/analyze`

Analyze UI for accessibility issues.

**Body:**
```json
{
  "image_data": "base64-encoded-image"
}
```

**Response:**
```json
{
  "success": true,
  "report": {
    "total_issues": 2,
    "total_elements": 10,
    "issues": [
      "Button missing text label",
      "Possible low contrast text"
    ],
    "suggestions": [
      "Add aria-label to button",
      "Increase color contrast between text and background"
    ],
    "accessibility_score": 80
  },
  "total_elements_analyzed": 10,
  "timestamp": "2024-01-15T10:30:45.123Z"
}
```

---

### Image Processing

#### POST `/api/v1/vision/image/process`

Apply image processing operations.

**Body:**
```json
{
  "image_data": "base64-encoded-image",
  "operation": "resize",
  "parameters": {
    "max_width": 800,
    "max_height": 600,
    "maintain_aspect": true
  }
}
```

**Supported Operations:**

1. **Resize**
```json
{
  "operation": "resize",
  "parameters": {
    "max_width": 1280,
    "max_height": 720,
    "maintain_aspect": true
  }
}
```

2. **Compress**
```json
{
  "operation": "compress",
  "parameters": {
    "quality": 75,
    "format": "jpeg"
  }
}
```

3. **Crop**
```json
{
  "operation": "crop",
  "parameters": {
    "region": [100, 100, 500, 400]
  }
}
```

4. **Convert**
```json
{
  "operation": "convert",
  "parameters": {
    "format": "webp"
  }
}
```

**Response:**
```json
{
  "success": true,
  "data": "base64-encoded-processed-image",
  "operation": "resize",
  "metadata": {
    "width": 800,
    "height": 600,
    "format": "png",
    "size_bytes": 245120
  },
  "timestamp": "2024-01-15T10:30:45.123Z"
}
```

---

## Streaming (SSE) Format

All SSE endpoints follow a standard format:

```
data: {json_object}\n\n
```

**Common Event Types:**
- `stream_start`: Stream initialization
- `text_chunk`: Text content chunk
- `thinking`: Intermediate reasoning
- `tool_call`: Tool invocation
- `tool_result`: Tool result
- `metadata`: Additional metadata
- `status`: Status updates
- `stream_complete`: Completion
- `error`: Error condition

**Example Parser (Python):**
```python
import json
from sseclient import SSEClient

response = requests.post(
    "http://localhost:7010/api/v1/vision/image/analyze",
    json=payload,
    params={"stream": True},
    stream=True
)

client = SSEClient(response)
for event in client:
    if event.event:
        data = json.loads(event.data)
        if data["type"] == "text_chunk":
            print(data["content"], end="", flush=True)
        elif data["type"] == "stream_complete":
            print("\n[Complete]")
        elif data["type"] == "error":
            print(f"\n[Error] {data['error']}")
```

---

## Configuration

### Environment Variables

```bash
# Service Configuration
API_GATEWAY_PORT=7010
API_GATEWAY_HOST=0.0.0.0
LOG_LEVEL=INFO

# Service URLs
VOICE_SERVICE_URL=http://localhost:7030
MEMORY_SERVICE_URL=http://localhost:7000
TOOL_SERVICE_URL=http://localhost:7040

# Vision Settings
VISION_PROVIDER=ollama          # ollama, openai, claude, qwen
OCR_PROVIDER=tesseract          # tesseract, paddle, ollama
DETECTION_MODEL=yolov8          # yolov8, faster_rcnn, custom_ollama

# CORS
CORS_ORIGINS=http://localhost:3000,http://localhost:3001
```

---

## Error Handling

All endpoints return consistent error responses:

```json
{
  "success": false,
  "error": "Error description",
  "request_id": "uuid-for-tracing"
}
```

**HTTP Status Codes:**
- `200`: Success
- `400`: Bad request (invalid parameters)
- `404`: Resource not found (element not found)
- `500`: Server error
- `503`: Service unavailable

---

## Performance Characteristics

### Latency Targets (p99)

| Operation | Latency | Notes |
|-----------|---------|-------|
| Screenshot | 50ms | Desktop capture |
| OCR (small image) | 200ms | Tesseract |
| Vision Analysis | 1-5s | Depends on model |
| UI Detection | 300-800ms | YOLOv8 |
| Image Processing | 100-500ms | Depends on operation |

### Throughput

- **Concurrent Requests**: ~20-50 (depends on provider)
- **Batch Processing**: Up to 100 images for UI detection
- **SSE Clients**: ~100 concurrent streams

### Memory Usage

- **Base Service**: ~200MB
- **YOLOv8 Model**: ~100MB
- **Image Cache**: Configurable, ~1GB default

---

## Integration Examples

### Complete Vision Pipeline

```python
import requests
import base64
import json
from datetime import datetime

async def analyze_screenshot():
    """Complete vision analysis pipeline."""
    
    # 1. Capture screenshot
    response = requests.post(
        "http://localhost:7010/api/v1/vision/screenshot/capture"
    )
    image_data = response.json()["data"]
    
    # 2. Extract text via OCR
    ocr_response = requests.post(
        "http://localhost:7010/api/v1/vision/ocr/extract",
        json={"image_data": image_data},
        params={"return_boxes": True}
    )
    ocr_results = ocr_response.json()
    
    # 3. Detect UI elements
    ui_response = requests.post(
        "http://localhost:7010/api/v1/vision/ui/detect",
        json={"image_data": image_data}
    )
    ui_elements = ui_response.json()
    
    # 4. Analyze with vision model
    vision_response = requests.post(
        "http://localhost:7010/api/v1/vision/image/analyze",
        json={
            "image_data": image_data,
            "prompt": "Describe the layout and main UI elements"
        }
    )
    vision_analysis = vision_response.json()
    
    return {
        "timestamp": datetime.utcnow().isoformat(),
        "screenshot_size": len(image_data),
        "ocr_results": ocr_results,
        "ui_elements": ui_elements,
        "vision_analysis": vision_analysis
    }
```

### Real-time Streaming Analysis

```python
import asyncio
import json
import sseclient
import requests

async def stream_analysis(image_data):
    """Stream vision analysis in real-time."""
    
    response = requests.post(
        "http://localhost:7010/api/v1/vision/image/analyze",
        json={
            "image_data": image_data,
            "prompt": "Analyze this screenshot"
        },
        params={"stream": True},
        stream=True
    )
    
    client = sseclient.SSEClient(response)
    
    for event in client:
        if event.event:
            data = json.loads(event.data)
            
            if data["type"] == "analysis_start":
                print(f"Starting analysis with {data['model']}...")
            
            elif data["type"] == "text_chunk":
                print(data["content"], end="", flush=True)
            
            elif data["type"] == "stream_complete":
                print(f"\n[Complete in {data['total_length']} chars]")
            
            elif data["type"] == "error":
                print(f"\n[Error] {data['error']}")
                break
```

---

## Troubleshooting

### Issue: "PIL not available"
**Solution**: Install Pillow
```bash
pip install Pillow
```

### Issue: OCR Provider Fallback Triggered
**Solution**: Check provider-specific requirements
```bash
# Tesseract
pip install pytesseract

# PaddleOCR
pip install paddleocr

# Ollama
# Install Ollama separately: https://ollama.ai
```

### Issue: UI Detection Low Confidence
**Solution**: Reduce confidence threshold or use different model
```json
{
  "confidence_threshold": 0.3,
  "detection_model": "paddle"
}
```

### Issue: Timeout on Large Images
**Solution**: Resize image before processing
```json
{
  "operation": "resize",
  "parameters": {
    "max_width": 1280,
    "max_height": 720
  }
}
```

---

## Best Practices

1. **Always Provide Request IDs** for tracing through logs
2. **Use Streaming** for real-time feedback on long operations
3. **Compress Images** before transmission for faster processing
4. **Cache Results** to avoid duplicate processing
5. **Set Appropriate Timeouts** (30-120s for vision operations)
6. **Monitor Service Health** before production use
7. **Batch Process** when handling multiple images
8. **Use Region Capture** to reduce processing scope

---

## API Version

- **Current Version**: 1.0.0
- **Last Updated**: 2024-01-15
- **Service Port**: 7010
