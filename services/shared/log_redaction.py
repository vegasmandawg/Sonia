"""Log redaction utilities for sensitive data.

Used across all SONIA services to prevent PII and secrets from appearing in logs.
"""

import re
from typing import Any, Dict


# Patterns for sensitive data
_REDACTION_PATTERNS = [
    # API keys
    (re.compile(r'sk-ant-[a-zA-Z0-9_-]{20,}'), '[REDACTED:anthropic_key]'),
    (re.compile(r'sk-or-v1-[a-zA-Z0-9]{20,}'), '[REDACTED:openrouter_key]'),
    (re.compile(r'hf_[a-zA-Z0-9]{20,}'), '[REDACTED:hf_token]'),
    (re.compile(r'ghp_[a-zA-Z0-9]{20,}'), '[REDACTED:github_token]'),
    (re.compile(r'xoxb-[a-zA-Z0-9-]{20,}'), '[REDACTED:slack_token]'),
    # Generic bearer tokens
    (re.compile(r'Bearer\s+[a-zA-Z0-9._-]{20,}'), 'Bearer [REDACTED]'),
    # Email addresses
    (re.compile(r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}'), '[REDACTED:email]'),
    # SSN
    (re.compile(r'\b\d{3}-\d{2}-\d{4}\b'), '[REDACTED:ssn]'),
    # Credit card numbers (basic)
    (re.compile(r'\b\d{4}[- ]?\d{4}[- ]?\d{4}[- ]?\d{4}\b'), '[REDACTED:cc]'),
    # Phone numbers (US format)
    (re.compile(r'\b(?:\+1)?[\s.-]?\(?\d{3}\)?[\s.-]?\d{3}[\s.-]?\d{4}\b'), '[REDACTED:phone]'),
]


def redact_string(text: str) -> str:
    """Redact sensitive patterns from a string."""
    if not isinstance(text, str):
        return text
    result = text
    for pattern, replacement in _REDACTION_PATTERNS:
        result = pattern.sub(replacement, result)
    return result


def redact_dict(data: Dict[str, Any], sensitive_keys: set = None) -> Dict[str, Any]:
    """Redact sensitive values from a dictionary.

    Args:
        data: Dictionary to redact
        sensitive_keys: Set of key names whose values should be fully redacted
    """
    if sensitive_keys is None:
        sensitive_keys = {
            "password", "secret", "token", "api_key", "apikey",
            "authorization", "cookie", "session_token",
            "private_key", "access_key", "secret_key",
        }

    result = {}
    for key, value in data.items():
        key_lower = key.lower()
        if any(sk in key_lower for sk in sensitive_keys):
            result[key] = "[REDACTED]"
        elif isinstance(value, str):
            result[key] = redact_string(value)
        elif isinstance(value, dict):
            result[key] = redact_dict(value, sensitive_keys)
        elif isinstance(value, list):
            result[key] = [
                redact_dict(item, sensitive_keys) if isinstance(item, dict)
                else redact_string(item) if isinstance(item, str)
                else item
                for item in value
            ]
        else:
            result[key] = value
    return result
