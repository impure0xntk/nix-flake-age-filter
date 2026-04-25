"""GitHub API-based Git backend implementation.

Uses GitHub REST API for fast operations on GitHub repositories.
Provides the fastest method for GitHub-hosted repos.
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Tuple

from .base import (
    GitBackend,
    GitBackendError,
    GitNotFoundError,
    FetchError,
    ResolveRefError,
    RateLimitError,
)
from .registry import register_backend

# Lazy import
_requests = None


def _get_requests():
    """Lazy import of requests."""
    global _requests
    if _requests is None:
        try:
            import requests as _requests_module
            _requests = _requests_module
        except ImportError:
            pass
    return _requests


_GITHUB_HEADERS = {
    "Accept": "application/vnd.github+json",
    "User-Agent": "nix-flake-age-filter/1.0",
}


@register_backend
class GitHubAPIBackend(GitBackend):
    """Git backend using GitHub REST API.
    
    This backend only works for GitHub repositories.
    For other hosts, it will fail with an error.
    """
    
    name = "github"
    
    def __init__(self, timeout: int = 120, token: Optional[str] = None):
        """Initialize the GitHub API backend.
        
        Args:
            timeout: Default timeout for operations.
            token: Optional GitHub token for higher rate limits.
        """
        super().__init__(timeout=timeout)
        self._token = token
        self._available: Optional[bool] = None
    
    def is_available(self) -> bool:
        """Check if requests is available."""
        if self._available is not None:
            return self._available
        self._available = _get_requests() is not None
        return self._available
    
    @property
    def headers(self) -> Dict[str, str]:
        """Get headers for GitHub API requests."""
        headers = _GITHUB_HEADERS.copy()
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"
        return headers
    
    def _get_owner_repo(self, git_url: str) -> Tuple[str, str]:
        """Extract owner and repo from GitHub URL.
        
        Raises:
            GitBackendError: If not a GitHub URL.
        """
        result = self.parse_github_url(git_url)
        if not result:
            raise GitBackendError(f"Not a GitHub URL: {git_url}")
        return result
    
    def _api_get(
        self,
        url: str,
        params: Optional[Dict[str, Any]] = None,
        timeout: Optional[int] = None,
    ) -> Tuple[int, Any]:
        """Make a GET request to GitHub API.
        
        Returns:
            Tuple of (status_code, json_data or error_message).
        """
        requests = _get_requests()
        if requests is None:
            return 0, {"error": "requests not available"}
        
        try:
            resp = requests.get(
                url,
                headers=self.headers,
                params=params,
                timeout=timeout or self.timeout,
            )
            
            if resp.status_code == 403:
                raise RateLimitError("GitHub API rate limited (403)")
            
            if resp.status_code == 200:
                return 200, resp.json()
            
            return resp.status_code, {"error": f"HTTP {resp.status_code}"}
            
        except requests.RequestException as e:
            return 0, {"error": str(e)}
    
    def get_commit_timestamp(
        self,
        git_url: str,
        rev: str,
        timeout: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Get commit timestamp via GitHub API."""
        try:
            owner, repo = self._get_owner_repo(git_url)
        except GitBackendError as e:
            return {"ok": False, "error": str(e)}
        
        url = f"https://api.github.com/repos/{owner}/{repo}/commits/{rev}"
        status, data = self._api_get(url, timeout=timeout)
        
        if status != 200:
            return {"ok": False, "error": data.get("error", f"HTTP {status}")}
        
        commit = data.get("commit", {})
        committer = commit.get("committer") or commit.get("author") or {}
        ts = self.parse_github_date(committer.get("date", ""))
        
        if ts is None:
            return {"ok": False, "error": "Failed to parse commit date"}
        
        return {
            "ok": True,
            "timestamp": ts,
            "rev": data.get("sha", rev),
        }
    
    def resolve_default_ref(
        self,
        git_url: str,
        ref: Optional[str] = None,
        timeout: Optional[int] = None,
    ) -> str:
        """Resolve the default reference for a repository."""
        if ref:
            return ref
        
        try:
            owner, repo = self._get_owner_repo(git_url)
        except GitBackendError as e:
            raise ResolveRefError(str(e))
        
        url = f"https://api.github.com/repos/{owner}/{repo}"
        status, data = self._api_get(url, timeout=timeout)
        
        if status != 200:
            raise ResolveRefError(data.get("error", f"HTTP {status}"))
        
        default_branch = data.get("default_branch")
        if not default_branch:
            raise ResolveRefError("Could not determine default branch")
        
        return default_branch
    
    def find_oldest_commit_meeting_age(
        self,
        git_url: str,
        ref: Optional[str],
        min_age_days: int,
        min_depth: int = 100,
        max_depth: int = 3000,
        timeout: Optional[int] = None,
        now: Optional[datetime] = None,
        verbose: bool = False,
        **kwargs,
    ) -> Dict[str, Any]:
        """Find the oldest commit meeting minimum age requirement via GitHub API."""
        try:
            owner, repo = self._get_owner_repo(git_url)
        except GitBackendError as e:
            return {"ok": False, "error": str(e)}
        
        now_ts = int((now or datetime.now(timezone.utc)).timestamp())
        cutoff_ts = now_ts - min_age_days * 86_400
        
        resolved_ref = ref or self.resolve_default_ref(git_url, timeout=timeout)
        
        if verbose:
            print(f"[DEBUG] [github] owner={owner}, repo={repo}, ref={ref} -> resolved_ref={resolved_ref}", file=sys.stderr)
            print(f"[DEBUG] [github] cutoff_ts={cutoff_ts} ({min_age_days}d ago)", file=sys.stderr)
        
        # Build cutoff ISO string (one minute earlier for edge cases)
        cutoff_dt = datetime.fromtimestamp(cutoff_ts - 60, tz=timezone.utc)
        cutoff_iso = cutoff_dt.strftime("%Y-%m-%dT%H:%M:%SZ")
        
        if verbose:
            print(f"[DEBUG] [github] Querying commits until {cutoff_iso}...", file=sys.stderr)
        
        # Query for commits older than cutoff.
        # GitHub API returns commits in chronological order (newest first by default).
        # Using per_page=1 returns the *newest* commit that is older than cutoff_iso.
        url = f"https://api.github.com/repos/{owner}/{repo}/commits"
        status, data = self._api_get(
            url,
            params={"sha": resolved_ref, "per_page": 1, "until": cutoff_iso},
            timeout=timeout,
        )
        
        if verbose:
            print(f"[DEBUG] [github] API response: status={status}, data_len={len(data) if isinstance(data, list) else 'N/A'}", file=sys.stderr)
        
        if status == 200 and data:
            commit = data[0]
            commit_data = commit.get("commit", {})
            committer = commit_data.get("committer") or commit_data.get("author") or {}
            ts = self.parse_github_date(committer.get("date", ""))
            
            if ts is not None:
                dt = datetime.fromtimestamp(ts, tz=timezone.utc)
                if verbose:
                    print(f"[DEBUG] [github] Found commit {commit.get('sha', '')[:8]} ts={ts}", file=sys.stderr)
                return {
                    "ok": True,
                    "rev": commit.get("sha"),
                    "timestamp": ts,
                    "depth": 0,
                    "date": dt.strftime("%Y-%m-%d %H:%M UTC"),
                    "error": None,
                    "too_new_commit": None,
                    "too_new_timestamp": None,
                    "too_new_date": None,
                }
        
        if status == 403:
            if verbose:
                print(f"[DEBUG] [github] Rate limited (403)", file=sys.stderr)
            return {
                "ok": False,
                "rev": None,
                "timestamp": None,
                "depth": 0,
                "date": "",
                "error": "GitHub API rate limited (403)",
                "fallback": True,
                "too_new_commit": None,
                "too_new_timestamp": None,
                "too_new_date": None,
            }
        
        if status == 404:
            if verbose:
                print(f"[DEBUG] [github] Ref not found (404)", file=sys.stderr)
            return {
                "ok": False,
                "rev": None,
                "timestamp": None,
                "depth": 0,
                "date": "",
                "error": "ref not found",
                "too_new_commit": None,
                "too_new_timestamp": None,
                "too_new_date": None,
            }
        
        # Get HEAD commit to report shortfall
        if verbose:
            print(f"[DEBUG] [github] Fetching HEAD commit to report shortfall...", file=sys.stderr)
        status, data = self._api_get(
            url,
            params={"sha": resolved_ref, "per_page": 1},
            timeout=timeout,
        )
        
        if status == 200 and data:
            commit = data[0]
            commit_data = commit.get("commit", {})
            committer = commit_data.get("committer") or commit_data.get("author") or {}
            ts = self.parse_github_date(committer.get("date", ""))
            
            if ts is not None:
                age_days = (now_ts - ts) / 86_400
                dt = datetime.fromtimestamp(ts, tz=timezone.utc)
                if verbose:
                    print(f"[DEBUG] [github] HEAD is only {age_days:.1f}d old (needs {min_age_days}d)", file=sys.stderr)
                return {
                    "ok": False,
                    "rev": None,
                    "timestamp": None,
                    "depth": 0,
                    "date": "",
                    "error": f"HEAD is only {age_days:.1f}d old (needs {min_age_days}d)",
                    "too_new_commit": commit.get("sha"),
                    "too_new_timestamp": ts,
                    "too_new_date": dt.strftime("%Y-%m-%d %H:%M UTC"),
                }
        
        return {
            "ok": False,
            "rev": None,
            "timestamp": None,
            "depth": 0,
            "date": "",
            "error": "GitHub API failed",
        }
    
    def list_refs(
        self,
        git_url: str,
        timeout: Optional[int] = None,
    ) -> Dict[str, Any]:
        """List all branches and tags via GitHub API."""
        from .base import RefInfo
        
        try:
            owner, repo = self._get_owner_repo(git_url)
        except GitBackendError as e:
            return {"ok": False, "refs": [], "error": str(e)}
        
        refs: list[RefInfo] = []
        
        # Get branches
        url = f"https://api.github.com/repos/{owner}/{repo}/branches"
        status, data = self._api_get(url, params={"per_page": 100}, timeout=timeout)
        
        if status == 200:
            for branch in data:
                refs.append(RefInfo(
                    name=branch.get("name", ""),
                    sha=branch.get("commit", {}).get("sha", ""),
                    is_branch=True,
                    is_tag=False,
                ))
        
        # Get tags
        url = f"https://api.github.com/repos/{owner}/{repo}/tags"
        status, data = self._api_get(url, params={"per_page": 100}, timeout=timeout)
        
        if status == 200:
            for tag in data:
                refs.append(RefInfo(
                    name=tag.get("name", ""),
                    sha=tag.get("commit", {}).get("sha", ""),
                    is_branch=False,
                    is_tag=True,
                ))
        
        return {"ok": True, "refs": refs, "error": None}
