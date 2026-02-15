"""Unit tests for log_redaction module — pattern-based PII/secret stripping."""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "services", "shared"))

from log_redaction import redact_string, redact_dict


class TestRedactString:
    def test_anthropic_key(self):
        raw = "key=sk-ant-abc123XYZ456def789ghi012"
        assert "[REDACTED:anthropic_key]" in redact_string(raw)
        assert "sk-ant-" not in redact_string(raw)

    def test_openrouter_key(self):
        raw = "Authorization: sk-or-v1-abcdefghij0123456789"
        assert "[REDACTED:openrouter_key]" in redact_string(raw)

    def test_hf_token(self):
        assert "[REDACTED:hf_token]" in redact_string("hf_abcdefghijklmnopqrstuvwx")

    def test_github_token(self):
        assert "[REDACTED:github_token]" in redact_string("ghp_abcdefghijklmnopqrstuvwx")

    def test_slack_token(self):
        assert "[REDACTED:slack_token]" in redact_string("xoxb-123456789012-abcdefgh-abc")

    def test_bearer_token(self):
        raw = "Bearer eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9.payload.sig"
        result = redact_string(raw)
        assert "Bearer [REDACTED]" in result
        assert "eyJ" not in result

    def test_email_address(self):
        assert "[REDACTED:email]" in redact_string("contact user@example.com for info")

    def test_ssn(self):
        assert "[REDACTED:ssn]" in redact_string("SSN: 123-45-6789")

    def test_credit_card(self):
        assert "[REDACTED:cc]" in redact_string("CC 4111-1111-1111-1111")
        assert "[REDACTED:cc]" in redact_string("CC 4111111111111111")

    def test_phone_number(self):
        assert "[REDACTED:phone]" in redact_string("Call 555-867-5309")

    def test_no_false_positive_on_clean(self):
        clean = "This is a normal log message with no secrets."
        assert redact_string(clean) == clean

    def test_non_string_passthrough(self):
        assert redact_string(12345) == 12345  # type: ignore
        assert redact_string(None) is None  # type: ignore


class TestRedactDict:
    def test_sensitive_key_redacted(self):
        data = {"username": "alice", "password": "s3cret", "api_key": "abc"}
        result = redact_dict(data)
        assert result["password"] == "[REDACTED]"
        assert result["api_key"] == "[REDACTED]"
        assert result["username"] == "alice"

    def test_pattern_in_value(self):
        data = {"message": "auth sk-ant-abc123XYZ456def789ghi012 used"}
        result = redact_dict(data)
        assert "sk-ant-" not in result["message"]
        assert "[REDACTED:anthropic_key]" in result["message"]

    def test_nested_dict(self):
        data = {"outer": {"token": "should_be_redacted", "info": "safe"}}
        result = redact_dict(data)
        assert result["outer"]["token"] == "[REDACTED]"
        assert result["outer"]["info"] == "safe"

    def test_list_of_dicts(self):
        data = {"items": [{"secret": "x"}, {"note": "hello user@test.com"}]}
        result = redact_dict(data)
        assert result["items"][0]["secret"] == "[REDACTED]"
        assert "[REDACTED:email]" in result["items"][1]["note"]

    def test_list_of_strings(self):
        data = {"logs": ["normal", "key=sk-ant-abc123XYZ456def789ghi012"]}
        result = redact_dict(data)
        assert result["logs"][0] == "normal"
        assert "[REDACTED:anthropic_key]" in result["logs"][1]

    def test_custom_sensitive_keys(self):
        data = {"my_field": "visible", "danger_zone": "hidden"}
        result = redact_dict(data, sensitive_keys={"danger_zone"})
        assert result["my_field"] == "visible"
        assert result["danger_zone"] == "[REDACTED]"

    def test_non_string_non_dict_values(self):
        data = {"count": 42, "flag": True, "name": "alice"}
        result = redact_dict(data)
        assert result["count"] == 42
        assert result["flag"] is True
