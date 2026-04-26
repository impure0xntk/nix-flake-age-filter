"""Tests for SubprocessGitBackend.find_oldest_commit_meeting_age.

We mock the _run_git method to simulate git log output and verify
that the backend correctly returns the NEWEST commit meeting the age requirement.
"""

from datetime import datetime, timezone

from flake_age_filter.core.backends.subprocess_backend import SubprocessGitBackend


class FakeBackend(SubprocessGitBackend):
    """Backend that records calls instead of actually running git."""

    def __init__(self):
        # Initialize parent to set up required attributes like _verbose
        super().__init__()
        self.calls = []

    def _run_git(self, args, cwd=None, timeout=None):
        self.calls.append(("run_git", args, cwd, timeout))
        # Default: return empty output
        return 0, "", ""


def make_backend_with_log(log_output: str) -> FakeBackend:
    """Create a backend that returns the given log output from 'git log'."""

    class _Backend(FakeBackend):
        def _run_git(self, args, cwd=None, timeout=None):
            self.calls.append(("run_git", args, cwd, timeout))
            # Check if this is a `git log` call
            if "log" in args:
                return 0, log_output, ""
            # For rev-list --count (history exhaustion check)
            if "rev-list" in args and "--count" in args:
                return 0, "100\n", ""  # Simulate 100 commits (not exhausted)
            return 0, "", ""

    return _Backend()


def make_timestamp(days_ago: int) -> int:
    """Create a Unix timestamp for `days_ago` days before now (2026-04-25)."""
    base = datetime(2026, 4, 25, 0, 0, 0, tzinfo=timezone.utc).timestamp()
    return int(base - days_ago * 86400)


def commit_line(rev: str, days_ago: int) -> str:
    """Generate a git log line: <rev> <timestamp>."""
    return f"{rev} {make_timestamp(days_ago)}"


def test_returns_newest_commit_when_multiple_qualify():
    """When several commits are older than cutoff, return the NEWEST one."""
    # cutoff: 10 days ago.
    # commits:
    #   old1: 20 days ago (should NOT be selected)
    #   old2: 15 days ago (should NOT be selected)
    #   target: 12 days ago (NEWEST that meets age >= 10 days)
    #   too_new: 5 days ago (does not meet age)
    log = "\n".join(
        [
            commit_line("old1", 20),
            commit_line("old2", 15),
            commit_line("target", 12),
            commit_line("too_new", 5),
        ]
    )
    backend = make_backend_with_log(log)

    # now_ts = base (2026-04-25), min_age_days = 10
    now_ts = make_timestamp(0)
    result = backend.find_oldest_commit_meeting_age(
        git_url="https://example.com/repo.git",
        ref="main",
        min_age_days=10,
        now_ts=now_ts,
        timeout=10,
    )

    assert result["ok"] is True
    assert result["rev"] == "target"
    assert result["timestamp"] == make_timestamp(12)


def test_returns_newest_when_cutoff_exactly_matches():
    """If a commit is exactly at cutoff, it should be returned (newest)."""
    # cutoff: 10 days ago.
    # commits:
    #   older: 15 days ago
    #   exact: 10 days ago (exactly at cutoff)
    #   newer: 9 days ago (too new)
    log = "\n".join(
        [
            commit_line("older", 15),
            commit_line("exact", 10),
            commit_line("newer", 9),
        ]
    )
    backend = make_backend_with_log(log)
    now_ts = make_timestamp(0)

    result = backend.find_oldest_commit_meeting_age(
        git_url="https://example.com/repo.git",
        ref="main",
        min_age_days=10,
        now_ts=now_ts,
        timeout=10,
    )

    assert result["ok"] is True
    assert result["rev"] == "exact"


def test_returns_none_when_no_commit_old_enough():
    """If all commits are too new, return error."""
    log = "\n".join(
        [
            commit_line("new1", 3),
            commit_line("new2", 1),
        ]
    )
    backend = make_backend_with_log(log)
    now_ts = make_timestamp(0)

    result = backend.find_oldest_commit_meeting_age(
        git_url="https://example.com/repo.git",
        ref="main",
        min_age_days=10,
        now_ts=now_ts,
        timeout=10,
    )

    assert result["ok"] is False
    assert result["rev"] is None
    assert (
        "older than" in result["error"].lower()
        or "no commit" in result["error"].lower()
    )


def test_returns_newest_when_only_one_commit_qualifies():
    """Even if only one commit qualifies, it should be returned."""
    log = "\n".join(
        [
            commit_line("only", 20),
        ]
    )
    backend = make_backend_with_log(log)
    now_ts = make_timestamp(0)

    result = backend.find_oldest_commit_meeting_age(
        git_url="https://example.com/repo.git",
        ref="main",
        min_age_days=10,
        now_ts=now_ts,
        timeout=10,
    )

    assert result["ok"] is True
    assert result["rev"] == "only"


def test_stops_iteration_when_found():
    """Backend should break out of loop once the newest qualifying commit is found."""
    # We mock _run_git to return a log with multiple qualifying commits,
    # but we want to verify that it returns the first one encountered
    # when iterating from newest to oldest.
    calls = []

    class _Backend(FakeBackend):
        def _run_git(self, args, cwd=None, timeout=None):
            calls.append(("run_git", args, cwd, timeout))
            if "log" in args:
                # oldest first; when reversed, newest first
                return (
                    0,
                    "\n".join(
                        [
                            commit_line("oldest", 30),
                            commit_line("middle", 20),
                            commit_line("newest_qualifying", 15),
                            commit_line("too_new", 5),
                        ]
                    ),
                    "",
                )
            if "rev-list" in args:
                return 0, "100\n", ""
            return 0, "", ""

    backend = _Backend()
    now_ts = make_timestamp(0)

    result = backend.find_oldest_commit_meeting_age(
        git_url="https://example.com/repo.git",
        ref="main",
        min_age_days=10,
        now_ts=now_ts,
        timeout=10,
    )

    assert result["ok"] is True
    assert result["rev"] == "newest_qualifying"
