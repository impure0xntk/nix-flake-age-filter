"""Tests for GitHubAPIBackend.find_oldest_commit_meeting_age.

We mock the _api_get method to simulate GitHub API responses and verify
that the backend correctly returns the NEWEST commit meeting the age requirement.
"""

import pytest
from datetime import datetime, timezone
from unittest import mock

from flake_age_filter.core.backends.github_api_backend import GitHubAPIBackend


def make_timestamp(days_ago: int) -> int:
    """Create a Unix timestamp for `days_ago` days before now (2026-04-25)."""
    base = datetime(2026, 4, 25, 0, 0, 0, tzinfo=timezone.utc).timestamp()
    return int(base - days_ago * 86400)


def make_iso_from_days_ago(days_ago: int) -> str:
    """Create an ISO timestamp for `days_ago` days before now."""
    ts = make_timestamp(days_ago)
    dt = datetime.fromtimestamp(ts, tz=timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


class MockBackend(GitHubAPIBackend):
    """Backend that mocks _api_get and resolve_default_ref."""

    def __init__(self, api_responses=None):
        # Skip parent __init__
        self._responses = api_responses or []
        self.call_count = 0

    def _api_get(self, url, params=None, timeout=None):
        if self.call_count < len(self._responses):
            result = self._responses[self.call_count]
            self.call_count += 1
            return result
        return 404, {"error": "No more responses"}

    def resolve_default_ref(self, git_url, timeout=None):
        return "main"


def test_returns_newest_commit_when_multiple_qualify():
    """When several commits are older than cutoff, return the NEWEST one."""
    # cutoff: 10 days ago
    # GitHub API returns commits in chronological order (newest first by default)
    # With until=cutoff_iso and per_page=1, it returns the newest commit older than cutoff
    target_ts = make_timestamp(12)
    target_iso = make_iso_from_days_ago(12)

    backend = MockBackend(
        api_responses=[
            (200, [{"sha": "target", "commit": {"committer": {"date": target_iso}}}]),
        ]
    )

    result = backend.find_oldest_commit_meeting_age(
        git_url="https://github.com/owner/repo.git",
        ref="main",
        min_age_days=10,
        now=datetime(2026, 4, 25, 0, 0, 0, tzinfo=timezone.utc),
    )

    assert result["ok"] is True
    assert result["rev"] == "target"
    assert result["timestamp"] == target_ts


def test_returns_none_when_no_commit_old_enough():
    """If all commits are too new (API returns empty), return error."""
    backend = MockBackend(
        api_responses=[
            (200, []),  # No commits older than cutoff
        ]
    )

    result = backend.find_oldest_commit_meeting_age(
        git_url="https://github.com/owner/repo.git",
        ref="main",
        min_age_days=10,
        now=datetime(2026, 4, 25, 0, 0, 0, tzinfo=timezone.utc),
    )

    assert result["ok"] is False
    assert result["rev"] is None


def test_handles_rate_limit():
    """If API returns 403, return fallback error."""
    backend = MockBackend(
        api_responses=[
            (403, {"error": "API rate limit exceeded"}),
        ]
    )

    result = backend.find_oldest_commit_meeting_age(
        git_url="https://github.com/owner/repo.git",
        ref="main",
        min_age_days=10,
        now=datetime(2026, 4, 25, 0, 0, 0, tzinfo=timezone.utc),
    )

    assert result["ok"] is False
    assert "rate limit" in result["error"].lower()
    assert result.get("fallback") is True


def test_returns_newest_when_only_one_commit_qualifies():
    """Even if only one commit qualifies, it should be returned."""
    target_ts = make_timestamp(20)
    target_iso = make_iso_from_days_ago(20)

    backend = MockBackend(
        api_responses=[
            (200, [{"sha": "only", "commit": {"committer": {"date": target_iso}}}]),
        ]
    )

    result = backend.find_oldest_commit_meeting_age(
        git_url="https://github.com/owner/repo.git",
        ref="main",
        min_age_days=10,
        now=datetime(2026, 4, 25, 0, 0, 0, tzinfo=timezone.utc),
    )

    assert result["ok"] is True
    assert result["rev"] == "only"
    assert result["timestamp"] == target_ts


def test_uses_resolved_ref():
    """Backend should use the resolved default ref when none provided."""
    backend = MockBackend(
        api_responses=[
            (200, [{"sha": "abc123", "commit": {"committer": {"date": make_iso_from_days_ago(15)}}}] ),
        ]
    )
    backend.resolve_default_ref = mock.MagicMock(return_value="main")

    result = backend.find_oldest_commit_meeting_age(
        git_url="https://github.com/owner/repo.git",
        ref=None,  # No ref provided
        min_age_days=10,
        now=datetime(2026, 4, 25, 0, 0, 0, tzinfo=timezone.utc),
    )

    assert result["ok"] is True
    backend.resolve_default_ref.assert_called_once()
