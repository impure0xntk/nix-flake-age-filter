"""Core module for nix-flake-age-filter.

This module provides:
- GitBackend abstract base class and implementations
- Git operation facade (git_ops)
- Flake lock file parsing (lock_file)
- Data models (models)
- Age checking utilities (age_check)
- Error handling (errors)
"""

from __future__ import annotations

# Import exceptions from git_ops for backward compatibility
from .git_ops import (
    GitOperationError,
    GitNotFound,
    GitConfigError,
    FetchError,
    ResolveRefError,
    set_backend,
    get_current_backend,
)

# Import backend system
from .backends import (
    GitBackend,
    GitBackendError,
    GitNotFoundError as BackendGitNotFoundError,
    FetchError as BackendFetchError,
    ResolveRefError as BackendResolveRefError,
    RateLimitError,
    CommitInfo,
    RefInfo,
    register_backend,
    get_backend,
    list_backends,
    get_auto_backend,
    SubprocessGitBackend,
    Pygit2Backend,
    GitHubAPIBackend,
)

__all__ = [
    # Legacy API (from git_ops)
    "GitOperationError",
    "GitNotFound",
    "GitConfigError",
    "FetchError",
    "ResolveRefError",
    "set_backend",
    "get_current_backend",
    # New backend system
    "GitBackend",
    "GitBackendError",
    "BackendGitNotFoundError",
    "BackendFetchError",
    "BackendResolveRefError",
    "RateLimitError",
    "CommitInfo",
    "RefInfo",
    "register_backend",
    "get_backend",
    "list_backends",
    "get_auto_backend",
    # Backend classes
    "SubprocessGitBackend",
    "Pygit2Backend",
    "GitHubAPIBackend",
]
