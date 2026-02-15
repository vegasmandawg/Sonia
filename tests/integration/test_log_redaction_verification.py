#!/usr/bin/env python3
"""
Log redaction verification integration test.

Tests that the log_redaction module properly redacts PII across all pattern types.
Outputs JSON verification report for audit trail.
"""

import sys
import json
from pathlib import Path
from datetime import datetime

# Add shared to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent / 'services' / 'shared'))

import pytest
from log_redaction import redact_string, redact_dict


# Test corpus with various PII types
TEST_CORPUS = {
    'email': [
        ('Contact john.doe@example.com for details', 'john.doe@example.com'),
        ('Email: alice_smith123@company.co.uk', 'alice_smith123@company.co.uk'),
        ('support+filter@startup.io replied', 'support+filter@startup.io'),
    ],
    'ssn': [
        ('SSN: 123-45-6789 on file', '123-45-6789'),
        ('Social security 987-65-4321', '987-65-4321'),
        ('ID 555-12-3456 verified', '555-12-3456'),
    ],
    'credit_card': [
        ('Card 4532-1234-5678-9010 charged', '4532-1234-5678-9010'),
        ('Visa: 4111111111111111', '4111111111111111'),
        ('Payment via 5500-0000-0000-0004', '5500-0000-0000-0004'),
    ],
    'phone': [
        ('Call +1-555-123-4567 now', '+1-555-123-4567'),
        ('Office: (555) 987-6543', '(555) 987-6543'),
        ('Mobile 555.111.2222', '555.111.2222'),
    ],
    'api_key': [
        ('Key: sk-ant-api03-AbCdEfGhIjKlMnOpQrStUvWxYz1234567890', 'sk-ant-api03-AbCdEfGhIjKlMnOpQrStUvWxYz1234567890'),
        ('Token sk-or-v1-1234567890abcdef1234567890abcdef1234567890abcdef1234567890abcd', 'sk-or-v1-1234567890abcdef1234567890abcdef1234567890abcdef1234567890abcd'),
    ],
    'bearer_token': [
        ('Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9', 'Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9'),
        ('Token: Bearer abc123def456ghi789jkl012mno345', 'Bearer abc123def456ghi789jkl012mno345'),
    ],
    'ip_address': [
        ('Server IP: 192.168.1.100', '192.168.1.100'),
        ('Connected from 10.0.0.5', '10.0.0.5'),
        ('IPv6: 2001:0db8:85a3:0000:0000:8a2e:0370:7334', '2001:0db8:85a3:0000:0000:8a2e:0370:7334'),
    ],
}

# Non-sensitive strings that should pass through unchanged
SAFE_STRINGS = [
    'This is a normal log message',
    'Processing request 12345',
    'Status: healthy',
    'User clicked button',
    'Error in module xyz',
]


@pytest.fixture(scope='module')
def verification_report():
    """Fixture to collect verification results for JSON report."""
    report_data = {
        'timestamp': datetime.utcnow().isoformat(),
        'test_suite': 'log_redaction_verification',
        'results': [],
    }
    yield report_data

    # Write report after all tests complete
    report_path = Path('S:/reports/audit/redaction-verification-{}.json'.format(
        datetime.now().strftime('%Y%m%d-%H%M%S')
    ))
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report_data, indent=2), encoding='utf-8')
    print(f"\nVerification report: {report_path}")


def test_redact_emails(verification_report):
    """Verify email addresses are properly redacted."""
    for text, expected_pii in TEST_CORPUS['email']:
        redacted = redact_string(text)
        assert expected_pii not in redacted, f"Email not redacted: {text}"
        assert '[REDACTED:email]' in redacted, f"Missing redaction marker in: {redacted}"
        verification_report['results'].append({
            'pattern': 'email',
            'input': text,
            'output': redacted,
            'passed': expected_pii not in redacted,
        })


def test_redact_ssn(verification_report):
    """Verify SSNs are properly redacted."""
    for text, expected_pii in TEST_CORPUS['ssn']:
        redacted = redact_string(text)
        assert expected_pii not in redacted, f"SSN not redacted: {text}"
        assert '[REDACTED:ssn]' in redacted, f"Missing redaction marker in: {redacted}"
        verification_report['results'].append({
            'pattern': 'ssn',
            'input': text,
            'output': redacted,
            'passed': expected_pii not in redacted,
        })


def test_redact_credit_cards(verification_report):
    """Verify credit card numbers are properly redacted."""
    for text, expected_pii in TEST_CORPUS['credit_card']:
        redacted = redact_string(text)
        # Remove hyphens for comparison since redaction might normalize
        normalized_pii = expected_pii.replace('-', '')
        assert normalized_pii not in redacted.replace('-', ''), f"CC not redacted: {text}"
        assert '[REDACTED:cc]' in redacted, f"Missing redaction marker in: {redacted}"
        verification_report['results'].append({
            'pattern': 'credit_card',
            'input': text,
            'output': redacted,
            'passed': normalized_pii not in redacted.replace('-', ''),
        })


def test_redact_phone_numbers(verification_report):
    """Verify phone numbers are properly redacted."""
    for text, expected_pii in TEST_CORPUS['phone']:
        redacted = redact_string(text)
        # Phone patterns can vary, check that digits are redacted
        digit_sequence = ''.join(c for c in expected_pii if c.isdigit())
        assert digit_sequence not in redacted.replace('-', '').replace('(', '').replace(')', '').replace('.', '').replace(' ', ''), \
            f"Phone not redacted: {text}"
        verification_report['results'].append({
            'pattern': 'phone',
            'input': text,
            'output': redacted,
            'passed': True,
        })


def test_redact_api_keys(verification_report):
    """Verify API keys are properly redacted."""
    for text, expected_pii in TEST_CORPUS['api_key']:
        redacted = redact_string(text)
        assert expected_pii not in redacted, f"API key not redacted: {text}"
        assert '[REDACTED_API_KEY]' in redacted or '[REDACTED' in redacted, \
            f"Missing redaction marker in: {redacted}"
        verification_report['results'].append({
            'pattern': 'api_key',
            'input': text,
            'output': redacted,
            'passed': expected_pii not in redacted,
        })


def test_redact_bearer_tokens(verification_report):
    """Verify Bearer tokens are properly redacted."""
    for text, expected_pii in TEST_CORPUS['bearer_token']:
        redacted = redact_string(text)
        # Check that the Bearer token value is redacted
        token_value = expected_pii.split(' ', 1)[1] if ' ' in expected_pii else expected_pii
        assert token_value not in redacted, f"Bearer token not redacted: {text}"
        verification_report['results'].append({
            'pattern': 'bearer_token',
            'input': text,
            'output': redacted,
            'passed': token_value not in redacted,
        })


def test_ip_addresses_not_redacted(verification_report):
    """Verify IP addresses pass through (intentionally not redacted for debugging)."""
    for text, expected_ip in TEST_CORPUS['ip_address']:
        redacted = redact_string(text)
        assert expected_ip in redacted, f"IP should NOT be redacted: {text}"
        verification_report['results'].append({
            'pattern': 'ip_address',
            'input': text,
            'output': redacted,
            'passed': True,
            'note': 'IP addresses intentionally not redacted for operational debugging',
        })


def test_safe_strings_unchanged(verification_report):
    """Verify non-sensitive strings pass through unchanged."""
    for text in SAFE_STRINGS:
        redacted = redact_string(text)
        assert redacted == text, f"Safe string was modified: {text} -> {redacted}"
        verification_report['results'].append({
            'pattern': 'safe_string',
            'input': text,
            'output': redacted,
            'passed': redacted == text,
        })


def test_redact_dict_nested(verification_report):
    """Verify redact_dict handles nested dictionaries."""
    test_dict = {
        'user': 'john.doe@example.com',
        'metadata': {
            'ssn': '123-45-6789',
            'phone': '555-123-4567',
        },
        'safe_field': 'normal data',
    }

    redacted = redact_dict(test_dict)

    # Check email redacted
    assert 'john.doe@example.com' not in str(redacted), "Email in dict not redacted"
    # Check SSN redacted
    assert '123-45-6789' not in str(redacted), "SSN in nested dict not redacted"
    # Check safe field unchanged
    assert redacted.get('safe_field') == 'normal data', "Safe field was modified"

    verification_report['results'].append({
        'pattern': 'nested_dict',
        'input': str(test_dict),
        'output': str(redacted),
        'passed': '123-45-6789' not in str(redacted),
    })


def test_redact_dict_sensitive_keys(verification_report):
    """Verify redact_dict redacts values for sensitive keys."""
    test_dict = {
        'password': 'secret123',
        'api_key': 'my-api-key-value',
        'token': 'auth-token-xyz',
        'normal_key': 'safe value',
    }

    redacted = redact_dict(test_dict)

    # Sensitive keys should have redacted values
    assert redacted.get('password') != 'secret123', "Password value not redacted"
    assert redacted.get('api_key') != 'my-api-key-value', "API key value not redacted"
    assert redacted.get('token') != 'auth-token-xyz', "Token value not redacted"

    # Normal key should be unchanged
    assert redacted.get('normal_key') == 'safe value', "Normal key was modified"

    verification_report['results'].append({
        'pattern': 'sensitive_keys',
        'input': str(test_dict),
        'output': str(redacted),
        'passed': redacted.get('password') != 'secret123',
    })


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
