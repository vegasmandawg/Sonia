"""Unit tests for turn_quality module — normalization, fallback, annotations."""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "services", "api-gateway"))

from turn_quality import normalize_response, enforce_non_empty, should_use_fallback, build_annotations
from schemas.vision import ResponsePolicy


class TestNormalizeResponse:
    def test_strips_control_characters(self):
        raw = "hello\x00world\x07test"
        result = normalize_response(raw)
        assert "\x00" not in result
        assert "\x07" not in result
        assert "helloworld" in result

    def test_preserves_tab_newline_cr(self):
        raw = "line1\nline2\ttab\rreturn"
        result = normalize_response(raw)
        assert "\n" in result
        assert "\t" in result

    def test_enforces_max_output_chars(self):
        policy = ResponsePolicy(max_output_chars=10)
        result = normalize_response("a" * 100, policy)
        assert len(result) <= 10

    def test_default_max_is_4000(self):
        result = normalize_response("x" * 5000)
        assert len(result) <= 4000

    def test_strips_whitespace(self):
        assert normalize_response("  hello  ") == "hello"

    def test_empty_string(self):
        assert normalize_response("") == ""

    def test_only_control_chars(self):
        result = normalize_response("\x00\x01\x02")
        assert result == ""


class TestEnforceNonEmpty:
    def test_non_empty_passes_through(self):
        assert enforce_non_empty("hello") == "hello"

    def test_empty_gets_fallback(self):
        result = enforce_non_empty("")
        assert result == "(No response generated)"

    def test_whitespace_only_gets_fallback(self):
        result = enforce_non_empty("   ")
        assert result == "(No response generated)"

    def test_disabled_allows_empty(self):
        policy = ResponsePolicy(disallow_empty_response=False)
        assert enforce_non_empty("", policy) == ""


class TestShouldUseFallback:
    def test_primary_failed_triggers_fallback(self):
        assert should_use_fallback(primary_failed=True) is True

    def test_primary_ok_no_fallback(self):
        assert should_use_fallback(primary_failed=False) is False

    def test_disabled_policy(self):
        policy = ResponsePolicy(fallback_on_model_timeout=False)
        assert should_use_fallback(primary_failed=True, policy=policy) is False


class TestBuildAnnotations:
    def test_defaults(self):
        ann = build_annotations()
        assert ann["generation_profile_used"] == "chat_low_latency"
        assert ann["fallback_used"] is False
        assert ann["tool_calls_attempted"] == 0
        assert ann["tool_calls_executed"] == 0
        assert ann["completion_reason"] == "ok"

    def test_custom_values(self):
        ann = build_annotations(
            profile_used="reasoning",
            fallback_used=True,
            tool_calls_attempted=3,
            tool_calls_executed=2,
            completion_reason="timeout",
        )
        assert ann["generation_profile_used"] == "reasoning"
        assert ann["fallback_used"] is True
        assert ann["tool_calls_attempted"] == 3
        assert ann["completion_reason"] == "timeout"

    def test_returns_dict(self):
        result = build_annotations()
        assert isinstance(result, dict)
