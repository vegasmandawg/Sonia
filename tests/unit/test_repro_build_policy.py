"""Tests for repro_build_policy — frozen deps, lock hashes."""
import sys
sys.path.insert(0, r"S:\services\api-gateway")

import pytest
from repro_build_policy import (
    DependencyEntry, FrozenDependencySet, parse_requirements_line,
)


def _dep(name="fastapi", ver="0.115.0", spec="==0.115.0"):
    return DependencyEntry(name, ver, spec, "sha256hash")


class TestPinning:
    def test_fully_pinned(self):
        d = _dep(spec="==1.2.3")
        assert d.is_fully_pinned()

    def test_floating_range_not_pinned(self):
        d = _dep(spec=">=1.2.0")
        assert not d.is_fully_pinned()

    def test_tilde_not_pinned(self):
        d = _dep(spec="~=1.2.0")
        assert not d.is_fully_pinned()

    def test_unpinned_detected(self):
        fds = FrozenDependencySet()
        fds.add(_dep("fastapi", spec="==1.0.0"))
        fds.add(_dep("uvicorn", spec=">=0.30"))
        assert not fds.all_pinned()
        assert "uvicorn" in fds.unpinned_deps()


class TestLockHash:
    def test_hash_deterministic(self):
        fds = FrozenDependencySet()
        fds.add(_dep("fastapi"))
        fds.add(_dep("uvicorn", "0.30.0", "==0.30.0"))
        h1 = fds.compute_lock_hash()
        h2 = fds.compute_lock_hash()
        assert h1 == h2 and len(h1) == 64

    def test_verify_correct_hash(self):
        fds = FrozenDependencySet()
        fds.add(_dep("fastapi"))
        h = fds.compute_lock_hash()
        assert fds.verify_lock_hash(h)

    def test_verify_wrong_hash_fails(self):
        fds = FrozenDependencySet()
        fds.add(_dep("fastapi"))
        assert not fds.verify_lock_hash("wronghash")

    def test_export_lock(self):
        fds = FrozenDependencySet()
        fds.add(_dep("fastapi"))
        export = fds.export_lock()
        assert export["dep_count"] == 1
        assert export["all_pinned"] is True


class TestParse:
    def test_parse_pinned_line(self):
        d = parse_requirements_line("fastapi==0.115.0")
        assert d is not None
        assert d.name == "fastapi"
        assert d.is_fully_pinned()

    def test_parse_comment_returns_none(self):
        assert parse_requirements_line("# comment") is None

    def test_parse_empty_returns_none(self):
        assert parse_requirements_line("") is None
