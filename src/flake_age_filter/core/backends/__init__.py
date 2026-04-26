"""Git backend implementations for nix-flake-age-filter.

This module provides a pluggable backend system for Git operations:
- SubprocessGitBackend: Uses git CLI via subprocess (most reliable)
- Pygit2Backend: Uses pygit2 library (faster, requires libgit2)
- GitHubAPIBackend: Uses GitHub REST API (fastest for GitHub repos)

Usage:
    from flake_age_filter.core.backends import get_backend
    
    # Get backend by name
    backend = get_backend("subprocess")
    result = backend.get_commit_timestamp("https://github.com/user/repo.git", "main")
    
    # Use with method selection
    backend = get_backend("auto")  # Auto-select best available
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Optional

from .base import (
    GitBackend,
    GitBackendError,
    GitNotFoundError,
    FetchError,
    ResolveRefError,
    RateLimitError,
    CommitInfo,
    RefInfo,
)
from .registry import (
    register_backend,
    get_backend,
    list_backends,
    clear_backends,
)

# Import backends to register them
from .subprocess_backend import SubprocessGitBackend
from .pygit2_backend import Pygit2Backend
from .github_api_backend import GitHubAPIBackend

__all__ = [
    # Base classes
    "GitBackend",
    "CommitInfo",
    "RefInfo",
    # Exceptions
    "GitBackendError",
    "GitNotFoundError",
    "FetchError",
    "ResolveRefError",
    "RateLimitError",
    # Registry
    "register_backend",
    "get_backend",
    "list_backends",
    "clear_backends",
    # Backends
    "SubprocessGitBackend",
    "Pygit2Backend",
    "GitHubAPIBackend",
]


def get_auto_backend(timeout: int = 120, token: Optional[str] = None, verbose: bool = False, **kwargs) -> GitBackend:
    """Get the best available backend automatically.
    
    Selection order:
    1. GitHub API (if URL is GitHub and requests available)
    2. Pygit2 (if available)
    3. Subprocess (fallback, always available)
    
    Args:
        timeout: Default timeout for operations.
        token: Optional GitHub token for higher rate limits (GitHub backend only).
        verbose: If True, log rate limit info to stderr (GitHub backend only).
        **kwargs: Additional arguments for backend.
        
    Returns:
        Backend instance.
    """
    from typing import Optional as _Optional
    
    # Build kwargs for GitHub backend
    github_kwargs = {**kwargs}
    if token is not None:
        github_kwargs["token"] = token
    if verbose:
        github_kwargs["verbose"] = verbose
    
    # Try GitHub API first (fastest for GitHub repos)
    try:
        backend = get_backend("github", timeout=timeout, **github_kwargs)
        if backend.is_available():
            return backend
    except (ValueError, ImportError):
        pass
    
    # Try pygit2 (fast for any git repo)
    try:
        backend = get_backend("pygit2", timeout=timeout, **kwargs)
        if backend.is_available():
            return backend
    except (ValueError, ImportError):
        pass
    
    # Fall back to subprocess (always available if git is installed)
    return get_backend("subprocess", timeout=timeout, **kwargs)
