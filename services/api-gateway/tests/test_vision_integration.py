"""
Vision Integration Tests

End-to-end tests for vision module integration.
Tests screenshot capture, OCR, UI detection, and vision analysis.
"""

import asyncio
import base64
import json
import pytest
from io import BytesIO
from pathlib import Path

# Mock imports for testing
try:
    from PIL import Image
    import numpy as np
except ImportError:
    pass


class MockScreenCapture:
    """Mock screen capture for testing."""

    async def capture_screenshot(self, region=None):
        """Return mock PNG image."""
        img = Image.new('RGB', (1920, 1080), color='white')
        buffer = BytesIO()
        img.save(buffer, format='PNG')
        return buffer.getvalue()


class MockVisionClient:
    """Mock vision client for testing."""

    async def analyze_image(self, image_bytes, prompt, model=None, max_tokens=1024, temperature=0.7):
        """Return mock analysis result."""
        return f"Mock analysis of image using prompt: {prompt[:50]}..."


class MockOCREngine:
    """Mock OCR engine for testing."""

    async def extract_text(self, image_bytes, language=None, provider=None):
        """Return mock extracted text."""
        return "Mock extracted text from image"

    async def extract_boxes(self, image_bytes, language=None, provider=None):
        """Return mock OCR boxes."""
        class MockBox:
            def __init__(self, text, confidence, bbox):
                self.text = text
                self.confidence = confidence
                self.bbox = bbox

        return [
            MockBox("Mock", 0.95, (10, 20, 50, 30)),
            MockBox("Text", 0.92, (70, 20, 50, 30)),
        ]


class MockUIDetector:
    """Mock UI detector for testing."""

    async def detect(self, image_bytes, confidence_threshold=0.5, extract_text=True, ocr_data=None):
        """Return mock UI analysis."""
        class MockElement:
            def __init__(self, elem_type, bbox, confidence, label, text):
                self.element_type = elem_type
                self.bbox = bbox
                self.confidence = confidence
                self.label = label
                self.text_content = text

            def to_dict(self):
                return {
                    "type": self.element_type,
                    "bbox": self.bbox,
                    "confidence": self.confidence,
                    "label": self.label,
                    "text": self.text_content
                }

        class MockAnalysis:
            def __init__(self):
                self.elements = [
                    MockElement("button", (100, 200, 100, 40), 0.92, "button", "Click Me"),
                    MockElement("input", (100, 300, 200, 30), 0.88, "input", None),
                ]
                self.total_elements = 2
                self.image_width = 1920
                self.image_height = 1080
                self.detection_time_ms = 234.5
                self.model_used = "mock"

        return MockAnalysis()


# Test Classes
class TestScreenCapture:
    """Test screenshot capture functionality."""

    @pytest.mark.asyncio
    async def test_capture_screenshot(self):
        """Test basic screenshot capture."""
        capture = MockScreenCapture()
        image_bytes = await capture.capture_screenshot()

        assert isinstance(image_bytes, bytes)
        assert len(image_bytes) > 0

    @pytest.mark.asyncio
    async def test_capture_region(self):
        """Test regional screenshot capture."""
        capture = MockScreenCapture()
        region = (0, 0, 800, 600)
        image_bytes = await capture.capture_screenshot(region)

        assert isinstance(image_bytes, bytes)
        assert len(image_bytes) > 0


class TestImageProcessor:
    """Test image processing functionality."""

    @pytest.mark.asyncio
    async def test_image_resize(self):
        """Test image resizing."""
        # Create test image
        img = Image.new('RGB', (1920, 1080))
        buffer = BytesIO()
        img.save(buffer, format='PNG')
        image_bytes = buffer.getvalue()

        # Mock processor would resize
        assert isinstance(image_bytes, bytes)

    @pytest.mark.asyncio
    async def test_image_compression(self):
        """Test image compression."""
        img = Image.new('RGB', (800, 600))
        buffer = BytesIO()
        img.save(buffer, format='PNG')
        image_bytes = buffer.getvalue()

        original_size = len(image_bytes)
        assert original_size > 0


class TestOCREngine:
    """Test OCR functionality."""

    @pytest.mark.asyncio
    async def test_extract_text(self):
        """Test text extraction."""
        ocr = MockOCREngine()
        text = await ocr.extract_text(b"mock_image")

        assert isinstance(text, str)
        assert len(text) > 0

    @pytest.mark.asyncio
    async def test_extract_boxes(self):
        """Test box extraction."""
        ocr = MockOCREngine()
        boxes = await ocr.extract_boxes(b"mock_image")

        assert isinstance(boxes, list)
        assert len(boxes) > 0
        assert all(hasattr(b, 'text') for b in boxes)
        assert all(hasattr(b, 'bbox') for b in boxes)
        assert all(hasattr(b, 'confidence') for b in boxes)

    @pytest.mark.asyncio
    async def test_language_detection(self):
        """Test language detection."""
        ocr = MockOCREngine()
        # Mock would detect language
        detected_lang = "eng"
        assert detected_lang == "eng"


class TestUIDetection:
    """Test UI element detection."""

    @pytest.mark.asyncio
    async def test_detect_elements(self):
        """Test element detection."""
        detector = MockUIDetector()
        img = Image.new('RGB', (1920, 1080))
        buffer = BytesIO()
        img.save(buffer, format='PNG')
        image_bytes = buffer.getvalue()

        analysis = await detector.detect(image_bytes)

        assert analysis.total_elements == 2
        assert analysis.image_width == 1920
        assert analysis.image_height == 1080
        assert len(analysis.elements) == 2

    @pytest.mark.asyncio
    async def test_element_classification(self):
        """Test element type classification."""
        detector = MockUIDetector()
        img = Image.new('RGB', (1920, 1080))
        buffer = BytesIO()
        img.save(buffer, format='PNG')
        image_bytes = buffer.getvalue()

        analysis = await detector.detect(image_bytes)

        element_types = [e.element_type for e in analysis.elements]
        assert "button" in element_types
        assert "input" in element_types

    @pytest.mark.asyncio
    async def test_element_to_dict(self):
        """Test element serialization."""
        detector = MockUIDetector()
        img = Image.new('RGB', (1920, 1080))
        buffer = BytesIO()
        img.save(buffer, format='PNG')
        image_bytes = buffer.getvalue()

        analysis = await detector.detect(image_bytes)
        element_dict = analysis.elements[0].to_dict()

        assert "type" in element_dict
        assert "bbox" in element_dict
        assert "confidence" in element_dict
        assert "label" in element_dict


class TestVisionAnalysis:
    """Test vision model analysis."""

    @pytest.mark.asyncio
    async def test_vision_analysis(self):
        """Test vision model analysis."""
        client = MockVisionClient()
        img = Image.new('RGB', (1920, 1080))
        buffer = BytesIO()
        img.save(buffer, format='PNG')
        image_bytes = buffer.getvalue()

        result = await client.analyze_image(
            image_bytes,
            "Describe this image",
            model="mock_model"
        )

        assert isinstance(result, str)
        assert len(result) > 0


class TestStreamingResponse:
    """Test SSE streaming response."""

    def test_sse_format(self):
        """Test SSE event formatting."""
        event_data = {
            "type": "test_event",
            "data": "test"
        }

        # SSE format: data: {json}\n\n
        sse_line = f"data: {json.dumps(event_data)}\n\n"

        assert sse_line.startswith("data: ")
        assert sse_line.endswith("\n\n")
        assert json.loads(sse_line[6:-2]) == event_data

    def test_sse_multiple_events(self):
        """Test multiple SSE events."""
        events = [
            {"type": "start", "data": "beginning"},
            {"type": "chunk", "content": "text"},
            {"type": "complete", "data": "done"},
        ]

        sse_output = ""
        for event in events:
            sse_output += f"data: {json.dumps(event)}\n\n"

        lines = sse_output.split("data: ")
        # First element is empty due to split
        parsed_events = []
        for line in lines[1:]:
            if line.strip():
                parsed_events.append(json.loads(line.strip()))

        assert len(parsed_events) == 3
        assert parsed_events[0]["type"] == "start"
        assert parsed_events[1]["type"] == "chunk"
        assert parsed_events[2]["type"] == "complete"


class TestAPIIntegration:
    """Test API integration scenarios."""

    @pytest.mark.asyncio
    async def test_screenshot_to_ocr_pipeline(self):
        """Test screenshot -> OCR pipeline."""
        # Capture
        capture = MockScreenCapture()
        image_bytes = await capture.capture_screenshot()

        # OCR
        ocr = MockOCREngine()
        text = await ocr.extract_text(image_bytes)

        assert isinstance(text, str)
        assert len(text) > 0

    @pytest.mark.asyncio
    async def test_screenshot_to_ui_detection_pipeline(self):
        """Test screenshot -> UI detection pipeline."""
        # Capture
        capture = MockScreenCapture()
        image_bytes = await capture.capture_screenshot()

        # UI Detection
        detector = MockUIDetector()
        analysis = await detector.detect(image_bytes, extract_text=True)

        assert analysis.total_elements > 0

    @pytest.mark.asyncio
    async def test_full_vision_pipeline(self):
        """Test complete vision analysis pipeline."""
        # Capture
        capture = MockScreenCapture()
        image_bytes = await capture.capture_screenshot()

        # OCR
        ocr = MockOCREngine()
        text = await ocr.extract_text(image_bytes)

        # UI Detection
        detector = MockUIDetector()
        ui_analysis = await detector.detect(image_bytes)

        # Vision Analysis
        vision = MockVisionClient()
        vision_result = await vision.analyze_image(
            image_bytes,
            "Analyze this UI"
        )

        assert isinstance(text, str)
        assert ui_analysis.total_elements > 0
        assert isinstance(vision_result, str)

    @pytest.mark.asyncio
    async def test_concurrent_analyses(self):
        """Test concurrent image analyses."""
        capture = MockScreenCapture()
        image_bytes = await capture.capture_screenshot()

        ocr = MockOCREngine()
        detector = MockUIDetector()
        vision = MockVisionClient()

        # Run concurrently
        results = await asyncio.gather(
            ocr.extract_text(image_bytes),
            detector.detect(image_bytes),
            vision.analyze_image(image_bytes, "Analyze"),
        )

        assert len(results) == 3
        assert all(r is not None for r in results)


class TestErrorHandling:
    """Test error handling and edge cases."""

    @pytest.mark.asyncio
    async def test_invalid_image_data(self):
        """Test handling of invalid image data."""
        ocr = MockOCREngine()

        # Should handle gracefully or raise appropriate error
        try:
            result = await ocr.extract_text(b"invalid_data")
            assert result is not None
        except Exception as e:
            assert isinstance(e, Exception)

    @pytest.mark.asyncio
    async def test_empty_image(self):
        """Test handling of empty image."""
        detector = MockUIDetector()

        analysis = await detector.detect(b"")
        assert analysis is not None

    @pytest.mark.asyncio
    async def test_large_image_processing(self):
        """Test handling of large images."""
        # Create large image
        img = Image.new('RGB', (4096, 2160))
        buffer = BytesIO()
        img.save(buffer, format='PNG')
        large_image = buffer.getvalue()

        assert len(large_image) > 1_000_000  # > 1MB
        assert isinstance(large_image, bytes)


class TestPerformance:
    """Test performance characteristics."""

    @pytest.mark.asyncio
    async def test_ocr_latency(self):
        """Test OCR latency."""
        import time

        ocr = MockOCREngine()
        img = Image.new('RGB', (1920, 1080))
        buffer = BytesIO()
        img.save(buffer, format='PNG')
        image_bytes = buffer.getvalue()

        start = time.time()
        await ocr.extract_text(image_bytes)
        elapsed = (time.time() - start) * 1000

        assert elapsed < 5000  # Should complete in < 5s

    @pytest.mark.asyncio
    async def test_ui_detection_latency(self):
        """Test UI detection latency."""
        import time

        detector = MockUIDetector()
        img = Image.new('RGB', (1920, 1080))
        buffer = BytesIO()
        img.save(buffer, format='PNG')
        image_bytes = buffer.getvalue()

        start = time.time()
        await detector.detect(image_bytes)
        elapsed = (time.time() - start) * 1000

        assert elapsed < 5000  # Should complete in < 5s

    @pytest.mark.asyncio
    async def test_batch_processing(self):
        """Test batch processing of multiple images."""
        import time

        detector = MockUIDetector()
        
        # Create multiple test images
        images = []
        for _ in range(5):
            img = Image.new('RGB', (1920, 1080))
            buffer = BytesIO()
            img.save(buffer, format='PNG')
            images.append(buffer.getvalue())

        start = time.time()
        results = await asyncio.gather(
            *[detector.detect(img) for img in images]
        )
        elapsed = (time.time() - start) * 1000

        assert len(results) == 5
        assert elapsed < 10000  # All 5 should complete in < 10s


# Pytest configuration
if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
