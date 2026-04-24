"""Abstract base class for Git backends.

Defines the interface that all Git backends must implement.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Tuple


@dataclass(frozen=True)
class CommitInfo:
    """Information about a Git commit."""
    sha: str
    timestamp: int  # Unix epoch seconds (UTC)
    message: Optional[str] = None
    author: Optional[str] = None
    
    @property
    def date_str(self) -> str:
        """Return formatted date string."""
        dt = datetime.fromtimestamp(self.timestamp, tz=timezone.utc)
        return dt.strftime("%Y-%m-%d %H:%M UTC")


@dataclass(frozen=True)
class RefInfo:
    """Information about a Git reference (branch/tag)."""
    name: str
    sha: str
    is_branch: bool = False
    is_tag: bool = False


class GitBackendError(Exception):
    """Base exception for Git backend errors."""
    pass


class GitNotFoundError(GitBackendError):
    """Git executable or library not found."""
    pass


class FetchError(GitBackendError):
    """Error during git fetch operation."""
    pass


class ResolveRefError(GitBackendError):
    """Error resolving a Git reference."""
    pass


class RateLimitError(GitBackendError):
    """API rate limit exceeded."""
    pass


class GitBackend(ABC):
    """Abstract base class for Git operation backends.
    
    All backends must implement this interface to be used polymorphically.
    The backend provides methods for:
    - Resolving references (branches, tags)
    - Fetching commit information
    - Finding commits by age criteria
    """
    
    # Backend name for registration and CLI selection
    name: str = "base"
    
    def __init__(self, timeout: int = 120):
        """Initialize the backend.
        
        Args:
            timeout: Default timeout for network operations in seconds.
        """
        self.timeout = timeout
    
    # ---------------------------------------------------------------------
    # Core operations (must be implemented by all backends)
    # ---------------------------------------------------------------------
    
    @abstractmethod
    def get_commit_timestamp(
        self,
        git_url: str,
        rev: str,
        timeout: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Get the timestamp for a specific commit.
        
        Args:
            git_url: Git repository URL.
            rev: Commit SHA, branch, or tag.
            timeout: Optional timeout override.
            
        Returns:
            Dict with keys:
                - ok: bool
                - timestamp: int (Unix epoch) if ok
                - rev: str (resolved SHA) if ok
                - error: str if not ok
        """
        pass
    
    @abstractmethod
    def resolve_default_ref(
        self,
        git_url: str,
        ref: Optional[str] = None,
        timeout: Optional[int] = None,
    ) -> str:
        """Resolve the default reference for a repository.
        
        Args:
            git_url: Git repository URL.
            ref: Optional explicit ref to resolve.
            timeout: Optional timeout override.
            
        Returns:
            Resolved ref name (e.g., "main", "master", or the provided ref).
            
        Raises:
            ResolveRefError: If the reference cannot be resolved.
        """
        pass
    
    @abstractmethod
    def find_oldest_commit_meeting_age(
        self,
        git_url: str,
        ref: Optional[str],
        min_age_days: int,
        min_depth: int = 100,
        max_depth: int = 3000,
        timeout: Optional[int] = None,
        now: Optional[datetime] = None,
        **kwargs,
    ) -> Dict[str, Any]:
        """Find the oldest commit meeting minimum age requirement.
        
        Args:
            git_url: Git repository URL.
            ref: Branch or tag name (None for HEAD).
            min_age_days: Minimum age in days.
            min_depth: Minimum fetch depth.
            max_depth: Maximum fetch depth.
            timeout: Optional timeout override.
            now: Override current time for reproducible checks.
            
        Returns:
            Dict with keys:
                - ok: bool
                - rev: str (commit SHA) if ok
                - timestamp: int if ok
                - depth: int (search depth) if ok
                - date: str (formatted date) if ok
                - error: str if not ok
                - too_new_commit: str | None (if HEAD is too new)
                - too_new_timestamp: int | None
                - too_new_date: str | None
        """
        pass
    
    # ---------------------------------------------------------------------
    # Optional operations (may be overridden for optimization)
    # ---------------------------------------------------------------------
    
    def list_refs(
        self,
        git_url: str,
        timeout: Optional[int] = None,
    ) -> Dict[str, Any]:
        """List all references (branches and tags) in a repository.
        
        Args:
            git_url: Git repository URL.
            timeout: Optional timeout override.
            
        Returns:
            Dict with keys:
                - ok: bool
                - refs: List[RefInfo] if ok
                - error: str if not ok
        """
        return {
            "ok": False,
            "refs": [],
            "error": "list_refs not implemented for this backend",
        }
    
    def is_available(self) -> bool:
        """Check if this backend is available (dependencies installed).
        
        Returns:
            True if the backend can be used, False otherwise.
        """
        return True
    
    # ---------------------------------------------------------------------
    # Utility methods
    # ---------------------------------------------------------------------
    
    @staticmethod
    def parse_github_url(git_url: str) -> Optional[Tuple[str, str]]:
        """Parse GitHub URL to extract owner and repo.
        
        Args:
            git_url: Git URL (HTTPS or SSH).
            
        Returns:
            Tuple of (owner, repo) if GitHub URL, None otherwise.
        """
        import re
        m = re.search(r"github\.com[:/]{1}([^/]+)/([^/]+?)(?:\.git)?$", git_url)
        return m.groups() if m else None
    
    @staticmethod
    def env_no_prompt() -> Dict[str, str]:
        """Return environment variables to silence interactive prompts."""
        return {
            "GIT_TERMINAL_PROMPT": "0",
            "GIT_ASKPASS": "echo",
            "GIT_CONFIG_COUNT": "1",
            "GIT_CONFIG_KEY_0": "protocol.version",
            "GIT_CONFIG_VALUE_0": "2",
        }
    
    @staticmethod
    def parse_github_date(date_str: str) -> Optional[int]:
        """Parse an ISO-8601 timestamp from the GitHub API into a Unix epoch.
        
        Only UTC timestamps ending with ``Z`` are expected.
        """
        if not date_str or not date_str.endswith("Z"):
            return None
        try:
            dt = datetime(
                int(date_str[:4]),
                int(date_str[5:7]),
                int(date_str[8:10]),
                int(date_str[11:13]),
                int(date_str[14:16]),
                int(date_str[17:19]),
                tzinfo=timezone.utc,
            )
            return int(dt.timestamp())
        except Exception:
            return None
