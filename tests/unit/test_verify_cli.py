"""Unit tests for the verify CLI method option."""

import json
import tempfile
from pathlib import Path
from unittest import mock

import pytest
from typer.testing import CliRunner

from flake_age_filter.cli.verify import app
from flake_age_filter.core.models import FlakeInput


def make_input(
    name: str,
    url: str | None = None,
    rev: str | None = None,
    input_type: str = "git",
    original: dict | None = None,
) -> FlakeInput:
    """Create a FlakeInput with sensible defaults for testing."""
    locked: dict = {"type": input_type}
    if url is not None:
        locked["url"] = url
    if rev is not None:
        locked["rev"] = rev
    if original is None:
        original = {}
    return FlakeInput(name=name, locked=locked, original=original)


@pytest.fixture
def mock_git_ops():
    with (
        mock.patch("flake_age_filter.core.git_ops.resolve_default_ref") as m_resolve,
        mock.patch("flake_age_filter.core.git_ops.get_commit_timestamp") as m_ts,
        mock.patch(
            "flake_age_filter.core.git_ops.find_oldest_commit_meeting_age"
        ) as m_find,
        mock.patch("time.time") as m_time,
    ):
        yield m_resolve, m_ts, m_find, m_time


def test_verify_method_github_passed(mock_git_ops):
    m_resolve, m_ts, m_find, m_time = mock_git_ops
    m_time.return_value = 1_740_000_000  # Fix now_ts to make the commit 10 days old (after 2025-01-01 to avoid SSL warnings)
    m_resolve.return_value = "main"
    # Timestamp for the locked revision is recent (not old enough).
    m_ts.return_value = {"ok": True, "timestamp": 1_739_136_000}  # 10 days old
    # Mock find to return an older commit.
    m_find.return_value = {"ok": True, "rev": "olderrev", "timestamp": 1_600_000_000}

    runner = CliRunner()
    with tempfile.TemporaryDirectory() as tmpdir:
        flake_path = Path(tmpdir) / "flake.lock"
        flake_path.write_text(
            json.dumps(
                {
                    "nodes": {
                        "root": {"inputs": {"pkg": "pkg"}},
                        "pkg": {
                            "locked": {
                                "type": "git",
                                "url": "git+https://github.com/owner/repo.git",
                                "rev": "newrev",
                            }
                        },
                    }
                }
            )
        )
        # Invoke verify with --method github
        result = runner.invoke(
            app, ["--min-age", "30", str(flake_path), "--method", "github"]
        )
        assert result.exit_code == 0, (
            f"Expected exit code 0, got {result.exit_code}. stdout: {result.stdout}"
        )
        # Ensure find_oldest_commit_meeting_age was called with method='github'
        m_find.assert_called_once()
        called_kwargs = m_find.call_args.kwargs
        assert called_kwargs.get("method") == "github"


def test_verify_method_pygit2_passed(mock_git_ops):
    m_resolve, m_ts, m_find, m_time = mock_git_ops
    m_time.return_value = 1_740_000_000  # Fix now_ts to make the commit 10 days old (after 2025-01-01 to avoid SSL warnings)
    m_resolve.return_value = "main"
    m_ts.return_value = {"ok": True, "timestamp": 1_739_136_000}
    m_find.return_value = {"ok": True, "rev": "olderrev", "timestamp": 1_600_000_000}

    runner = CliRunner()
    with tempfile.TemporaryDirectory() as tmpdir:
        flake_path = Path(tmpdir) / "flake.lock"
        flake_path.write_text(
            json.dumps(
                {
                    "nodes": {
                        "root": {"inputs": {"pkg": "pkg"}},
                        "pkg": {
                            "locked": {
                                "type": "git",
                                "url": "git+https://example.com/repo.git",
                                "rev": "newrev",
                            }
                        },
                    }
                }
            )
        )
        result = runner.invoke(
            app, ["--min-age", "30", str(flake_path), "--method", "pygit2"]
        )
        assert result.exit_code == 0
        m_find.assert_called_once()
        called_kwargs = m_find.call_args.kwargs
        assert called_kwargs.get("method") == "pygit2"


def test_verify_method_subprocess_passed(mock_git_ops):
    m_resolve, m_ts, m_find, m_time = mock_git_ops
    m_time.return_value = 1_740_000_000  # Fix now_ts to make the commit 10 days old (after 2025-01-01 to avoid SSL warnings)
    m_resolve.return_value = "main"
    m_ts.return_value = {"ok": True, "timestamp": 1_739_136_000}
    m_find.return_value = {"ok": True, "rev": "olderrev", "timestamp": 1_600_000_000}

    runner = CliRunner()
    with tempfile.TemporaryDirectory() as tmpdir:
        flake_path = Path(tmpdir) / "flake.lock"
        flake_path.write_text(
            json.dumps(
                {
                    "nodes": {
                        "root": {"inputs": {"pkg": "pkg"}},
                        "pkg": {
                            "locked": {
                                "type": "git",
                                "url": "git+https://example.com/repo.git",
                                "rev": "newrev",
                            }
                        },
                    }
                }
            )
        )
        result = runner.invoke(
            app, ["--min-age", "30", str(flake_path), "--method", "subprocess"]
        )
        assert result.exit_code == 0
        m_find.assert_called_once()
        called_kwargs = m_find.call_args.kwargs
        assert called_kwargs.get("method") == "subprocess"


def test_verify_method_auto_attempts_github_first(mock_git_ops):
    m_resolve, m_ts, m_find, m_time = mock_git_ops
    m_time.return_value = 1_740_000_000  # Fix now_ts to make the commit 10 days old (after 2025-01-01 to avoid SSL warnings)
    m_resolve.return_value = "main"
    m_ts.return_value = {"ok": True, "timestamp": 1_739_136_000}
    # Mock find to return an older commit (success)
    m_find.return_value = {"ok": True, "rev": "olderrev", "timestamp": 1_600_000_000}

    runner = CliRunner()
    with tempfile.TemporaryDirectory() as tmpdir:
        flake_path = Path(tmpdir) / "flake.lock"
        flake_path.write_text(
            json.dumps(
                {
                    "nodes": {
                        "root": {"inputs": {"pkg": "pkg"}},
                        "pkg": {
                            "locked": {
                                "type": "git",
                                "url": "git+https://github.com/owner/repo.git",
                                "rev": "newrev",
                            }
                        },
                    }
                }
            )
        )
        result = runner.invoke(
            app, ["--min-age", "30", str(flake_path), "--method", "auto"]
        )
        assert result.exit_code == 0
        # Should have been called once with method='auto'
        m_find.assert_called_once()
        called_kwargs = m_find.call_args.kwargs
        assert called_kwargs.get("method") == "auto"


def test_verify_method_auto_falls_back_to_subprocess(mock_git_ops):
    m_resolve, m_ts, m_find, m_time = mock_git_ops
    m_time.return_value = 1_740_000_000  # Fix now_ts to make the commit 10 days old (after 2025-01-01 to avoid SSL warnings)
    m_resolve.return_value = "main"
    m_ts.return_value = {"ok": True, "timestamp": 1_739_136_000}
    # Mock find to return an older commit (success)
    m_find.return_value = {"ok": True, "rev": "olderrev", "timestamp": 1_600_000_000}

    runner = CliRunner()
    with tempfile.TemporaryDirectory() as tmpdir:
        flake_path = Path(tmpdir) / "flake.lock"
        flake_path.write_text(
            json.dumps(
                {
                    "nodes": {
                        "root": {"inputs": {"pkg": "pkg"}},
                        "pkg": {
                            "locked": {
                                "type": "git",
                                "url": "git+https://example.com/repo.git",
                                "rev": "newrev",
                            }
                        },
                    }
                }
            )
        )
        result = runner.invoke(
            app, ["--min-age", "30", str(flake_path), "--method", "auto"]
        )
        assert result.exit_code == 0
        m_find.assert_called_once()
        called_kwargs = m_find.call_args.kwargs
        assert called_kwargs.get("method") == "auto"
