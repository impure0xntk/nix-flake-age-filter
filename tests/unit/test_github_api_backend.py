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


class TestTokenHandling:
    """Tests for GitHub token authentication support."""

    def test_token_passed_to_api_requests(self):
        """Token should be included in API request headers."""
        backend = GitHubAPIBackend(token="ghp_test123")
        assert backend._token == "ghp_test123"

    def test_no_token_by_default(self):
        """Backend should work without a token (unauthenticated)."""
        with mock.patch("flake_age_filter.core.backends.github_api_backend._get_token_from_gh_cli", return_value=None):
            backend = GitHubAPIBackend()
            assert backend._token is None

    def test_token_sent_in_authorization_header(self):
        """When a token is set, it should be sent as Bearer auth header."""
        import unittest.mock as mock

        backend = GitHubAPIBackend(token="ghp_test123")

        mock_resp = mock.MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = []
        mock_resp.headers = {
            "x-ratelimit-remaining": "4999",
            "x-ratelimit-limit": "5000",
            "x-ratelimit-reset": "1700000000",
        }

        with mock.patch("requests.get", return_value=mock_resp) as mock_get:
            backend._api_get("https://api.github.com/repos/o/r/commits")
            mock_get.assert_called_once()
            call_kwargs = mock_get.call_args
            assert "Authorization" in call_kwargs.kwargs.get("headers", {})
            assert call_kwargs.kwargs["headers"]["Authorization"] == "Bearer ghp_test123"

    def test_no_auth_header_without_token(self):
        """When no token is set, no Authorization header should be sent."""
        import unittest.mock as mock

        with mock.patch("flake_age_filter.core.backends.github_api_backend._get_token_from_gh_cli", return_value=None):
            backend = GitHubAPIBackend()

        mock_resp = mock.MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = []
        mock_resp.headers = {
            "x-ratelimit-remaining": "58",
            "x-ratelimit-limit": "60",
            "x-ratelimit-reset": "1700000000",
        }

        with mock.patch("requests.get", return_value=mock_resp) as mock_get:
            backend._api_get("https://api.github.com/repos/o/r/commits")
            mock_get.assert_called_once()
            call_kwargs = mock_get.call_args
            assert "Authorization" not in call_kwargs.kwargs.get("headers", {})


class TestRateLimitInfo:
    """Tests for rate limit tracking and display."""

    def test_rate_limit_info_updated_after_request(self):
        """Rate limit info should be updated after each API request."""
        import unittest.mock as mock

        backend = GitHubAPIBackend(token="ghp_test")

        mock_resp = mock.MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = []
        mock_resp.headers = {
            "X-RateLimit-Remaining": "4995",
            "X-RateLimit-Limit": "5000",
            "X-RateLimit-Reset": "1700000000",
        }

        with mock.patch("requests.get", return_value=mock_resp):
            backend._api_get("https://api.github.com/repos/o/r/commits")

        info = backend.get_rate_limit_info()
        assert info is not None
        assert info["remaining"] == 4995
        assert info["limit"] == 5000
        assert info["reset"] == 1700000000

    def test_rate_limit_info_values_none_before_request(self):
        """Rate limit info values should be None before any API request."""
        with mock.patch("flake_age_filter.core.backends.github_api_backend._get_token_from_gh_cli", return_value=None):
            backend = GitHubAPIBackend()
        info = backend.get_rate_limit_info()
        assert info["remaining"] is None
        assert info["limit"] is None
        assert info["reset"] is None
        assert info["has_token"] is False

    def test_rate_limit_error_includes_hint_without_token(self):
        """Rate limit error should suggest setting a token when none is configured."""
        import unittest.mock as mock

        backend = GitHubAPIBackend(token=None)

        # Use the MockBackend which simulates API responses
        mock_backend = MockBackend(
            api_responses=[
                (403, {"error": "rate limit exceeded"}),
            ]
        )
        mock_backend._token = None

        result = mock_backend.find_oldest_commit_meeting_age(
            git_url="https://github.com/owner/repo.git",
            ref="main",
            min_age_days=10,
            now=datetime(2026, 4, 25, 0, 0, 0, tzinfo=timezone.utc),
        )

        assert result["ok"] is False
        assert "rate limit" in result["error"].lower()


class TestGetTokenFromEnv:
    """Tests for _get_github_token_from_env helper function."""

    def test_reads_github_token(self):
        """Should read GITHUB_TOKEN environment variable."""
        from flake_age_filter.core.backends.github_api_backend import _get_github_token_from_env

        with mock.patch.dict("os.environ", {"GITHUB_TOKEN": "ghp_abc123"}, clear=False):
            assert _get_github_token_from_env() == "ghp_abc123"

    def test_reads_gh_token(self):
        """Should read GH_TOKEN environment variable as fallback."""
        from flake_age_filter.core.backends.github_api_backend import _get_github_token_from_env

        with mock.patch.dict("os.environ", {"GH_TOKEN": "ghp_xyz789"}, clear=False):
            assert _get_github_token_from_env() == "ghp_xyz789"

    def test_github_token_takes_priority(self):
        """GITHUB_TOKEN should take priority over GH_TOKEN."""
        from flake_age_filter.core.backends.github_api_backend import _get_github_token_from_env

        with mock.patch.dict(
            "os.environ",
            {"GITHUB_TOKEN": "primary", "GH_TOKEN": "secondary"},
            clear=False,
        ):
            assert _get_github_token_from_env() == "primary"

    def test_returns_none_when_no_env_vars(self):
        """Should return None when no token env vars are set and gh not available."""
        from flake_age_filter.core.backends.github_api_backend import _get_github_token_from_env

        with mock.patch.dict("os.environ", {}, clear=True):
            with mock.patch("shutil.which", return_value=None):
                assert _get_github_token_from_env() is None

    def test_falls_back_to_gh_cli(self):
        """Should fall back to gh auth token when no env vars are set."""
        from flake_age_filter.core.backends.github_api_backend import _get_github_token_from_env

        mock_result = mock.MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "ghp_from_cli\n"

        with mock.patch.dict("os.environ", {}, clear=True):
            with mock.patch("shutil.which", return_value="/usr/bin/gh"):
                with mock.patch("subprocess.run", return_value=mock_result):
                    assert _get_github_token_from_env() == "ghp_from_cli"

    def test_env_vars_take_priority_over_gh_cli(self):
        """Environment variables should take priority over gh CLI."""
        from flake_age_filter.core.backends.github_api_backend import _get_github_token_from_env

        with mock.patch.dict("os.environ", {"GH_TOKEN": "from_env"}, clear=False):
            with mock.patch("flake_age_filter.core.backends.github_api_backend._get_token_from_gh_cli") as mock_gh:
                assert _get_github_token_from_env() == "from_env"
                mock_gh.assert_not_called()


class TestGetTokenFromGhCli:
    """Tests for _get_token_from_gh_cli helper function."""

    def test_returns_token_on_success(self):
        """Should return token when gh auth token succeeds."""
        from flake_age_filter.core.backends.github_api_backend import _get_token_from_gh_cli

        mock_result = mock.MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "ghp_testtoken123\n"

        with mock.patch("shutil.which", return_value="/usr/bin/gh"):
            with mock.patch("subprocess.run", return_value=mock_result) as mock_run:
                token = _get_token_from_gh_cli()
                assert token == "ghp_testtoken123"
                mock_run.assert_called_once_with(
                    ["/usr/bin/gh", "auth", "token"],
                    capture_output=True,
                    text=True,
                    timeout=10,
                )

    def test_returns_none_when_gh_not_installed(self):
        """Should return None when gh CLI is not found."""
        from flake_age_filter.core.backends.github_api_backend import _get_token_from_gh_cli

        with mock.patch("shutil.which", return_value=None):
            assert _get_token_from_gh_cli() is None

    def test_returns_none_when_gh_auth_fails(self):
        """Should return None when gh auth token returns non-zero exit code."""
        from flake_age_filter.core.backends.github_api_backend import _get_token_from_gh_cli

        mock_result = mock.MagicMock()
        mock_result.returncode = 1
        mock_result.stderr = "not logged in"

        with mock.patch("shutil.which", return_value="/usr/bin/gh"):
            with mock.patch("subprocess.run", return_value=mock_result):
                assert _get_token_from_gh_cli() is None

    def test_returns_none_when_gh_output_empty(self):
        """Should return None when gh auth token outputs empty string."""
        from flake_age_filter.core.backends.github_api_backend import _get_token_from_gh_cli

        mock_result = mock.MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "   \n"

        with mock.patch("shutil.which", return_value="/usr/bin/gh"):
            with mock.patch("subprocess.run", return_value=mock_result):
                assert _get_token_from_gh_cli() is None

    def test_returns_none_on_timeout(self):
        """Should return None when gh auth token times out."""
        import subprocess as sp
        from flake_age_filter.core.backends.github_api_backend import _get_token_from_gh_cli

        with mock.patch("shutil.which", return_value="/usr/bin/gh"):
            with mock.patch("subprocess.run", side_effect=sp.TimeoutExpired(cmd="gh", timeout=10)):
                assert _get_token_from_gh_cli() is None

    def test_returns_none_on_os_error(self):
        """Should return None when subprocess.run raises OSError."""
        from flake_age_filter.core.backends.github_api_backend import _get_token_from_gh_cli

        with mock.patch("shutil.which", return_value="/usr/bin/gh"):
            with mock.patch("subprocess.run", side_effect=OSError("permission denied")):
                assert _get_token_from_gh_cli() is None

    def test_strips_whitespace(self):
        """Should strip leading/trailing whitespace from token."""
        from flake_age_filter.core.backends.github_api_backend import _get_token_from_gh_cli

        mock_result = mock.MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "  ghp_spaced  \n"

        with mock.patch("shutil.which", return_value="/usr/bin/gh"):
            with mock.patch("subprocess.run", return_value=mock_result):
                assert _get_token_from_gh_cli() == "ghp_spaced"
