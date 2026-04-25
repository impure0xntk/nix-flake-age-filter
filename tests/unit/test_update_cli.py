"""Tests for the update CLI command and its helper functions.

We mock the heavy external calls (git operations) to focus on the logic of
* _choose_rev – selecting a suitable rev or skipping non‑git inputs
* the CLI flow – that non‑git inputs are ignored and that overrides are
  generated correctly.
"""

import json
import tempfile
from pathlib import Path
from unittest import mock

import pytest

from flake_age_filter.cli.update import _choose_rev, app
from flake_age_filter.core.models import FlakeInput


# Helper to create a FlakeInput instance with minimal required fields.
def make_input(
    name: str,
    url: str | None = None,
    rev: str | None = None,
    input_type: str = "git",
    original: dict | None = None,
) -> FlakeInput:
    """Create a FlakeInput with sensible defaults for testing.

    Parameters correspond to the fields used by `_choose_rev`.
    """
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
    ):
        yield m_resolve, m_ts, m_find


def test_choose_rev_returns_none_for_path_input(mock_git_ops):
    # Path inputs have no URL – should be skipped.
    inp = make_input(name="local", input_type="path")
    res = _choose_rev(inp, min_age=30, timeout=10)
    assert res is None


def test_choose_rev_always_searches_newest_meeting_age(mock_git_ops):
    """Test that _choose_rev always searches for the newest commit meeting age requirement."""
    m_resolve, m_ts, m_find = mock_git_ops
    m_resolve.return_value = "main"
    # Even if current rev is old enough, should still search for newest meeting age.
    m_ts.return_value = {"ok": True, "timestamp": 1_600_000_000}
    # Mock find to return a different (newer) commit that meets age requirement.
    m_find.return_value = {"ok": True, "rev": "newer_rev", "timestamp": 1_650_000_000}
    inp = make_input(name="foo", url="git+https://example.com/repo.git", rev="abcd1234")
    res = _choose_rev(inp, min_age=30, timeout=10, now_ts=1_700_000_000)
    # Should return the commit found by find_oldest_commit_meeting_age, not the current one.
    assert res == {"ok": True, "rev": "newer_rev", "timestamp": 1_650_000_000}
    m_find.assert_called_once()


def test_choose_rev_returns_none_when_found_rev_matches_locked(mock_git_ops):
    """Test that _choose_rev returns None when found rev matches locked rev."""
    m_resolve, m_ts, m_find = mock_git_ops
    m_resolve.return_value = "main"
    m_ts.return_value = {"ok": True, "timestamp": 1_600_000_000}
    # Mock find to return the same rev as currently locked.
    m_find.return_value = {"ok": True, "rev": "abcd1234", "timestamp": 1_600_000_000}
    inp = make_input(name="foo", url="git+https://example.com/repo.git", rev="abcd1234")
    res = _choose_rev(inp, min_age=30, timeout=10, now_ts=1_700_000_000)
    # No update needed since found rev matches locked rev.
    assert res is None
    m_find.assert_called_once()


def test_choose_rev_falls_back_to_find_when_newer(mock_git_ops):
    m_resolve, m_ts, m_find = mock_git_ops
    m_resolve.return_value = "main"
    # Timestamp is NEWER than min_age threshold (only 10 days old, need 30).
    # now_ts=1_700_000_000, so 10 days ago = 1_700_000_000 - 864000 = 1_699_136_000
    recent_ts = 1_699_136_000
    m_ts.return_value = {"ok": True, "timestamp": recent_ts}
    # Mock find to return an older commit.
    m_find.return_value = {"ok": True, "rev": "olderrev", "timestamp": 1_600_000_000}
    inp = make_input(name="foo", url="git+https://example.com/repo.git", rev="newrev")
    res = _choose_rev(inp, min_age=30, timeout=10, now_ts=1_700_000_000)
    assert res == {"ok": True, "rev": "olderrev", "timestamp": 1_600_000_000}
    m_find.assert_called_once()


def test_cli_skips_path_inputs_and_outputs_overrides(mock_git_ops):
    """Test that the CLI correctly skips path inputs and generates overrides for git inputs."""
    from typer.testing import CliRunner

    runner = CliRunner()
    m_resolve, m_ts, m_find = mock_git_ops
    m_resolve.return_value = "main"
    
    # Simulate that find returns a newer commit than currently locked.
    # locked rev is "abcd", find returns "newer_rev".
    m_ts.return_value = {"ok": True, "timestamp": 1_600_000_000}
    m_find.return_value = {"ok": True, "rev": "newer_rev", "timestamp": 1_650_000_000}

    # prepare a minimal flake.lock file with two inputs – one git, one path.
    # NOTE: The lock file must have a 'root' node for extract_locked_inputs to work.
    flake_lock_content = {
        "nodes": {
            "root": {"inputs": {"git-input": "git-input", "path-input": "path-input"}},
            "git-input": {
                "locked": {
                    "type": "git",
                    "url": "git+https://example.com/repo.git",
                    "rev": "abcd",
                }
            },
            "path-input": {"locked": {"type": "path", "path": "/tmp/local"}},
        }
    }
    tmp = Path(tempfile.mkdtemp()) / "flake.lock"
    tmp.write_text(json.dumps(flake_lock_content))

    # Run the CLI with dry‑run to avoid calling nix.
    # NOTE: The app's default command is update, so no "update" subcommand needed.
    result = runner.invoke(app, ["--min-age", "30", str(tmp), "--dry-run"])
    # Exit code should be 0 (dry‑run always succeeds).
    assert result.exit_code == 0, (
        f"Expected exit code 0, got {result.exit_code}. stdout: {result.stdout}"
    )
    out = result.stdout
    # Only the git input should appear in the override list (not path-input).
    assert "git-input=" in out, f"Expected 'git-input=' in output: {out}"
    # path-input should NOT appear as an override (it should be skipped)
    assert "path-input=" not in out, f"Expected 'path-input=' NOT in output: {out}"
