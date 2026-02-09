"""
Vision Module

Implements image capture, processing, and vision model integration.
Supports screenshot capture, image preprocessing, and vision API calls.
"""

import asyncio
import base64
import logging
import json
from typing import Optional, Dict, Any, List, Tuple
from pathlib import Path
from datetime import datetime
from enum import Enum
import io

try:
    from PIL import Image
    import numpy as np
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False

logger = logging.getLogger(__name__)


class ImageFormat(str, Enum):
    """Supported image formats."""
    JPEG = "jpeg"
    PNG = "png"
    WEBP = "webp"
    BASE64 = "base64"


class VisionProvider(str, Enum):
    """Supported vision model providers."""
    OLLAMA = "ollama"
    OPENAI = "openai"
    CLAUDE = "claude"
    QWEN = "qwen"


class ScreenCapture:
    """Handles screenshot and image capture from desktop/browser."""

    def __init__(self):
        """Initialize screen capture."""
        self.logger = logging.getLogger(f"{__name__}.ScreenCapture")
        
    async def capture_screenshot(
        self,
        region: Optional[Tuple[int, int, int, int]] = None
    ) -> bytes:
        """
        Capture screenshot from desktop.

        Args:
            region: Optional (left, top, width, height) tuple for partial capture

        Returns:
            PNG image bytes

        Raises:
            RuntimeError: If screenshot capture fails
        """
        try:
            # Try mss (cross-platform, most reliable)
            try:
                import mss
                with mss.mss() as sct:
                    monitor = sct.monitors[1]  # Primary monitor
                    
                    if region:
                        left, top, width, height = region
                        capture_region = {
                            "left": left,
                            "top": top,
                            "width": width,
                            "height": height
                        }
                    else:
                        capture_region = monitor
                    
                    screenshot = sct.grab(capture_region)
                    
                    # Convert to PIL Image and save as PNG
                    if PIL_AVAILABLE:
                        img = Image.frombytes(
                            'RGB',
                            screenshot.size,
                            screenshot.rgb
                        )
                        buffer = io.BytesIO()
                        img.save(buffer, format='PNG')
                        return buffer.getvalue()
                    else:
                        # Fallback: return raw pixel data info
                        self.logger.warning("PIL not available, returning raw screenshot data")
                        raise ImportError("PIL required for image conversion")
                        
            except ImportError:
                # Fallback to PIL ImageGrab (Windows/Mac only)
                if not PIL_AVAILABLE:
                    raise RuntimeError("PIL/Pillow required for screenshot capture")
                
                from PIL import ImageGrab
                img = ImageGrab.grab(bbox=region)
                buffer = io.BytesIO()
                img.save(buffer, format='PNG')
                return buffer.getvalue()
                
        except Exception as e:
            self.logger.error(f"Screenshot capture failed: {e}")
            raise RuntimeError(f"Failed to capture screenshot: {e}")

    async def capture_browser_element(
        self,
        element_selector: str,
        headless_browser_url: str = "http://localhost:3000"
    ) -> bytes:
        """
        Capture specific browser element via Playwright/Puppeteer API.

        Args:
            element_selector: CSS selector for element to capture
            headless_browser_url: URL of headless browser service

        Returns:
            PNG image bytes

        Raises:
            RuntimeError: If element capture fails
        """
        try:
            import aiohttp
            
            async with aiohttp.ClientSession() as session:
                payload = {
                    "selector": element_selector,
                    "format": "png"
                }
                
                async with session.post(
                    f"{headless_browser_url}/screenshot",
                    json=payload,
                    timeout=aiohttp.ClientTimeout(total=30)
                ) as resp:
                    if resp.status != 200:
                        error_text = await resp.text()
                        raise RuntimeError(f"Capture failed: {error_text}")
                    
                    return await resp.read()
                    
        except Exception as e:
            self.logger.error(f"Browser element capture failed: {e}")
            raise RuntimeError(f"Failed to capture browser element: {e}")

    async def capture_from_url(self, url: str) -> bytes:
        """
        Capture screenshot from URL.

        Args:
            url: URL to capture

        Returns:
            PNG image bytes

        Raises:
            RuntimeError: If URL capture fails
        """
        try:
            import aiohttp
            
            async with aiohttp.ClientSession() as session:
                payload = {"url": url}
                
                async with session.post(
                    "http://localhost:3000/screenshot",
                    json=payload,
                    timeout=aiohttp.ClientTimeout(total=30)
                ) as resp:
                    if resp.status != 200:
                        error_text = await resp.text()
                        raise RuntimeError(f"Capture failed: {error_text}")
                    
                    return await resp.read()
                    
        except Exception as e:
            self.logger.error(f"URL screenshot capture failed: {e}")
            raise RuntimeError(f"Failed to capture from URL: {e}")


class ImageProcessor:
    """Handles image preprocessing and optimization."""

    def __init__(self):
        """Initialize image processor."""
        self.logger = logging.getLogger(f"{__name__}.ImageProcessor")
        if not PIL_AVAILABLE:
            self.logger.warning("PIL not available; image processing limited")

    async def resize_image(
        self,
        image_bytes: bytes,
        max_width: int = 1920,
        max_height: int = 1080,
        maintain_aspect: bool = True
    ) -> bytes:
        """
        Resize image to fit constraints.

        Args:
            image_bytes: Input image bytes
            max_width: Maximum width in pixels
            max_height: Maximum height in pixels
            maintain_aspect: Keep aspect ratio if True

        Returns:
            Resized image bytes (PNG format)
        """
        if not PIL_AVAILABLE:
            self.logger.warning("PIL not available, returning original image")
            return image_bytes
            
        try:
            img = Image.open(io.BytesIO(image_bytes))
            
            if maintain_aspect:
                img.thumbnail((max_width, max_height), Image.Resampling.LANCZOS)
            else:
                img = img.resize((max_width, max_height), Image.Resampling.LANCZOS)
            
            buffer = io.BytesIO()
            img.save(buffer, format='PNG')
            return buffer.getvalue()
            
        except Exception as e:
            self.logger.error(f"Image resize failed: {e}")
            raise RuntimeError(f"Failed to resize image: {e}")

    async def compress_image(
        self,
        image_bytes: bytes,
        quality: int = 85,
        format: ImageFormat = ImageFormat.JPEG
    ) -> bytes:
        """
        Compress image to reduce size.

        Args:
            image_bytes: Input image bytes
            quality: JPEG quality (1-100, default 85)
            format: Output format

        Returns:
            Compressed image bytes
        """
        if not PIL_AVAILABLE:
            self.logger.warning("PIL not available, returning original image")
            return image_bytes
            
        try:
            img = Image.open(io.BytesIO(image_bytes))
            
            # Convert RGBA to RGB if needed for JPEG
            if format == ImageFormat.JPEG and img.mode in ('RGBA', 'LA', 'P'):
                background = Image.new('RGB', img.size, (255, 255, 255))
                background.paste(img, mask=img.split()[-1] if img.mode == 'RGBA' else None)
                img = background
            
            buffer = io.BytesIO()
            save_kwargs = {'format': format.value.upper()}
            
            if format == ImageFormat.JPEG:
                save_kwargs['quality'] = quality
            elif format == ImageFormat.WEBP:
                save_kwargs['quality'] = quality
            
            img.save(buffer, **save_kwargs)
            return buffer.getvalue()
            
        except Exception as e:
            self.logger.error(f"Image compression failed: {e}")
            raise RuntimeError(f"Failed to compress image: {e}")

    async def crop_image(
        self,
        image_bytes: bytes,
        region: Tuple[int, int, int, int]
    ) -> bytes:
        """
        Crop image to specified region.

        Args:
            image_bytes: Input image bytes
            region: (left, top, right, bottom) tuple

        Returns:
            Cropped image bytes
        """
        if not PIL_AVAILABLE:
            self.logger.warning("PIL not available, cannot crop image")
            return image_bytes
            
        try:
            img = Image.open(io.BytesIO(image_bytes))
            cropped = img.crop(region)
            
            buffer = io.BytesIO()
            cropped.save(buffer, format='PNG')
            return buffer.getvalue()
            
        except Exception as e:
            self.logger.error(f"Image crop failed: {e}")
            raise RuntimeError(f"Failed to crop image: {e}")

    async def get_image_metadata(self, image_bytes: bytes) -> Dict[str, Any]:
        """
        Extract image metadata.

        Args:
            image_bytes: Input image bytes

        Returns:
            Dictionary with image metadata
        """
        if not PIL_AVAILABLE:
            return {
                "error": "PIL not available",
                "size_bytes": len(image_bytes)
            }
            
        try:
            img = Image.open(io.BytesIO(image_bytes))
            
            metadata = {
                "width": img.width,
                "height": img.height,
                "format": img.format,
                "mode": img.mode,
                "size_bytes": len(image_bytes),
                "aspect_ratio": img.width / img.height if img.height > 0 else 0
            }
            
            # Add EXIF data if available
            if hasattr(img, '_getexif') and img._getexif():
                metadata["has_exif"] = True
            
            return metadata
            
        except Exception as e:
            self.logger.error(f"Metadata extraction failed: {e}")
            return {
                "error": str(e),
                "size_bytes": len(image_bytes)
            }

    async def convert_format(
        self,
        image_bytes: bytes,
        target_format: ImageFormat = ImageFormat.PNG
    ) -> bytes:
        """
        Convert image to different format.

        Args:
            image_bytes: Input image bytes
            target_format: Target format

        Returns:
            Converted image bytes
        """
        if not PIL_AVAILABLE:
            self.logger.warning("PIL not available, returning original image")
            return image_bytes
            
        try:
            img = Image.open(io.BytesIO(image_bytes))
            
            # Handle format-specific conversions
            if target_format == ImageFormat.JPEG:
                if img.mode in ('RGBA', 'LA', 'P'):
                    background = Image.new('RGB', img.size, (255, 255, 255))
                    background.paste(img, mask=img.split()[-1] if img.mode == 'RGBA' else None)
                    img = background
            
            buffer = io.BytesIO()
            img.save(buffer, format=target_format.value.upper())
            return buffer.getvalue()
            
        except Exception as e:
            self.logger.error(f"Format conversion failed: {e}")
            raise RuntimeError(f"Failed to convert image format: {e}")


class VisionClient:
    """Client for vision model API calls."""

    def __init__(
        self,
        provider: VisionProvider = VisionProvider.OLLAMA,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None
    ):
        """
        Initialize vision client.

        Args:
            provider: Vision provider
            api_key: API key for cloud providers
            base_url: Base URL for service (default based on provider)
        """
        self.provider = provider
        self.api_key = api_key
        self.base_url = base_url or self._get_default_url()
        self.logger = logging.getLogger(f"{__name__}.VisionClient")

    def _get_default_url(self) -> str:
        """Get default URL for provider."""
        defaults = {
            VisionProvider.OLLAMA: "http://localhost:11434",
            VisionProvider.QWEN: "http://localhost:8000",
            VisionProvider.OPENAI: "https://api.openai.com/v1",
            VisionProvider.CLAUDE: "https://api.anthropic.com/v1"
        }
        return defaults.get(self.provider, "http://localhost:11434")

    async def analyze_image(
        self,
        image_bytes: bytes,
        prompt: str,
        model: Optional[str] = None,
        max_tokens: int = 1024,
        temperature: float = 0.7
    ) -> str:
        """
        Analyze image with vision model.

        Args:
            image_bytes: Image bytes to analyze
            prompt: Analysis prompt
            model: Model name (provider-specific)
            max_tokens: Max response tokens
            temperature: Response temperature (0.0-1.0)

        Returns:
            Analysis text response

        Raises:
            RuntimeError: If analysis fails
        """
        image_b64 = base64.b64encode(image_bytes).decode('utf-8')
        
        if self.provider == VisionProvider.OLLAMA:
            return await self._ollama_vision(image_b64, prompt, model, max_tokens, temperature)
        elif self.provider == VisionProvider.OPENAI:
            return await self._openai_vision(image_b64, prompt, model, max_tokens, temperature)
        elif self.provider == VisionProvider.CLAUDE:
            return await self._claude_vision(image_b64, prompt, model, max_tokens, temperature)
        elif self.provider == VisionProvider.QWEN:
            return await self._qwen_vision(image_b64, prompt, model, max_tokens, temperature)
        else:
            raise ValueError(f"Unsupported provider: {self.provider}")

    async def _ollama_vision(
        self,
        image_b64: str,
        prompt: str,
        model: Optional[str],
        max_tokens: int,
        temperature: float
    ) -> str:
        """Ollama vision API call."""
        try:
            import aiohttp
            
            model = model or "llava"
            
            async with aiohttp.ClientSession() as session:
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
                    return data.get("response", "")
                    
        except Exception as e:
            self.logger.error(f"Ollama vision analysis failed: {e}")
            raise RuntimeError(f"Vision analysis failed: {e}")

    async def _openai_vision(
        self,
        image_b64: str,
        prompt: str,
        model: Optional[str],
        max_tokens: int,
        temperature: float
    ) -> str:
        """OpenAI vision API call."""
        try:
            import aiohttp
            
            if not self.api_key:
                raise ValueError("API key required for OpenAI")
            
            model = model or "gpt-4-vision-preview"
            
            async with aiohttp.ClientSession() as session:
                headers = {
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json"
                }
                
                payload = {
                    "model": model,
                    "messages": [
                        {
                            "role": "user",
                            "content": [
                                {
                                    "type": "image_url",
                                    "image_url": {
                                        "url": f"data:image/png;base64,{image_b64}"
                                    }
                                },
                                {
                                    "type": "text",
                                    "text": prompt
                                }
                            ]
                        }
                    ],
                    "max_tokens": max_tokens,
                    "temperature": temperature
                }
                
                async with session.post(
                    f"{self.base_url}/chat/completions",
                    json=payload,
                    headers=headers,
                    timeout=aiohttp.ClientTimeout(total=120)
                ) as resp:
                    if resp.status != 200:
                        error_text = await resp.text()
                        raise RuntimeError(f"OpenAI API error: {error_text}")
                    
                    data = await resp.json()
                    return data["choices"][0]["message"]["content"]
                    
        except Exception as e:
            self.logger.error(f"OpenAI vision analysis failed: {e}")
            raise RuntimeError(f"Vision analysis failed: {e}")

    async def _claude_vision(
        self,
        image_b64: str,
        prompt: str,
        model: Optional[str],
        max_tokens: int,
        temperature: float
    ) -> str:
        """Claude vision API call (requires Claude API)."""
        try:
            import aiohttp
            
            if not self.api_key:
                raise ValueError("API key required for Claude")
            
            model = model or "claude-3-vision-20240229"
            
            async with aiohttp.ClientSession() as session:
                headers = {
                    "x-api-key": self.api_key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json"
                }
                
                payload = {
                    "model": model,
                    "max_tokens": max_tokens,
                    "messages": [
                        {
                            "role": "user",
                            "content": [
                                {
                                    "type": "image",
                                    "source": {
                                        "type": "base64",
                                        "media_type": "image/png",
                                        "data": image_b64
                                    }
                                },
                                {
                                    "type": "text",
                                    "text": prompt
                                }
                            ]
                        }
                    ]
                }
                
                async with session.post(
                    f"{self.base_url}/messages",
                    json=payload,
                    headers=headers,
                    timeout=aiohttp.ClientTimeout(total=120)
                ) as resp:
                    if resp.status != 200:
                        error_text = await resp.text()
                        raise RuntimeError(f"Claude API error: {error_text}")
                    
                    data = await resp.json()
                    return data["content"][0]["text"]
                    
        except Exception as e:
            self.logger.error(f"Claude vision analysis failed: {e}")
            raise RuntimeError(f"Vision analysis failed: {e}")

    async def _qwen_vision(
        self,
        image_b64: str,
        prompt: str,
        model: Optional[str],
        max_tokens: int,
        temperature: float
    ) -> str:
        """Qwen vision API call."""
        try:
            import aiohttp
            
            model = model or "qwen-vl-max"
            
            async with aiohttp.ClientSession() as session:
                payload = {
                    "model": model,
                    "messages": [
                        {
                            "role": "user",
                            "content": [
                                {
                                    "type": "image",
                                    "image": f"data:image/png;base64,{image_b64}"
                                },
                                {
                                    "type": "text",
                                    "text": prompt
                                }
                            ]
                        }
                    ],
                    "max_tokens": max_tokens,
                    "temperature": temperature
                }
                
                async with session.post(
                    f"{self.base_url}/chat/completions",
                    json=payload,
                    timeout=aiohttp.ClientTimeout(total=120)
                ) as resp:
                    if resp.status != 200:
                        error_text = await resp.text()
                        raise RuntimeError(f"Qwen API error: {error_text}")
                    
                    data = await resp.json()
                    return data["choices"][0]["message"]["content"]
                    
        except Exception as e:
            self.logger.error(f"Qwen vision analysis failed: {e}")
            raise RuntimeError(f"Vision analysis failed: {e}")

    async def batch_analyze(
        self,
        image_list: List[Tuple[bytes, str]],
        model: Optional[str] = None,
        max_tokens: int = 1024,
        temperature: float = 0.7
    ) -> List[str]:
        """
        Analyze multiple images concurrently.

        Args:
            image_list: List of (image_bytes, prompt) tuples
            model: Model name
            max_tokens: Max response tokens
            temperature: Response temperature

        Returns:
            List of analysis results
        """
        tasks = [
            self.analyze_image(img_bytes, prompt, model, max_tokens, temperature)
            for img_bytes, prompt in image_list
        ]
        
        results = []
        for task in asyncio.as_completed(tasks):
            try:
                result = await task
                results.append(result)
            except Exception as e:
                self.logger.error(f"Batch analysis task failed: {e}")
                results.append(f"Error: {str(e)}")
        
        return results
