"""Unit tests for tool_policy module — classification + confirmation tokens."""
import os, sys, time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "services", "api-gateway"))

from tool_policy import classify_tool, ConfirmationToken, SAFE_READ_TOOLS, GUARDED_WRITE_TOOLS


class TestClassifyTool:
    def test_safe_read(self):
        assert classify_tool("file.read") == "safe_read"

    def test_guarded_write(self):
        assert classify_tool("file.write") == "guarded_write"
        assert classify_tool("shell.run") == "guarded_write"
        assert classify_tool("browser.open") == "guarded_write"

    def test_unknown_defaults_blocked(self):
        assert classify_tool("totally.unknown") == "blocked"

    def test_empty_string_blocked(self):
        assert classify_tool("") == "blocked"

    def test_all_safe_tools_classified(self):
        for tool in SAFE_READ_TOOLS:
            assert classify_tool(tool) == "safe_read"

    def test_all_guarded_tools_classified(self):
        for tool in GUARDED_WRITE_TOOLS:
            assert classify_tool(tool) == "guarded_write"


class TestConfirmationToken:
    def test_initial_state(self):
        t = ConfirmationToken("sess1", "turn1", "file.write", {"path": "/tmp/x"})
        assert t.status == "pending"
        assert t.confirmation_id.startswith("cfm_")
        assert t.session_id == "sess1"
        assert t.tool_name == "file.write"

    def test_summary_includes_tool_and_args(self):
        t = ConfirmationToken("s", "t", "shell.run", {"command": "ls -la"})
        assert "shell.run" in t.summary
        assert "command=" in t.summary

    def test_summary_truncates_long_args(self):
        long_val = "x" * 200
        t = ConfirmationToken("s", "t", "file.write", {"path": long_val})
        # Summary should truncate to 60 chars
        assert len(t.summary) < 200

    def test_expiry_respects_ttl(self):
        t = ConfirmationToken("s", "t", "file.write", {}, ttl_seconds=0.01)
        assert not t.is_expired  # just created
        time.sleep(0.02)
        assert t.is_expired

    def test_remaining_seconds(self):
        t = ConfirmationToken("s", "t", "file.write", {}, ttl_seconds=10.0)
        assert 8.0 < t.remaining_seconds <= 10.0

    def test_to_dict_keys(self):
        t = ConfirmationToken("s", "t", "file.write", {"path": "/x"})
        d = t.to_dict()
        required = {"confirmation_id", "session_id", "turn_id", "tool_name",
                     "args", "summary", "status", "created_at", "remaining_seconds"}
        assert required.issubset(d.keys())

    def test_unique_ids(self):
        t1 = ConfirmationToken("s", "t", "file.write", {})
        t2 = ConfirmationToken("s", "t", "file.write", {})
        assert t1.confirmation_id != t2.confirmation_id
