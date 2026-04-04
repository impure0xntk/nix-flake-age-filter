"""Custom exception classes."""

from __future__ import annotations


class FlakeAgeError(Exception):
    """Base exception for flake-age-filter."""


class FlakeLockNotFoundError(FlakeAgeError):
    """Raised when flake.lock is not found."""


class FlakeLockParseError(FlakeAgeError):
    """Raised when JSON parsing of flake.lock fails."""


class CommitNotFoundError(FlakeAgeError):
    """Raised when the specified revision is not found on the remote."""


class RateLimitError(FlakeAgeError):
    """Raised when a rate limit (e.g., GitHub API) is reached."""


class RepositoryNotAccessible(FlakeAgeError):
    """Raised when the remote repository is not accessible."""


class TimeoutError(FlakeAgeError):
    """Raised when an operation times out."""
