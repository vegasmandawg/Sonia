"""Client for generating embeddings via Ollama or local LLM."""

import asyncio
import json
import logging
import hashlib
import math
from typing import List, Optional
import httpx

logger = logging.getLogger(__name__)


class EmbeddingsClient:
    """Client for generating text embeddings via Ollama or OpenAI-compatible API."""

    def __init__(
        self,
        provider: str = "ollama",
        base_url: str = "http://127.0.0.1:11434",
        model: str = "nomic-embed-text",
        embedding_dim: int = 1536,
        timeout: float = 30.0,
    ):
        """
        Initialize embeddings client.

        Args:
            provider: "ollama" or "openai-compatible"
            base_url: API endpoint (default Ollama local)
            model: Model name (default nomic-embed-text for Ollama)
            embedding_dim: Expected embedding dimension
            timeout: Request timeout in seconds
        """
        self.provider = provider
        self.base_url = base_url
        self.model = model
        self.embedding_dim = embedding_dim
        self.timeout = timeout
        self.client = None
        self._initialized = False
        self._degraded = False
        self._degraded_reason = ""

    async def initialize(self) -> None:
        """Initialize HTTP client and verify connectivity."""
        try:
            self.client = httpx.AsyncClient(timeout=self.timeout)
            
            # Verify connectivity
            if self.provider == "ollama":
                response = await self.client.get(f"{self.base_url}/api/tags")
                if response.status_code == 200:
                    logger.info(f"Connected to Ollama at {self.base_url}")
                    self._initialized = True
                else:
                    logger.warning(
                        f"Ollama returned {response.status_code}, "
                        "will retry on first use"
                    )
            else:
                logger.info(f"Using {self.provider} embeddings at {self.base_url}")
                self._initialized = True
                
        except Exception as e:
            logger.warning(f"Embeddings client init: {e}, will use fallback")
            self._initialized = False

    async def embed(self, text: str) -> List[float]:
        """
        Generate embedding for a single text.

        Args:
            text: Text to embed

        Returns:
            List of floats (embedding vector)
        """
        if not text or not isinstance(text, str):
            logger.warning("Invalid text input for embedding")
            return self._fallback_embedding(text="", reason="invalid_input")

        try:
            if self.provider == "ollama":
                return await self._embed_ollama(text)
            elif self.provider == "openai-compatible":
                return await self._embed_openai(text)
            else:
                logger.error(f"Unknown provider: {self.provider}")
                return self._fallback_embedding(
                    text=text,
                    reason=f"unknown_provider:{self.provider}",
                )

        except Exception as e:
            logger.error(f"Embedding generation failed: {e}")
            return self._fallback_embedding(text=text, reason=str(e))

    async def _embed_ollama(self, text: str) -> List[float]:
        """Generate embedding via Ollama API."""
        if not self.client:
            self.client = httpx.AsyncClient(timeout=self.timeout)

        payload = {
            "model": self.model,
            "prompt": text,
        }

        try:
            response = await self.client.post(
                f"{self.base_url}/api/embed",
                json=payload,
            )
            
            if response.status_code == 200:
                data = response.json()
                embedding = data.get("embedding", [])
                
                if len(embedding) != self.embedding_dim:
                    logger.warning(
                        f"Expected {self.embedding_dim} dims, "
                        f"got {len(embedding)}"
                    )
                self._degraded = False
                self._degraded_reason = ""
                return embedding
            else:
                logger.error(
                    f"Ollama embed failed: {response.status_code} "
                    f"{response.text}"
                )
                return self._fallback_embedding(
                    text=text,
                    reason=f"ollama_status_{response.status_code}",
                )

        except asyncio.TimeoutError:
            logger.error("Ollama embedding request timeout")
            return self._fallback_embedding(text=text, reason="ollama_timeout")
        except Exception as e:
            logger.error(f"Ollama embedding error: {e}")
            return self._fallback_embedding(text=text, reason=str(e))

    async def _embed_openai(self, text: str) -> List[float]:
        """Generate embedding via OpenAI-compatible API."""
        if not self.client:
            self.client = httpx.AsyncClient(timeout=self.timeout)

        payload = {
            "model": self.model,
            "input": text,
        }

        try:
            response = await self.client.post(
                f"{self.base_url}/v1/embeddings",
                json=payload,
                headers={"Content-Type": "application/json"},
            )
            
            if response.status_code == 200:
                data = response.json()
                if "data" in data and len(data["data"]) > 0:
                    embedding = data["data"][0].get("embedding", [])
                    self._degraded = False
                    self._degraded_reason = ""
                    return embedding
                else:
                    logger.error("No embedding in OpenAI response")
                    return self._fallback_embedding(
                        text=text,
                        reason="openai_empty_payload",
                    )
            else:
                logger.error(
                    f"OpenAI embed failed: {response.status_code} "
                    f"{response.text}"
                )
                return self._fallback_embedding(
                    text=text,
                    reason=f"openai_status_{response.status_code}",
                )

        except Exception as e:
            logger.error(f"OpenAI embedding error: {e}")
            return self._fallback_embedding(text=text, reason=str(e))

    async def embed_batch(
        self, texts: List[str], batch_size: int = 32
    ) -> List[List[float]]:
        """
        Generate embeddings for batch of texts.

        Args:
            texts: List of texts to embed
            batch_size: Process in batches to avoid overload

        Returns:
            List of embedding vectors
        """
        embeddings = []
        
        for i in range(0, len(texts), batch_size):
            batch = texts[i : i + batch_size]
            
            # Process batch concurrently
            tasks = [self.embed(text) for text in batch]
            batch_embeddings = await asyncio.gather(*tasks)
            embeddings.extend(batch_embeddings)
            
            logger.debug(
                f"Processed batch {i // batch_size + 1}: "
                f"{len(batch)} texts"
            )

        logger.info(f"Generated embeddings for {len(embeddings)} texts")
        return embeddings

    def _fallback_embedding(self, text: str, reason: str) -> List[float]:
        """
        Return deterministic hash embedding when remote provider is unavailable.

        The fallback status is recorded so retrieval callers can surface
        degraded quality through logs/response metadata.
        """
        self._degraded = True
        self._degraded_reason = reason
        logger.warning(
            "Embedding fallback active (reason=%s). Returning deterministic hash vector.",
            reason,
        )

        seed = text if text else "_empty_"
        digest = hashlib.sha256(seed.encode("utf-8", errors="ignore")).digest()
        values: List[float] = []
        while len(values) < self.embedding_dim:
            for b in digest:
                # Map byte to [-1.0, 1.0]
                values.append((b / 127.5) - 1.0)
                if len(values) >= self.embedding_dim:
                    break
            digest = hashlib.sha256(digest + seed.encode("utf-8", errors="ignore")).digest()

        # Normalize so distance behavior is stable.
        norm = math.sqrt(sum(v * v for v in values)) or 1.0
        return [v / norm for v in values]

    async def shutdown(self) -> None:
        """Shutdown HTTP client."""
        if self.client:
            await self.client.aclose()
            logger.info("Embeddings client shutdown")

    async def health_check(self) -> bool:
        """Check if embeddings service is available."""
        try:
            if self.provider == "ollama":
                if not self.client:
                    self.client = httpx.AsyncClient(timeout=self.timeout)
                response = await self.client.get(
                    f"{self.base_url}/api/tags",
                    timeout=5.0,
                )
                return response.status_code == 200
            return self._initialized
        except Exception as e:
            logger.debug(f"Embeddings health check failed: {e}")
            return False

    def status(self) -> dict:
        """Expose current embedding quality state for diagnostics."""
        return {
            "provider": self.provider,
            "model": self.model,
            "degraded": self._degraded,
            "degraded_reason": self._degraded_reason or None,
        }
