"""
OpenClaw Web Executor
Executes web operations: search and fetch.

web.search — Search the web using DuckDuckGo's instant answer API (no API key needed).
web.fetch  — Fetch and extract text content from a URL.
"""

import time
import json
import re
from typing import Any, Dict, Optional, Tuple, List
from datetime import datetime
from urllib.parse import urlparse, quote_plus

try:
    import httpx
except ImportError:
    httpx = None

# HTML tag stripper for simple text extraction
_HTML_TAG_RE = re.compile(r"<[^>]+>")
_MULTI_SPACE_RE = re.compile(r"\s+")


class WebExecutor:
    """Executes web operations (search, fetch)."""

    DEFAULT_TIMEOUT_MS = 15000
    MAX_TIMEOUT_MS = 30000
    MAX_FETCH_BYTES = 512 * 1024  # 512KB max fetch

    # Blocked domains for fetch
    BLOCKED_DOMAINS = frozenset({
        "localhost", "127.0.0.1", "0.0.0.0",
        "192.168.0.1", "10.0.0.1", "169.254.169.254",
    })

    SAFE_SCHEMES = frozenset({"http", "https"})

    def __init__(self):
        self.execution_log: List[Dict[str, Any]] = []

    # ------------------------------------------------------------------
    # web.search
    # ------------------------------------------------------------------

    def search(
        self,
        query: str,
        max_results: int = 5,
        timeout_ms: Optional[int] = None,
        correlation_id: Optional[str] = None,
    ) -> Tuple[bool, Dict[str, Any], Optional[str]]:
        """
        Search the web using DuckDuckGo instant answer API.

        Args:
            query: Search query string.
            max_results: Maximum number of results to return.
            timeout_ms: Timeout in milliseconds.
            correlation_id: Correlation ID for tracing.

        Returns:
            (success, result_dict, error_message)
        """
        if httpx is None:
            return False, {}, "httpx not installed"

        start = time.time()
        timeout_ms = min(timeout_ms or self.DEFAULT_TIMEOUT_MS, self.MAX_TIMEOUT_MS)
        timeout_s = timeout_ms / 1000.0

        if not query or not query.strip():
            return False, {}, "query is required"

        try:
            # DuckDuckGo instant answer API (no API key)
            url = f"https://api.duckduckgo.com/?q={quote_plus(query)}&format=json&no_html=1&skip_disambig=1"

            with httpx.Client(timeout=timeout_s) as client:
                resp = client.get(url, follow_redirects=True)

            elapsed = (time.time() - start) * 1000

            if resp.status_code != 200:
                self._log("search", query=query, success=False,
                          error=f"HTTP {resp.status_code}", elapsed_ms=elapsed,
                          correlation_id=correlation_id)
                return False, {}, f"Search API returned HTTP {resp.status_code}"

            data = resp.json()
            results = []

            # Abstract (main answer)
            abstract = data.get("AbstractText", "")
            abstract_url = data.get("AbstractURL", "")
            abstract_source = data.get("AbstractSource", "")
            if abstract:
                results.append({
                    "title": abstract_source or "Answer",
                    "snippet": abstract[:500],
                    "url": abstract_url,
                })

            # Related topics
            for topic in data.get("RelatedTopics", [])[:max_results]:
                if isinstance(topic, dict):
                    text = topic.get("Text", "")
                    first_url = topic.get("FirstURL", "")
                    if text:
                        results.append({
                            "title": text[:80],
                            "snippet": text[:300],
                            "url": first_url,
                        })

            # Infobox
            infobox = data.get("Infobox", {})
            if isinstance(infobox, dict):
                for item in infobox.get("content", [])[:3]:
                    if isinstance(item, dict):
                        label = item.get("label", "")
                        value = item.get("value", "")
                        if label and value:
                            results.append({
                                "title": label,
                                "snippet": str(value)[:300],
                                "url": "",
                            })

            results = results[:max_results]

            self._log("search", query=query, success=True,
                      elapsed_ms=elapsed, correlation_id=correlation_id)

            return True, {
                "query": query,
                "results": results,
                "result_count": len(results),
                "elapsed_ms": round(elapsed, 1),
                "source": "duckduckgo",
            }, None

        except Exception as e:
            elapsed = (time.time() - start) * 1000
            self._log("search", query=query, success=False,
                      error=str(e), elapsed_ms=elapsed,
                      correlation_id=correlation_id)
            return False, {}, f"Search failed: {e}"

    # ------------------------------------------------------------------
    # web.fetch
    # ------------------------------------------------------------------

    def fetch(
        self,
        url: str,
        max_chars: int = 5000,
        timeout_ms: Optional[int] = None,
        correlation_id: Optional[str] = None,
    ) -> Tuple[bool, Dict[str, Any], Optional[str]]:
        """
        Fetch a URL and extract text content.

        Args:
            url: URL to fetch.
            max_chars: Maximum characters of text to return.
            timeout_ms: Timeout in milliseconds.
            correlation_id: Correlation ID for tracing.

        Returns:
            (success, result_dict, error_message)
        """
        if httpx is None:
            return False, {}, "httpx not installed"

        start = time.time()
        timeout_ms = min(timeout_ms or self.DEFAULT_TIMEOUT_MS, self.MAX_TIMEOUT_MS)
        timeout_s = timeout_ms / 1000.0

        if not url or not url.strip():
            return False, {}, "url is required"

        # Validate URL
        ok, err = self._validate_url(url)
        if not ok:
            return False, {}, err

        try:
            with httpx.Client(
                timeout=timeout_s,
                follow_redirects=True,
                max_redirects=5,
            ) as client:
                resp = client.get(url, headers={
                    "User-Agent": "SONIA/1.0 (OpenClaw web.fetch)",
                    "Accept": "text/html, text/plain, application/json",
                })

            elapsed = (time.time() - start) * 1000

            if resp.status_code != 200:
                self._log("fetch", url=url, success=False,
                          error=f"HTTP {resp.status_code}", elapsed_ms=elapsed,
                          correlation_id=correlation_id)
                return False, {}, f"Fetch returned HTTP {resp.status_code}"

            content_type = resp.headers.get("content-type", "")
            content_length = len(resp.content)

            if content_length > self.MAX_FETCH_BYTES:
                return False, {}, f"Response too large ({content_length} bytes, max {self.MAX_FETCH_BYTES})"

            # Extract text based on content type
            text = resp.text
            if "html" in content_type:
                text = self._strip_html(text)
            elif "json" in content_type:
                try:
                    parsed = resp.json()
                    text = json.dumps(parsed, indent=2, default=str)
                except Exception:
                    pass  # keep raw text

            # Truncate
            text = text[:max_chars]

            self._log("fetch", url=url, success=True,
                      elapsed_ms=elapsed, correlation_id=correlation_id)

            return True, {
                "url": url,
                "content_type": content_type,
                "text": text,
                "text_length": len(text),
                "original_length": content_length,
                "truncated": content_length > max_chars,
                "elapsed_ms": round(elapsed, 1),
            }, None

        except Exception as e:
            elapsed = (time.time() - start) * 1000
            self._log("fetch", url=url, success=False,
                      error=str(e), elapsed_ms=elapsed,
                      correlation_id=correlation_id)
            return False, {}, f"Fetch failed: {e}"

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _validate_url(self, url: str) -> Tuple[bool, Optional[str]]:
        """Validate URL for safety."""
        try:
            parsed = urlparse(url)
            if parsed.scheme not in self.SAFE_SCHEMES:
                return False, f"Unsafe URL scheme: {parsed.scheme}"
            hostname = parsed.netloc.split(":")[0].lower()
            if hostname in self.BLOCKED_DOMAINS:
                return False, f"Blocked domain: {hostname}"
            if len(url) > 4096:
                return False, "URL too long"
            return True, None
        except Exception as e:
            return False, f"Invalid URL: {e}"

    @staticmethod
    def _strip_html(html: str) -> str:
        """Strip HTML tags and normalize whitespace."""
        # Remove script and style blocks
        text = re.sub(r"<(script|style)[^>]*>.*?</\1>", "", html, flags=re.DOTALL | re.IGNORECASE)
        # Remove tags
        text = _HTML_TAG_RE.sub(" ", text)
        # Normalize whitespace
        text = _MULTI_SPACE_RE.sub(" ", text).strip()
        return text

    def _log(self, operation: str, elapsed_ms: float = 0, success: bool = True,
             error: Optional[str] = None, correlation_id: Optional[str] = None,
             **kwargs):
        entry = {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "operation": operation,
            "success": success,
            "elapsed_ms": round(elapsed_ms, 1),
            "correlation_id": correlation_id,
        }
        entry.update(kwargs)
        if error:
            entry["error"] = error
        self.execution_log.append(entry)

    def get_execution_log(self) -> List[Dict[str, Any]]:
        return self.execution_log.copy()
