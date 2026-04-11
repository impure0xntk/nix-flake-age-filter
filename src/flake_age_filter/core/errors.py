"""Custom exception hierarchy for the flake‑age filter.
All domain‑specific errors inherit from :class:`FlakeAgeError` so callers can
catch a single base class.
"""

class FlakeAgeError(Exception):
    """Base class for all flake‑age related errors."""
    pass


class FlakeLockNotFoundError(FlakeAgeError):
    """Raised when ``flake.lock`` cannot be located or read."""
    pass


class CommitFetchError(FlakeAgeError):
    """Raised when a commit timestamp cannot be obtained from a remote."""
    pass


class RateLimitError(FlakeAgeError):
    """Raised when a remote API (e.g. GitHub) returns a rate‑limit response."""
    pass


class AgeValidationError(FlakeAgeError):
    """Raised when a commit does not satisfy the minimum‑age requirement."""
    pass


class NixExecutionError(FlakeAgeError):
    """Raised when a ``nix`` command exits non‑zero."""
    pass
