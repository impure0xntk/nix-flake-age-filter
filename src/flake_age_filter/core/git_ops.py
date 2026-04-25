"""Git operation facade using the backend system.

This module provides a simplified interface for Git operations that internally
uses the pluggable backend system. It maintains backward compatibility with
the existing API while delegating to the appropriate backend.
"""

from __future__ import annotations

import os
import sys
from datetime import datetime, timezone
from typing import Tuple, Dict, Any, Optional
from pathlib import Path

from .backends import (
    GitBackend,
    GitBackendError,
    get_backend,
    get_auto_backend,
    list_backends,
)


# Re-export exceptions for backward compatibility
class GitOperationError(GitBackendError):
    """Base exception for GitOperation errors."""
    pass


class GitNotFound(GitOperationError):
    """Raised when git executable is not found."""
    pass


class GitConfigError(GitOperationError):
    """Raised when git config operation fails."""
    pass


class FetchError(GitOperationError):
    """Raised when git fetch operation fails."""
    pass


class ResolveRefError(GitOperationError):
    """Raised when resolving a ref fails."""
    pass


# Global backend instance (lazy initialized)
_backend: Optional[GitBackend] = None
_backend_name: str = "auto"


def set_backend(name: str, **kwargs) -> None:
    """Set the global backend by name.
    
    Args:
        name: Backend name ("subprocess", "pygit2", "github", "auto").
        **kwargs: Additional arguments for backend constructor.
    """
    global _backend, _backend_name
    _backend_name = name
    if name == "auto":
        _backend = None  # Will be lazily initialized
    else:
        _backend = get_backend(name, **kwargs)


def get_current_backend() -> GitBackend:
    """Get the current global backend instance.
    
    Returns:
        Current backend instance.
    """
    global _backend
    if _backend is None:
        _backend = get_auto_backend()
    return _backend


# ---------------------------------------------------------------------
# Facade functions (backward compatible API)
# ---------------------------------------------------------------------

def parse_github_url(git_url: str) -> Optional[Tuple[str, str]]:
    """Parse a GitHub URL to extract owner and repository.
    
    Args:
        git_url: Git URL to parse
    
    Returns:
        Tuple of (owner, repo) if URL is a GitHub URL, None otherwise
    """
    return GitBackend.parse_github_url(git_url)


def parse_github_date(date_str: str) -> Optional[int]:
    """Parse a GitHub API date string to Unix timestamp.
    
    Args:
        date_str: ISO-8601 date string from GitHub API
    
    Returns:
        Unix timestamp or None if parsing fails
    """
    return GitBackend.parse_github_date(date_str)


def get_commit_timestamp(
    git_url: str,
    ref: str,
    timeout: int = 120,
    method: str = "auto",
) -> Dict[str, Any]:
    """Get commit timestamp for a revision.
    
    Args:
        git_url: Git URL of the repository
        ref: Revision to get timestamp for (SHA, branch, tag)
        timeout: Request timeout in seconds
        method: Backend method to use ("subprocess", "pygit2", "github", "auto")
    
    Returns:
        Dict with keys: ok, timestamp, error, rev
    """
    if method == "auto":
        backend = get_auto_backend(timeout=timeout)
    else:
        try:
            backend = get_backend(method, timeout=timeout)
        except ValueError as e:
            # Method not found, fall back to subprocess (not auto) to respect user intent
            print(f"Warning: Unknown method '{method}', falling back to subprocess: {e}", file=sys.stderr)
            backend = get_backend("subprocess", timeout=timeout)
    return backend.get_commit_timestamp(git_url, ref, timeout=timeout)


def get_github_default_branch(
    owner: str,
    repo: str,
    timeout: int = 10,
) -> Optional[str]:
    """Get the default branch name from GitHub API.
    
    Args:
        owner: GitHub owner
        repo: Repository name
        timeout: Request timeout in seconds
    
    Returns:
        Default branch name or None if not available
    """
    try:
        backend = get_backend("github", timeout=timeout)
        git_url = f"https://github.com/{owner}/{repo}.git"
        return backend.resolve_default_ref(git_url, timeout=timeout)
    except Exception:
        return None


def resolve_default_ref(
    git_url: str,
    ref: Optional[str],
    timeout: int = 15,
    method: str = "auto",
) -> str:
    """Resolve the default ref (branch) for a remote.
    
    Args:
        git_url: Git URL of the remote
        ref: Optional explicit ref to resolve
        timeout: Request timeout in seconds
        method: Backend method to use ("subprocess", "pygit2", "github", "auto")
    
    Returns:
        Resolved ref name
    """
    if method == "auto":
        backend = get_auto_backend(timeout=timeout)
    else:
        try:
            backend = get_backend(method, timeout=timeout)
        except ValueError:
            # Fall back to subprocess to respect user intent of avoiding GitHub API
            print(f"Warning: Unknown method '{method}', falling back to subprocess", file=sys.stderr)
            backend = get_backend("subprocess", timeout=timeout)
    return backend.resolve_default_ref(git_url, ref, timeout=timeout)


def find_oldest_commit_meeting_age(
    git_url: str,
    ref: Optional[str],
    min_age_days: int,
    min_depth: int = 100,
    max_depth: int = 3000,
    timeout: int = 300,
    method: str = "auto",
    now: Optional[datetime] = None,
    verbose: bool = False,
) -> Dict[str, Any]:
    """Find the oldest commit meeting the minimum age requirement.
    
    Args:
        git_url: Git URL of the repository
        ref: Branch or tag name (None for HEAD)
        min_age_days: Minimum age in days
        min_depth: Minimum fetch depth
        max_depth: Maximum fetch depth
        timeout: Request timeout in seconds
        method: Method to use: "github", "pygit2", "subprocess", "auto"
        now: Override current time for reproducible checks
        verbose: Enable debug output to stderr
    
    Returns:
        Dict with keys: ok, rev, timestamp, depth, date, error, too_new_*
    """
    # Select backend based on method
    if method == "auto":
        backend = get_auto_backend(timeout=timeout)
    else:
        try:
            backend = get_backend(method, timeout=timeout)
        except ValueError:
            # Fall back to subprocess to respect user intent of avoiding GitHub API
            print(f"Warning: Unknown method '{method}', falling back to subprocess", file=sys.stderr)
            backend = get_backend("subprocess", timeout=timeout)
    
    if verbose:
        print(f"[DEBUG] Finding commit for {git_url} (ref={ref}, min_age={min_age_days}d)", file=sys.stderr)
    
    result = backend.find_oldest_commit_meeting_age(
        git_url,
        ref,
        min_age_days,
        min_depth=min_depth,
        max_depth=max_depth,
        timeout=timeout,
        now=now,
        verbose=verbose,
    )
    return result


# ---------------------------------------------------------------------
# Legacy GitOperationBase class (deprecated, kept for compatibility)
# ---------------------------------------------------------------------

class GitOperationBase:
    """Legacy base class for Git operations.
    
    DEPRECATED: Use GitBackend from backends module instead.
    This class is kept for backward compatibility.
    """

    def __init__(self, repo_path: Optional[str] = None):
        """Initialize GitOperation.
        
        Args:
            repo_path: Path to a local repository. Ignored (for compatibility).
        """
        self.repo_path = repo_path
        self._backend = get_current_backend()

    @property
    def env_no_prompt(self) -> Dict[str, str]:
        """Return environment variables that silence interactive prompts."""
        return GitBackend.env_no_prompt()

    def run_command(
        self,
        args: list[str],
        cwd: Optional[str] = None,
        timeout: int = 60,
        env_overrides: Optional[Dict[str, str]] = None,
    ) -> Tuple[int, str, str]:
        """Execute a command (DEPRECATED: not supported in new backend)."""
        import subprocess
        import os
        
        env = os.environ.copy()
        env.update(self.env_no_prompt)
        if env_overrides:
            env.update(env_overrides)
        
        result = subprocess.run(
            args,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout,
            env=env,
        )
        return result.returncode, result.stdout, result.stderr

    def run_git(
        self,
        args: list[str],
        cwd: Optional[str] = None,
        timeout: int = 60,
        env_overrides: Optional[Dict[str, str]] = None,
    ) -> Tuple[int, str, str]:
        """Execute a git command (DEPRECATED: not supported in new backend)."""
        return self.run_command(["git"] + args, cwd, timeout, env_overrides)

    def parse_github_url(self, git_url: str) -> Optional[Tuple[str, str]]:
        """Parse a GitHub URL to extract owner and repository."""
        return GitBackend.parse_github_url(git_url)

    def parse_github_date(self, date_str: str) -> Optional[int]:
        """Parse a GitHub API date string to Unix timestamp."""
        return GitBackend.parse_github_date(date_str)

    def get_commit_timestamp(
        self,
        git_url: str,
        ref: str,
        timeout: int = 120,
    ) -> Dict[str, Any]:
        """Get commit timestamp for a revision."""
        return get_commit_timestamp(git_url, ref, timeout)

    def get_github_default_branch(
        self,
        owner: str,
        repo: str,
        timeout: int = 10,
    ) -> Optional[str]:
        """Get the default branch name from GitHub API."""
        return get_github_default_branch(owner, repo, timeout)

    def resolve_default_ref(
        self,
        git_url: str,
        ref: Optional[str],
        timeout: int = 15,
    ) -> str:
        """Resolve the default ref (branch) for a remote."""
        return resolve_default_ref(git_url, ref, timeout)

    def find_oldest_commit_meeting_age(
        self,
        git_url: str,
        ref: Optional[str],
        min_age_days: int,
        min_depth: int = 20,
        max_depth: int = 3000,
        timeout: int = 300,
        method: str = "auto",
        now: Optional[datetime] = None,
    ) -> Dict[str, Any]:
        """Find the oldest commit meeting the minimum age requirement."""
        return find_oldest_commit_meeting_age(
            git_url, ref, min_age_days, min_depth, max_depth, timeout, method, now
        )
