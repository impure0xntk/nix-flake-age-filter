"""Pygit2-based Git backend implementation.

Uses the pygit2 library for efficient Python-side git operations.
This backend is faster than subprocess but requires libgit2.
"""

from __future__ import annotations

import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from .base import (
    GitBackend,
    GitBackendError,
    GitNotFoundError,
    FetchError,
    ResolveRefError,
)
from .registry import register_backend

# Lazy import
_pygit2 = None


def _get_pygit2():
    """Lazy import of pygit2."""
    global _pygit2
    if _pygit2 is None:
        try:
            import pygit2 as _pygit2_module
            _pygit2 = _pygit2_module
        except ImportError:
            pass
    return _pygit2


@register_backend
class Pygit2Backend(GitBackend):
    """Git backend using pygit2 library."""
    
    name = "pygit2"
    
    def __init__(self, timeout: int = 120):
        """Initialize the pygit2 backend.
        
        Args:
            timeout: Default timeout for operations.
        """
        super().__init__(timeout=timeout)
        self._available: Optional[bool] = None
    
    def is_available(self) -> bool:
        """Check if pygit2 is available."""
        if self._available is not None:
            return self._available
        self._available = _get_pygit2() is not None
        return self._available
    
    def _create_callbacks(self, timeout: int):
        """Create remote callbacks for authentication."""
        pygit2 = _get_pygit2()
        if pygit2 is None:
            raise GitNotFoundError("pygit2 not available")
        
        # Create basic callbacks
        return pygit2.RemoteCallbacks()
    
    def get_commit_timestamp(
        self,
        git_url: str,
        rev: str,
        timeout: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Get commit timestamp using pygit2."""
        pygit2 = _get_pygit2()
        if pygit2 is None:
            return {"ok": False, "error": "pygit2 not available"}
        
        with tempfile.TemporaryDirectory() as tmpdir:
            try:
                # Clone with depth 1
                repo = pygit2.clone_repository(
                    git_url,
                    tmpdir,
                    depth=1,
                    checkout_branch=rev if not self._is_sha(rev) else None,
                )
                
                # Get the commit
                if self._is_sha(rev):
                    # Fetch the specific SHA
                    commit = repo.get(rev)
                    if commit is None:
                        # Try to fetch it
                        for remote in repo.remotes:
                            remote.fetch([rev], callbacks=self._create_callbacks(timeout or self.timeout))
                        commit = repo.get(rev)
                        if commit is None:
                            return {"ok": False, "error": f"Commit {rev} not found"}
                else:
                    # Use HEAD or branch
                    commit = repo.head.peel(pygit2.Commit)
                
                return {
                    "ok": True,
                    "timestamp": commit.commit_time,
                    "rev": commit.hex,
                }
                
            except pygit2.GitError as e:
                return {"ok": False, "error": f"Git error: {e}"}
            except Exception as e:
                return {"ok": False, "error": f"Error: {e}"}
    
    def resolve_default_ref(
        self,
        git_url: str,
        ref: Optional[str] = None,
        timeout: Optional[int] = None,
    ) -> str:
        """Resolve the default reference for a repository."""
        if ref:
            return ref
        
        pygit2 = _get_pygit2()
        if pygit2 is None:
            raise GitNotFoundError("pygit2 not available")
        
        try:
            with tempfile.TemporaryDirectory() as tmpdir:
                # Clone with depth 1 without checkout
                repo = pygit2.clone_repository(
                    git_url,
                    tmpdir,
                    depth=1,
                    checkout=False,
                )
                
                # Check HEAD reference
                head = repo.head
                if head.target:
                    # Extract branch name from ref
                    target_str = str(head.target)
                    if target_str.startswith("refs/heads/"):
                        return target_str[len("refs/heads/"):]
                
                # Fallback to main/master detection
                for ref_name in repo.references:
                    if ref_name == "refs/heads/main":
                        return "main"
                    if ref_name == "refs/heads/master":
                        return "master"
                
                return "main"
                
        except pygit2.GitError as e:
            raise ResolveRefError(f"Failed to resolve default ref: {e}")
    
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
        """Find the oldest commit meeting minimum age requirement."""
        pygit2 = _get_pygit2()
        if pygit2 is None:
            return {"ok": False, "error": "pygit2 not available"}
        
        now_ts = int((now or datetime.now(timezone.utc)).timestamp())
        cutoff_ts = now_ts - min_age_days * 86_400
        
        resolved_ref = ref or self.resolve_default_ref(git_url, timeout=timeout)
        
        with tempfile.TemporaryDirectory() as tmpdir:
            try:
                # Clone with initial depth
                depth = min_depth
                found_sha: Optional[str] = None
                found_ts: Optional[int] = None
                head_sha: Optional[str] = None
                head_ts: Optional[int] = None
                
                while depth <= max_depth:
                    repo = pygit2.clone_repository(
                        git_url,
                        tmpdir,
                        depth=depth,
                        checkout_branch=resolved_ref,
                    )
                    
                    # Walk commits from oldest to newest
                    commits = []
                    walker = repo.walk(repo.head.target, pygit2.GIT_SORT_TOPOLOGICAL | pygit2.GIT_SORT_REVERSE)
                    
                    for commit in walker:
                        commits.append((commit.hex, commit.commit_time))
                    
                    if not commits:
                        return {"ok": False, "error": "No commits found"}
                    
                    head_sha, head_ts = commits[-1]
                    
                    # Find first commit meeting age requirement
                    for sha, ts in commits:
                        if ts <= cutoff_ts:
                            found_sha = sha
                            found_ts = ts
                            break
                    
                    if found_sha:
                        break
                    
                    # Check if we've reached the end
                    commit_count = len(commits)
                    if commit_count < depth:
                        break
                    
                    depth = min(depth * 2, max_depth)
                    
                    # Clean up for next iteration
                    import shutil
                    shutil.rmtree(tmpdir)
                    tmpdir = tempfile.mkdtemp()
                
                if found_sha and found_ts:
                    dt = datetime.fromtimestamp(found_ts, tz=timezone.utc)
                    return {
                        "ok": True,
                        "rev": found_sha,
                        "timestamp": found_ts,
                        "depth": depth,
                        "date": dt.strftime("%Y-%m-%d %H:%M UTC"),
                        "error": None,
                        "too_new_commit": None,
                        "too_new_timestamp": None,
                        "too_new_date": None,
                    }
                
                # No commit old enough
                dt = datetime.fromtimestamp(head_ts, tz=timezone.utc) if head_ts else None
                return {
                    "ok": False,
                    "rev": None,
                    "timestamp": None,
                    "depth": depth,
                    "date": "",
                    "error": f"No commit found older than {min_age_days} days",
                    "too_new_commit": head_sha,
                    "too_new_timestamp": head_ts,
                    "too_new_date": dt.strftime("%Y-%m-%d %H:%M UTC") if dt else None,
                }
                
            except pygit2.GitError as e:
                return {"ok": False, "error": f"Git error: {e}"}
            except Exception as e:
                return {"ok": False, "error": f"Error: {e}"}
    
    @staticmethod
    def _is_sha(s: str) -> bool:
        """Check if string looks like a SHA hash."""
        return len(s) >= 7 and all(c in "0123456789abcdefABCDEF" for c in s)
