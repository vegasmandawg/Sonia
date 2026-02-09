"""
OCR Module

Implements Optical Character Recognition for extracting text from images.
Supports multiple OCR backends with fallback options.
"""

import asyncio
import base64
import logging
import json
from typing import Optional, Dict, Any, List, Tuple
from dataclasses import dataclass
from enum import Enum
import io

try:
    import pytesseract
    from PIL import Image
    PYTESSERACT_AVAILABLE = True
except ImportError:
    PYTESSERACT_AVAILABLE = False

logger = logging.getLogger(__name__)


class OCRProvider(str, Enum):
    """Supported OCR providers."""
    TESSERACT = "tesseract"
    PADDLE = "paddle"
    OLLAMA = "ollama"
    OPENAI = "openai"
    GOOGLE = "google"


class OCRLanguage(str, Enum):
    """Supported OCR languages."""
    ENGLISH = "eng"
    SPANISH = "spa"
    FRENCH = "fra"
    GERMAN = "deu"
    CHINESE_SIMPLIFIED = "chi_sim"
    CHINESE_TRADITIONAL = "chi_tra"
    JAPANESE = "jpn"
    KOREAN = "kor"
    RUSSIAN = "rus"
    ARABIC = "ara"


@dataclass
class OCRBox:
    """Represents a text detection bounding box."""
    text: str
    confidence: float
    bbox: Tuple[int, int, int, int]  # x, y, width, height
    language: str
    font_size: Optional[int] = None


@dataclass
class OCRResult:
    """Complete OCR analysis result."""
    text: str
    confidence: float
    language: str
    boxes: List[OCRBox]
    page_count: int = 1
    processing_time_ms: float = 0.0
    provider: str = "unknown"


class TesseractOCR:
    """Tesseract-based OCR engine."""

    def __init__(self, languages: List[str] = None):
        """
        Initialize Tesseract OCR.

        Args:
            languages: List of language codes (e.g., ['eng', 'spa'])
        """
        self.logger = logging.getLogger(f"{__name__}.TesseractOCR")
        self.languages = languages or [OCRLanguage.ENGLISH.value]
        
        if not PYTESSERACT_AVAILABLE:
            self.logger.warning("pytesseract not available")

    async def extract_text(
        self,
        image_bytes: bytes,
        language: Optional[str] = None
    ) -> str:
        """
        Extract text from image using Tesseract.

        Args:
            image_bytes: Input image bytes
            language: Language code (overrides default)

        Returns:
            Extracted text

        Raises:
            RuntimeError: If OCR fails
        """
        if not PYTESSERACT_AVAILABLE:
            raise RuntimeError("pytesseract not available")

        try:
            img = Image.open(io.BytesIO(image_bytes))
            lang = language or '+'.join(self.languages)
            
            text = await asyncio.to_thread(
                pytesseract.image_to_string,
                img,
                lang=lang
            )
            
            return text.strip()
            
        except Exception as e:
            self.logger.error(f"Tesseract extraction failed: {e}")
            raise RuntimeError(f"OCR extraction failed: {e}")

    async def extract_boxes(
        self,
        image_bytes: bytes,
        language: Optional[str] = None
    ) -> List[OCRBox]:
        """
        Extract text with bounding boxes.

        Args:
            image_bytes: Input image bytes
            language: Language code

        Returns:
            List of OCRBox objects

        Raises:
            RuntimeError: If OCR fails
        """
        if not PYTESSERACT_AVAILABLE:
            raise RuntimeError("pytesseract not available")

        try:
            img = Image.open(io.BytesIO(image_bytes))
            lang = language or '+'.join(self.languages)
            
            # Get data with bounding boxes
            data = await asyncio.to_thread(
                pytesseract.image_to_data,
                img,
                lang=lang,
                output_type=pytesseract.Output.DICT
            )
            
            boxes = []
            for i, text in enumerate(data['text']):
                if text.strip():
                    conf = int(data['conf'][i])
                    if conf > 0:  # Only include detected text
                        box = OCRBox(
                            text=text,
                            confidence=conf / 100.0,
                            bbox=(
                                data['left'][i],
                                data['top'][i],
                                data['width'][i],
                                data['height'][i]
                            ),
                            language=lang
                        )
                        boxes.append(box)
            
            return boxes
            
        except Exception as e:
            self.logger.error(f"Tesseract box extraction failed: {e}")
            raise RuntimeError(f"OCR box extraction failed: {e}")

    async def detect_language(self, image_bytes: bytes) -> str:
        """
        Detect document language.

        Args:
            image_bytes: Input image bytes

        Returns:
            Language code

        Raises:
            RuntimeError: If detection fails
        """
        try:
            img = Image.open(io.BytesIO(image_bytes))
            
            # Try common languages for detection
            results = {}
            for lang in ['eng', 'spa', 'fra', 'deu', 'chi_sim']:
                text = await asyncio.to_thread(
                    pytesseract.image_to_string,
                    img,
                    lang=lang
                )
                # Higher score if more text detected
                results[lang] = len(text.strip().split())
            
            best_lang = max(results, key=results.get)
            return best_lang
            
        except Exception as e:
            self.logger.error(f"Language detection failed: {e}")
            return OCRLanguage.ENGLISH.value


class PaddleOCR:
    """PaddleOCR engine (PaddlePaddle-based)."""

    def __init__(self, language: str = "en"):
        """
        Initialize PaddleOCR.

        Args:
            language: Language code (en, ch, etc.)
        """
        self.logger = logging.getLogger(f"{__name__}.PaddleOCR")
        self.language = language
        self.ocr = None
        self._initialized = False

    async def initialize(self):
        """Initialize PaddleOCR engine (lazy initialization)."""
        if self._initialized:
            return

        try:
            from paddleocr import PaddleOCR as PaddleOCREngine
            self.ocr = await asyncio.to_thread(
                PaddleOCREngine,
                use_angle_cls=True,
                lang=self.language
            )
            self._initialized = True
        except ImportError:
            raise RuntimeError("paddleocr not installed")

    async def extract_text(self, image_bytes: bytes) -> str:
        """
        Extract text using PaddleOCR.

        Args:
            image_bytes: Input image bytes

        Returns:
            Extracted text

        Raises:
            RuntimeError: If OCR fails
        """
        try:
            await self.initialize()
            
            img = Image.open(io.BytesIO(image_bytes))
            
            result = await asyncio.to_thread(self.ocr.ocr, img, cls=True)
            
            # Extract text from result structure
            texts = []
            for line in result:
                for word_info in line:
                    texts.append(word_info[1][0])
            
            return '\n'.join(texts)
            
        except Exception as e:
            self.logger.error(f"PaddleOCR extraction failed: {e}")
            raise RuntimeError(f"OCR extraction failed: {e}")

    async def extract_boxes(self, image_bytes: bytes) -> List[OCRBox]:
        """
        Extract text with bounding boxes using PaddleOCR.

        Args:
            image_bytes: Input image bytes

        Returns:
            List of OCRBox objects

        Raises:
            RuntimeError: If OCR fails
        """
        try:
            await self.initialize()
            
            img = Image.open(io.BytesIO(image_bytes))
            
            result = await asyncio.to_thread(self.ocr.ocr, img, cls=True)
            
            boxes = []
            for line in result:
                for word_info in line:
                    points, (text, conf) = word_info
                    # Convert points to bbox
                    xs = [p[0] for p in points]
                    ys = [p[1] for p in points]
                    
                    box = OCRBox(
                        text=text,
                        confidence=float(conf),
                        bbox=(min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys)),
                        language=self.language
                    )
                    boxes.append(box)
            
            return boxes
            
        except Exception as e:
            self.logger.error(f"PaddleOCR box extraction failed: {e}")
            raise RuntimeError(f"OCR box extraction failed: {e}")


class OllamaOCR:
    """Ollama-based OCR via vision model."""

    def __init__(self, base_url: str = "http://localhost:11434"):
        """
        Initialize Ollama OCR.

        Args:
            base_url: Ollama service URL
        """
        self.logger = logging.getLogger(f"{__name__}.OllamaOCR")
        self.base_url = base_url

    async def extract_text(
        self,
        image_bytes: bytes,
        model: str = "llava"
    ) -> str:
        """
        Extract text using Ollama vision model.

        Args:
            image_bytes: Input image bytes
            model: Model name

        Returns:
            Extracted text

        Raises:
            RuntimeError: If OCR fails
        """
        try:
            import aiohttp
            
            image_b64 = base64.b64encode(image_bytes).decode('utf-8')
            
            async with aiohttp.ClientSession() as session:
                payload = {
                    "model": model,
                    "prompt": "Extract all text from this image. Return only the text content.",
                    "images": [image_b64],
                    "stream": False
                }
                
                async with session.post(
                    f"{self.base_url}/api/generate",
                    json=payload,
                    timeout=aiohttp.ClientTimeout(total=120)
                ) as resp:
                    if resp.status != 200:
                        error_text = await resp.text()
                        raise RuntimeError(f"Ollama API error: {error_text}")
                    
                    data = await resp.json()
                    return data.get("response", "").strip()
                    
        except Exception as e:
            self.logger.error(f"Ollama OCR extraction failed: {e}")
            raise RuntimeError(f"OCR extraction failed: {e}")

    async def extract_boxes(self, image_bytes: bytes, model: str = "llava") -> List[OCRBox]:
        """
        Extract text with confidence using Ollama.

        Args:
            image_bytes: Input image bytes
            model: Model name

        Returns:
            List of OCRBox objects

        Raises:
            RuntimeError: If OCR fails
        """
        try:
            import aiohttp
            
            image_b64 = base64.b64encode(image_bytes).decode('utf-8')
            
            async with aiohttp.ClientSession() as session:
                prompt = """Analyze this image and list all visible text with approximate positions.
                Format: "text|confidence|x|y|width|height" one per line
                Example: "Hello|0.95|10|20|50|15"
                """
                
                payload = {
                    "model": model,
                    "prompt": prompt,
                    "images": [image_b64],
                    "stream": False
                }
                
                async with session.post(
                    f"{self.base_url}/api/generate",
                    json=payload,
                    timeout=aiohttp.ClientTimeout(total=120)
                ) as resp:
                    if resp.status != 200:
                        error_text = await resp.text()
                        raise RuntimeError(f"Ollama API error: {error_text}")
                    
                    data = await resp.json()
                    response = data.get("response", "")
                    
                    boxes = []
                    for line in response.strip().split('\n'):
                        if '|' in line:
                            try:
                                parts = line.split('|')
                                text, conf, x, y, w, h = parts[:6]
                                
                                box = OCRBox(
                                    text=text.strip(),
                                    confidence=float(conf),
                                    bbox=(int(x), int(y), int(w), int(h)),
                                    language="unknown"
                                )
                                boxes.append(box)
                            except (ValueError, IndexError):
                                continue
                    
                    return boxes
                    
        except Exception as e:
            self.logger.error(f"Ollama OCR box extraction failed: {e}")
            raise RuntimeError(f"OCR box extraction failed: {e}")


class OCREngine:
    """Main OCR engine with provider selection and fallback."""

    def __init__(self, primary_provider: OCRProvider = OCRProvider.TESSERACT):
        """
        Initialize OCR engine.

        Args:
            primary_provider: Primary OCR provider
        """
        self.logger = logging.getLogger(f"{__name__}.OCREngine")
        self.primary_provider = primary_provider
        
        self.providers = {
            OCRProvider.TESSERACT: TesseractOCR(),
            OCRProvider.PADDLE: PaddleOCR(),
            OCRProvider.OLLAMA: OllamaOCR(),
        }

    async def extract_text(
        self,
        image_bytes: bytes,
        language: Optional[str] = None,
        provider: Optional[OCRProvider] = None
    ) -> str:
        """
        Extract text from image.

        Args:
            image_bytes: Input image bytes
            language: Language code
            provider: Specific provider to use

        Returns:
            Extracted text

        Raises:
            RuntimeError: If all providers fail
        """
        target_provider = provider or self.primary_provider
        
        try:
            if target_provider == OCRProvider.TESSERACT:
                return await self.providers[OCRProvider.TESSERACT].extract_text(
                    image_bytes,
                    language
                )
            elif target_provider == OCRProvider.PADDLE:
                return await self.providers[OCRProvider.PADDLE].extract_text(image_bytes)
            elif target_provider == OCRProvider.OLLAMA:
                return await self.providers[OCRProvider.OLLAMA].extract_text(image_bytes)
            else:
                raise ValueError(f"Unsupported provider: {target_provider}")
                
        except Exception as e:
            self.logger.warning(f"Primary provider {target_provider} failed: {e}")
            
            # Try fallback providers
            for alt_provider in [OCRProvider.PADDLE, OCRProvider.TESSERACT, OCRProvider.OLLAMA]:
                if alt_provider == target_provider:
                    continue
                    
                try:
                    self.logger.info(f"Trying fallback provider: {alt_provider}")
                    if alt_provider == OCRProvider.TESSERACT:
                        return await self.providers[OCRProvider.TESSERACT].extract_text(
                            image_bytes,
                            language
                        )
                    elif alt_provider == OCRProvider.PADDLE:
                        return await self.providers[OCRProvider.PADDLE].extract_text(image_bytes)
                    elif alt_provider == OCRProvider.OLLAMA:
                        return await self.providers[OCRProvider.OLLAMA].extract_text(image_bytes)
                except Exception as e2:
                    self.logger.warning(f"Fallback {alt_provider} failed: {e2}")
            
            raise RuntimeError(f"All OCR providers failed: {e}")

    async def extract_boxes(
        self,
        image_bytes: bytes,
        language: Optional[str] = None,
        provider: Optional[OCRProvider] = None
    ) -> List[OCRBox]:
        """
        Extract text with bounding boxes.

        Args:
            image_bytes: Input image bytes
            language: Language code
            provider: Specific provider to use

        Returns:
            List of OCRBox objects

        Raises:
            RuntimeError: If all providers fail
        """
        target_provider = provider or self.primary_provider
        
        try:
            if target_provider == OCRProvider.TESSERACT:
                return await self.providers[OCRProvider.TESSERACT].extract_boxes(
                    image_bytes,
                    language
                )
            elif target_provider == OCRProvider.PADDLE:
                return await self.providers[OCRProvider.PADDLE].extract_boxes(image_bytes)
            elif target_provider == OCRProvider.OLLAMA:
                return await self.providers[OCRProvider.OLLAMA].extract_boxes(image_bytes)
            else:
                raise ValueError(f"Unsupported provider: {target_provider}")
                
        except Exception as e:
            self.logger.warning(f"Primary provider {target_provider} failed: {e}")
            
            # Try fallbacks
            for alt_provider in [OCRProvider.PADDLE, OCRProvider.TESSERACT, OCRProvider.OLLAMA]:
                if alt_provider == target_provider:
                    continue
                    
                try:
                    if alt_provider == OCRProvider.TESSERACT:
                        return await self.providers[OCRProvider.TESSERACT].extract_boxes(
                            image_bytes,
                            language
                        )
                    elif alt_provider == OCRProvider.PADDLE:
                        return await self.providers[OCRProvider.PADDLE].extract_boxes(image_bytes)
                    elif alt_provider == OCRProvider.OLLAMA:
                        return await self.providers[OCRProvider.OLLAMA].extract_boxes(image_bytes)
                except Exception as e2:
                    self.logger.warning(f"Fallback {alt_provider} failed: {e2}")
            
            raise RuntimeError(f"All OCR providers failed: {e}")

    async def full_analysis(
        self,
        image_bytes: bytes,
        language: Optional[str] = None,
        provider: Optional[OCRProvider] = None
    ) -> OCRResult:
        """
        Perform full OCR analysis.

        Args:
            image_bytes: Input image bytes
            language: Language code
            provider: Specific provider

        Returns:
            OCRResult with full analysis
        """
        import time
        start_time = time.time()
        
        try:
            text = await self.extract_text(image_bytes, language, provider)
            boxes = await self.extract_boxes(image_bytes, language, provider)
            
            # Calculate average confidence
            avg_confidence = (
                sum(b.confidence for b in boxes) / len(boxes)
                if boxes else 0.9
            )
            
            elapsed_ms = (time.time() - start_time) * 1000
            
            return OCRResult(
                text=text,
                confidence=avg_confidence,
                language=language or "auto",
                boxes=boxes,
                processing_time_ms=elapsed_ms,
                provider=str(provider or self.primary_provider)
            )
            
        except Exception as e:
            self.logger.error(f"Full OCR analysis failed: {e}")
            raise RuntimeError(f"OCR analysis failed: {e}")
