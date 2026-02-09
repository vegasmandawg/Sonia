"""
UI Element Detection and Localization Module

Implements detection, classification, and localization of UI elements in screenshots.
Supports button, input, link, image, and other element types.
"""

import asyncio
import base64
import logging
import json
from typing import Optional, Dict, Any, List, Tuple
from dataclasses import dataclass, asdict
from enum import Enum
import io

try:
    from PIL import Image
    import numpy as np
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False

logger = logging.getLogger(__name__)


class ElementType(str, Enum):
    """UI element types."""
    BUTTON = "button"
    INPUT = "input"
    LINK = "link"
    IMAGE = "image"
    TEXT = "text"
    CHECKBOX = "checkbox"
    RADIO = "radio"
    DROPDOWN = "dropdown"
    MENU = "menu"
    MODAL = "modal"
    FORM = "form"
    NAVIGATION = "navigation"
    UNKNOWN = "unknown"


class DetectionModel(str, Enum):
    """Supported detection models."""
    YOLOV8 = "yolov8"
    FASTER_RCNN = "faster_rcnn"
    CUSTOM_OLLAMA = "custom_ollama"
    PADDLE = "paddle"


@dataclass
class UIElement:
    """Represents a detected UI element."""
    element_type: ElementType
    bbox: Tuple[int, int, int, int]  # x, y, width, height
    confidence: float
    label: str
    text_content: Optional[str] = None
    attributes: Optional[Dict[str, Any]] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "type": self.element_type.value,
            "bbox": self.bbox,
            "confidence": self.confidence,
            "label": self.label,
            "text": self.text_content,
            "attributes": self.attributes or {}
        }


@dataclass
class UIAnalysis:
    """Complete UI analysis result."""
    elements: List[UIElement]
    total_elements: int
    image_width: int
    image_height: int
    detection_time_ms: float
    model_used: str


class ElementClassifier:
    """Classifies detected elements into semantic types."""

    def __init__(self):
        """Initialize element classifier."""
        self.logger = logging.getLogger(f"{__name__}.ElementClassifier")

    async def classify(
        self,
        image_bytes: bytes,
        detections: List[Tuple[Tuple[int, int, int, int], float]],
        ocr_results: Optional[Dict[str, Any]] = None
    ) -> List[UIElement]:
        """
        Classify detected regions into UI element types.

        Args:
            image_bytes: Input image bytes
            detections: List of (bbox, confidence) tuples
            ocr_results: Optional OCR results for text analysis

        Returns:
            List of classified UIElement objects
        """
        try:
            if not PIL_AVAILABLE:
                self.logger.warning("PIL not available, using heuristic classification")
                return self._heuristic_classify(detections)

            img = Image.open(io.BytesIO(image_bytes))
            img_array = np.array(img)

            elements = []

            for bbox, conf in detections:
                x, y, w, h = bbox
                
                # Extract region
                region = img.crop((x, y, x + w, y + h))
                region_array = np.array(region)

                # Classify based on visual features
                element_type = await self._classify_region(
                    region_array,
                    region,
                    bbox,
                    ocr_results
                )

                # Extract text if available
                text_content = None
                if ocr_results:
                    text_content = self._extract_region_text(ocr_results, bbox)

                element = UIElement(
                    element_type=element_type,
                    bbox=bbox,
                    confidence=conf,
                    label=element_type.value,
                    text_content=text_content
                )

                elements.append(element)

            return elements

        except Exception as e:
            self.logger.error(f"Classification failed: {e}")
            raise RuntimeError(f"Element classification failed: {e}")

    async def _classify_region(
        self,
        region_array: np.ndarray,
        region_img: Image.Image,
        bbox: Tuple[int, int, int, int],
        ocr_results: Optional[Dict[str, Any]] = None
    ) -> ElementType:
        """
        Classify single region based on visual features.

        Args:
            region_array: NumPy array of region
            region_img: PIL Image of region
            bbox: Bounding box
            ocr_results: Optional OCR data

        Returns:
            Classified ElementType
        """
        x, y, w, h = bbox
        aspect_ratio = w / h if h > 0 else 1.0

        # Feature extraction
        has_text = ocr_results and self._has_text_in_region(ocr_results, bbox)
        
        # Color analysis
        color_variance = np.var(region_array)
        
        # Edge detection (simple Sobel-like)
        edges = self._detect_edges(region_array)
        edge_density = np.sum(edges) / edges.size if edges.size > 0 else 0

        # Shape heuristics
        is_square = 0.7 < aspect_ratio < 1.3
        is_tall = aspect_ratio < 0.5
        is_wide = aspect_ratio > 2.0

        # Classification logic
        if is_square and edge_density > 0.1:
            return ElementType.BUTTON
        elif is_wide and has_text:
            return ElementType.INPUT if color_variance < 50 else ElementType.TEXT
        elif is_tall and edge_density > 0.15:
            return ElementType.DROPDOWN
        elif has_text:
            if "click" in str(ocr_results).lower():
                return ElementType.LINK
            return ElementType.TEXT
        elif edge_density > 0.2:
            return ElementType.IMAGE
        else:
            return ElementType.UNKNOWN

    def _detect_edges(self, image_array: np.ndarray) -> np.ndarray:
        """Simple edge detection using gradient."""
        try:
            if len(image_array.shape) == 3:
                gray = np.mean(image_array, axis=2)
            else:
                gray = image_array

            gx = np.gradient(gray, axis=0)
            gy = np.gradient(gray, axis=1)
            magnitude = np.sqrt(gx**2 + gy**2)
            
            return magnitude > np.mean(magnitude)

        except Exception as e:
            self.logger.warning(f"Edge detection failed: {e}")
            return np.array([])

    def _has_text_in_region(
        self,
        ocr_results: Dict[str, Any],
        bbox: Tuple[int, int, int, int]
    ) -> bool:
        """Check if region contains text from OCR."""
        if "boxes" not in ocr_results:
            return False

        x, y, w, h = bbox
        region_area = w * h

        for box_info in ocr_results.get("boxes", []):
            box_x, box_y, box_w, box_h = box_info.get("bbox", (0, 0, 0, 0))
            
            # Check overlap
            if (x < box_x + box_w and x + w > box_x and
                y < box_y + box_h and y + h > box_y):
                return True

        return False

    def _extract_region_text(
        self,
        ocr_results: Dict[str, Any],
        bbox: Tuple[int, int, int, int]
    ) -> Optional[str]:
        """Extract text content for region from OCR."""
        x, y, w, h = bbox
        texts = []

        for box_info in ocr_results.get("boxes", []):
            box_x, box_y, box_w, box_h = box_info.get("bbox", (0, 0, 0, 0))
            
            if (x < box_x + box_w and x + w > box_x and
                y < box_y + box_h and y + h > box_y):
                text = box_info.get("text", "")
                if text:
                    texts.append(text)

        return " ".join(texts) if texts else None

    def _heuristic_classify(
        self,
        detections: List[Tuple[Tuple[int, int, int, int], float]]
    ) -> List[UIElement]:
        """Fallback classification without PIL."""
        elements = []

        for bbox, conf in detections:
            x, y, w, h = bbox
            aspect_ratio = w / h if h > 0 else 1.0

            # Simple heuristic without image data
            if 0.7 < aspect_ratio < 1.3:
                elem_type = ElementType.BUTTON
            elif aspect_ratio > 2.0:
                elem_type = ElementType.INPUT
            elif aspect_ratio < 0.5:
                elem_type = ElementType.DROPDOWN
            else:
                elem_type = ElementType.UNKNOWN

            element = UIElement(
                element_type=elem_type,
                bbox=bbox,
                confidence=conf,
                label=elem_type.value
            )
            elements.append(element)

        return elements


class UIElementDetector:
    """Detects UI elements in screenshots using various models."""

    def __init__(self, model_type: DetectionModel = DetectionModel.YOLOV8):
        """
        Initialize UI element detector.

        Args:
            model_type: Detection model to use
        """
        self.logger = logging.getLogger(f"{__name__}.UIElementDetector")
        self.model_type = model_type
        self.classifier = ElementClassifier()
        self.model = None

    async def detect(
        self,
        image_bytes: bytes,
        confidence_threshold: float = 0.5,
        use_ocr: bool = True,
        ocr_data: Optional[Dict[str, Any]] = None
    ) -> UIAnalysis:
        """
        Detect UI elements in image.

        Args:
            image_bytes: Input image bytes
            confidence_threshold: Minimum confidence score
            use_ocr: Whether to use OCR for text extraction
            ocr_data: Pre-computed OCR results

        Returns:
            UIAnalysis with detected elements

        Raises:
            RuntimeError: If detection fails
        """
        import time
        start_time = time.time()

        try:
            if not PIL_AVAILABLE:
                raise RuntimeError("PIL required for UI detection")

            img = Image.open(io.BytesIO(image_bytes))
            img_width, img_height = img.size

            # Perform detection based on model type
            detections = await self._detect_elements(
                image_bytes,
                confidence_threshold
            )

            # Classify elements
            elements = await self.classifier.classify(
                image_bytes,
                detections,
                ocr_data
            )

            elapsed_ms = (time.time() - start_time) * 1000

            return UIAnalysis(
                elements=elements,
                total_elements=len(elements),
                image_width=img_width,
                image_height=img_height,
                detection_time_ms=elapsed_ms,
                model_used=self.model_type.value
            )

        except Exception as e:
            self.logger.error(f"UI detection failed: {e}")
            raise RuntimeError(f"Failed to detect UI elements: {e}")

    async def _detect_elements(
        self,
        image_bytes: bytes,
        confidence_threshold: float
    ) -> List[Tuple[Tuple[int, int, int, int], float]]:
        """
        Perform actual element detection.

        Args:
            image_bytes: Input image bytes
            confidence_threshold: Minimum confidence

        Returns:
            List of (bbox, confidence) tuples
        """
        if self.model_type == DetectionModel.YOLOV8:
            return await self._yolov8_detect(image_bytes, confidence_threshold)
        elif self.model_type == DetectionModel.CUSTOM_OLLAMA:
            return await self._ollama_detect(image_bytes, confidence_threshold)
        elif self.model_type == DetectionModel.PADDLE:
            return await self._paddle_detect(image_bytes, confidence_threshold)
        else:
            return await self._yolov8_detect(image_bytes, confidence_threshold)

    async def _yolov8_detect(
        self,
        image_bytes: bytes,
        confidence_threshold: float
    ) -> List[Tuple[Tuple[int, int, int, int], float]]:
        """Detect using YOLOv8."""
        try:
            from ultralytics import YOLO

            if not self.model:
                self.model = await asyncio.to_thread(
                    YOLO,
                    "yolov8n.pt"  # nano model for speed
                )

            img = Image.open(io.BytesIO(image_bytes))

            results = await asyncio.to_thread(
                self.model,
                img
            )

            detections = []
            for result in results:
                for box in result.boxes:
                    conf = float(box.conf)
                    if conf >= confidence_threshold:
                        x1, y1, x2, y2 = map(int, box.xyxy[0])
                        w = x2 - x1
                        h = y2 - y1
                        detections.append(((x1, y1, w, h), conf))

            return detections

        except ImportError:
            self.logger.warning("ultralytics not available, trying fallback")
            return await self._ollama_detect(image_bytes, confidence_threshold)

    async def _ollama_detect(
        self,
        image_bytes: bytes,
        confidence_threshold: float
    ) -> List[Tuple[Tuple[int, int, int, int], float]]:
        """Detect using Ollama vision model."""
        try:
            import aiohttp

            image_b64 = base64.b64encode(image_bytes).decode('utf-8')

            async with aiohttp.ClientSession() as session:
                prompt = """Detect all UI elements in this screenshot.
                Return JSON array with: [{"x": int, "y": int, "width": int, "height": int, "type": str, "confidence": float}]
                Element types: button, input, link, image, text, checkbox, dropdown, menu, form
                """

                payload = {
                    "model": "llava",
                    "prompt": prompt,
                    "images": [image_b64],
                    "stream": False
                }

                async with session.post(
                    "http://localhost:11434/api/generate",
                    json=payload,
                    timeout=aiohttp.ClientTimeout(total=120)
                ) as resp:
                    if resp.status != 200:
                        raise RuntimeError(f"Ollama error: {await resp.text()}")

                    data = await resp.json()
                    response_text = data.get("response", "")

                    # Parse JSON from response
                    try:
                        import re
                        json_match = re.search(r'\[.*\]', response_text, re.DOTALL)
                        if json_match:
                            detections_data = json.loads(json_match.group())
                            detections = []
                            for det in detections_data:
                                conf = float(det.get("confidence", 0.5))
                                if conf >= confidence_threshold:
                                    bbox = (
                                        det["x"],
                                        det["y"],
                                        det["width"],
                                        det["height"]
                                    )
                                    detections.append((bbox, conf))
                            return detections
                    except (json.JSONDecodeError, KeyError):
                        self.logger.warning("Failed to parse Ollama detection response")

                    return []

        except Exception as e:
            self.logger.error(f"Ollama detection failed: {e}")
            return []

    async def _paddle_detect(
        self,
        image_bytes: bytes,
        confidence_threshold: float
    ) -> List[Tuple[Tuple[int, int, int, int], float]]:
        """Detect using PaddleDetection."""
        try:
            # PaddleDetection is similar to PaddleOCR but for object detection
            self.logger.info("PaddleDetection not yet fully implemented")
            return []

        except Exception as e:
            self.logger.error(f"Paddle detection failed: {e}")
            return []

    async def localize_element(
        self,
        image_bytes: bytes,
        element_label: str,
        fuzzy_match: bool = True
    ) -> Optional[UIElement]:
        """
        Find specific element by label.

        Args:
            image_bytes: Input image bytes
            element_label: Label to search for
            fuzzy_match: Allow approximate matching

        Returns:
            Located UIElement or None

        Raises:
            RuntimeError: If detection fails
        """
        analysis = await self.detect(image_bytes)

        for element in analysis.elements:
            if fuzzy_match:
                # Fuzzy string matching
                if element.label.lower() in element_label.lower():
                    return element
                if element.text_content and element_label.lower() in element.text_content.lower():
                    return element
            else:
                if element.label.lower() == element_label.lower():
                    return element

        return None

    async def localize_by_type(
        self,
        image_bytes: bytes,
        element_type: ElementType,
        index: int = 0
    ) -> Optional[UIElement]:
        """
        Find nth element of specific type.

        Args:
            image_bytes: Input image bytes
            element_type: Type to find
            index: Which element (0-based)

        Returns:
            Located UIElement or None

        Raises:
            RuntimeError: If detection fails
        """
        analysis = await self.detect(image_bytes)

        matching_elements = [
            e for e in analysis.elements
            if e.element_type == element_type
        ]

        if index < len(matching_elements):
            return matching_elements[index]

        return None


class AccessibilityAnalyzer:
    """Analyzes UI for accessibility issues."""

    def __init__(self):
        """Initialize accessibility analyzer."""
        self.logger = logging.getLogger(f"{__name__}.AccessibilityAnalyzer")

    async def analyze(self, analysis: UIAnalysis) -> Dict[str, Any]:
        """
        Analyze UI for accessibility issues.

        Args:
            analysis: UIAnalysis result

        Returns:
            Accessibility report
        """
        issues = []
        suggestions = []

        # Check for missing text labels
        for element in analysis.elements:
            if element.element_type in [ElementType.BUTTON, ElementType.LINK]:
                if not element.text_content:
                    issues.append(f"{element.element_type.value} missing text label")
                    suggestions.append(f"Add aria-label to {element.element_type.value}")

        # Check for color contrast (simplified)
        if not self._check_color_contrast(analysis):
            issues.append("Possible low contrast text")
            suggestions.append("Increase color contrast between text and background")

        # Check element spacing
        if not self._check_element_spacing(analysis):
            issues.append("Elements may be too close together")
            suggestions.append("Increase spacing between interactive elements")

        return {
            "total_issues": len(issues),
            "total_elements": analysis.total_elements,
            "issues": issues,
            "suggestions": suggestions,
            "accessibility_score": max(0, 100 - len(issues) * 10)
        }

    def _check_color_contrast(self, analysis: UIAnalysis) -> bool:
        """Check color contrast (simplified check)."""
        # Would require color analysis - simplified for now
        return True

    def _check_element_spacing(self, analysis: UIAnalysis) -> bool:
        """Check element spacing."""
        min_spacing = 5  # pixels

        for i, elem1 in enumerate(analysis.elements):
            for elem2 in analysis.elements[i + 1:]:
                x1, y1, w1, h1 = elem1.bbox
                x2, y2, w2, h2 = elem2.bbox

                # Check distance
                dx = x2 - (x1 + w1) if x2 > x1 + w1 else x1 - (x2 + w2)
                dy = y2 - (y1 + h1) if y2 > y1 + h1 else y1 - (y2 + h2)

                if dx >= 0 and dy >= 0 and min(dx, dy) < min_spacing:
                    return False

        return True
