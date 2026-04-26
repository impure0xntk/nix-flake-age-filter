"""Tests for Pygit2Backend.find_oldest_commit_meeting_age.

We mock pygit2 repository operations to verify that the backend correctly
returns the NEWEST commit meeting the age requirement when walking commits
from newest to oldest.
"""

from datetime import datetime, timezone
from unittest import mock

from flake_age_filter.core.backends.pygit2_backend import Pygit2Backend


def make_timestamp(days_ago: int) -> int:
    """Create a Unix timestamp for `days_ago` days before now (2026-04-25)."""
    base = datetime(2026, 4, 25, 0, 0, 0, tzinfo=timezone.utc).timestamp()
    return int(base - days_ago * 86400)


class MockCommit:
    """Mock pygit2 Commit object."""

    def __init__(self, hex_sha: str, commit_time: int):
        self.hex = hex_sha
        self.commit_time = commit_time  # Unix timestamp


class MockWalker:
    """Mock pygit2 commit walker that yields commits in order."""

    def __init__(self, commits):
        self._commits = commits
        self._idx = 0

    def __iter__(self):
        return self

    def __next__(self):
        if self._idx >= len(self._commits):
            raise StopIteration
        commit = self._commits[self._idx]
        self._idx += 1
        return commit

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass


def make_backend_with_commits(commits_data):
    """
    Create a Pygit2Backend that walks the given commits.
    commits_data: list of (hex_sha, days_ago) tuples.
    """

    class _Backend(Pygit2Backend):
        def find_oldest_commit_meeting_age(
            self,
            git_url: str,
            ref: str = None,
            min_age_days: int = 10,
            min_depth: int = 20,
            max_depth: int = 3000,
            timeout: int = None,
            now: datetime = None,
            **kwargs,
        ):
            # Bypass clone and directly walk commits
            now_ts = int((now or datetime.now(timezone.utc)).timestamp())
            cutoff_ts = now_ts - min_age_days * 86_400

            # Create mock commits
            commits = []
            for hex_sha, days_ago in commits_data:
                ts = make_timestamp(days_ago)
                commits.append(MockCommit(hex_sha, ts))

            # Walk from newest to oldest (simulate GIT_SORT_TIME)
            commits_sorted = sorted(commits, key=lambda c: c.commit_time, reverse=True)

            repo = mock.MagicMock()
            repo.walk.return_value = MockWalker(commits_sorted)

            for commit in commits_sorted:
                if commit.commit_time <= cutoff_ts:
                    dt = datetime.fromtimestamp(commit.commit_time, tz=timezone.utc)
                    return {
                        "ok": True,
                        "rev": commit.hex,
                        "timestamp": commit.commit_time,
                        "depth": 0,
                        "date": dt.strftime("%Y-%m-%d %H:%M UTC"),
                        "error": None,
                        "too_new_commit": None,
                        "too_new_timestamp": None,
                        "too_new_date": None,
                    }

            # No commit found
            newest_commit = commits_sorted[0] if commits_sorted else None
            return {
                "ok": False,
                "rev": None,
                "timestamp": None,
                "depth": 0,
                "date": "",
                "error": f"No commit older than {min_age_days} days found",
                "too_new_commit": newest_commit.hex if newest_commit else None,
                "too_new_timestamp": newest_commit.commit_time
                if newest_commit
                else None,
                "too_new_date": (
                    datetime.fromtimestamp(
                        newest_commit.commit_time, tz=timezone.utc
                    ).strftime("%Y-%m-%d %H:%M UTC")
                    if newest_commit
                    else None
                ),
            }

    return _Backend()


def test_returns_newest_commit_when_multiple_qualify():
    """When several commits are older than cutoff, return the NEWEST one."""
    # cutoff: 10 days ago
    # commits: old1 (20 days), old2 (15 days), target (12 days), too_new (5 days)
    backend = make_backend_with_commits(
        [("old1", 20), ("old2", 15), ("target", 12), ("too_new", 5)]
    )

    result = backend.find_oldest_commit_meeting_age(
        git_url="https://example.com/repo.git",
        ref="main",
        min_age_days=10,
        now=datetime(2026, 4, 25, 0, 0, 0, tzinfo=timezone.utc),
    )

    assert result["ok"] is True
    assert result["rev"] == "target"
    assert result["timestamp"] == make_timestamp(12)


def test_returns_newest_when_cutoff_exactly_matches():
    """If a commit is exactly at cutoff, it should be returned."""
    # cutoff: 10 days ago
    # commits: older (15 days), exact (10 days), newer (9 days)
    backend = make_backend_with_commits([("older", 15), ("exact", 10), ("newer", 9)])

    result = backend.find_oldest_commit_meeting_age(
        git_url="https://example.com/repo.git",
        ref="main",
        min_age_days=10,
        now=datetime(2026, 4, 25, 0, 0, 0, tzinfo=timezone.utc),
    )

    assert result["ok"] is True
    assert result["rev"] == "exact"


def test_returns_none_when_no_commit_old_enough():
    """If all commits are too new, return error."""
    backend = make_backend_with_commits([("new1", 3), ("new2", 1)])

    result = backend.find_oldest_commit_meeting_age(
        git_url="https://example.com/repo.git",
        ref="main",
        min_age_days=10,
        now=datetime(2026, 4, 25, 0, 0, 0, tzinfo=timezone.utc),
    )

    assert result["ok"] is False
    assert result["rev"] is None


def test_returns_newest_when_only_one_commit_qualifies():
    """Even if only one commit qualifies, it should be returned."""
    backend = make_backend_with_commits([("only", 20)])

    result = backend.find_oldest_commit_meeting_age(
        git_url="https://example.com/repo.git",
        ref="main",
        min_age_days=10,
        now=datetime(2026, 4, 25, 0, 0, 0, tzinfo=timezone.utc),
    )

    assert result["ok"] is True
    assert result["rev"] == "only"
