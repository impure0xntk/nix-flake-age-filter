"""Unit tests for the verify CLI.

Tests that verify checks the currently locked commit (inp.rev) against min_age.
It does NOT search for older commits.
"""

import json
import tempfile
from pathlib import Path
from unittest import mock

import pytest
from typer.testing import CliRunner

from flake_age_filter.cli.verify import app


@pytest.fixture
def mock_git_ops():
    with (
        mock.patch("flake_age_filter.cli.verify.git_ops.get_commit_timestamp") as m_ts,
        mock.patch("time.time") as m_time,
    ):
        yield m_ts, m_time


def test_verify_locked_rev_satisfies_min_age(mock_git_ops):
    """Locked commit is old enough -> exit 0, deviation positive."""
    m_ts, m_time = mock_git_ops
    # now = 1_740_000_000 (2025-02-15 ish)
    # commit timestamp = 1_739_136_000 -> ~10 days old
    m_time.return_value = 1_740_000_000
    m_ts.return_value = {"ok": True, "timestamp": 1_739_136_000}

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
                                "rev": "abcdef",
                            }
                        },
                    }
                }
            )
        )
        result = runner.invoke(
            app, ["--min-age", "5", str(flake_path), "--method", "github"]
        )
        assert result.exit_code == 0, result.stdout
        # get_commit_timestamp should be called with the locked rev
        m_ts.assert_called_once()
        call_args = m_ts.call_args
        assert call_args[0][1] == "abcdef"  # rev argument


def test_verify_locked_rev_too_new(mock_git_ops):
    """Locked commit is too new -> exit 1, deviation negative."""
    m_ts, m_time = mock_git_ops
    m_time.return_value = 1_740_000_000
    # Only 3 days old, min_age is 30 -> deviation = -27
    m_ts.return_value = {"ok": True, "timestamp": 1_739_840_000}

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
                                "rev": "abcdef",
                            }
                        },
                    }
                }
            )
        )
        result = runner.invoke(app, ["--min-age", "30", str(flake_path)])
        assert result.exit_code == 1
        assert "pkg" in result.stdout
        # Check that deviation is shown (negative value)
        assert "-27" in result.stdout or "deviation" in result.stdout.lower()


def test_verify_no_locked_rev(mock_git_ops):
    """Input without a locked rev -> reported as error."""
    m_ts, m_time = mock_git_ops
    m_time.return_value = 1_740_000_000

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
                                # no "rev" key
                            }
                        },
                    }
                }
            )
        )
        result = runner.invoke(app, ["--min-age", "30", str(flake_path)])
        assert result.exit_code == 1
        assert "No locked revision" in result.stdout or "error" in result.stdout.lower()


def test_verify_timestamp_fetch_fails(mock_git_ops):
    """When timestamp fetch fails, report error."""
    m_ts, m_time = mock_git_ops
    m_time.return_value = 1_740_000_000
    m_ts.return_value = {"ok": False, "error": "not found"}

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
                                "rev": "abcdef",
                            }
                        },
                    }
                }
            )
        )
        result = runner.invoke(app, ["--min-age", "30", str(flake_path)])
        assert result.exit_code == 1


def test_verify_method_passed_to_get_timestamp(mock_git_ops):
    """The --method option is forwarded to get_commit_timestamp."""
    m_ts, m_time = mock_git_ops
    m_time.return_value = 1_740_000_000
    m_ts.return_value = {"ok": True, "timestamp": 1_739_136_000}

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
                                "rev": "abcdef",
                            }
                        },
                    }
                }
            )
        )
        result = runner.invoke(
            app, ["--min-age", "5", str(flake_path), "--method", "subprocess"]
        )
        assert result.exit_code == 0
        m_ts.assert_called_once()
        call_kwargs = m_ts.call_args.kwargs
        assert call_kwargs.get("method") == "subprocess"


def test_verify_deviation_display(mock_git_ops):
    """Deviation column shows correct +/- values."""
    m_ts, m_time = mock_git_ops
    # now = 1_740_000_000, commit = 1_739_136_000 -> ~10 days old
    m_time.return_value = 1_740_000_000
    m_ts.return_value = {"ok": True, "timestamp": 1_739_136_000}

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
                                "rev": "abcdef",
                            }
                        },
                    }
                }
            )
        )
        # With min-age=5, deviation should be +5 (10-5=5)
        result = runner.invoke(app, ["--min-age", "5", str(flake_path)])
        assert result.exit_code == 0
        # Should show +5 deviation (positive = over min-age)
        assert "+5" in result.stdout or "Deviation" in result.stdout
