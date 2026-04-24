"""Subprocess-based Git backend implementation.

Uses the git CLI via subprocess for all operations.
This is the most reliable backend as it doesn't require additional dependencies.
"""

from __future__ import annotations

import os
import re
import subprocess
import tempfile
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .base import (
    GitBackend,
    GitBackendError,
    GitNotFoundError,
    FetchError,
    ResolveRefError,
)
from .registry import register_backend


@register_backend
class SubprocessGitBackend(GitBackend):
    """Git backend using subprocess to invoke git CLI commands."""
    
    name = "subprocess"
    
    def __init__(self, timeout: int = 120, git_path: Optional[str] = None):
        """Initialize the subprocess backend.
        
        Args:
            timeout: Default timeout for operations.
            git_path: Path to git executable (default: auto-detect).
        """
        super().__init__(timeout=timeout)
        self._git_path = git_path
        self._git_available: Optional[bool] = None
    
    def is_available(self) -> bool:
        """Check if git executable is available."""
        if self._git_available is not None:
            return self._git_available
        
        try:
            result = subprocess.run(
                [self.git_path, "--version"],
                capture_output=True,
                timeout=10,
            )
            self._git_available = result.returncode == 0
        except (subprocess.SubprocessError, FileNotFoundError):
            self._git_available = False
        
        return self._git_available
    
    @property
    def git_path(self) -> str:
        """Get path to git executable."""
        if self._git_path:
            return self._git_path
        return "git"
    
    def _run_git(
        self,
        args: List[str],
        cwd: Optional[str] = None,
        timeout: Optional[int] = None,
        env_overrides: Optional[Dict[str, str]] = None,
    ) -> Tuple[int, str, str]:
        """Execute a git command.
        
        Args:
            args: Git command arguments.
            cwd: Working directory.
            timeout: Timeout in seconds.
            env_overrides: Environment variable overrides.
            
        Returns:
            Tuple of (returncode, stdout, stderr).
        """
        env = os.environ.copy()
        env.update(self.env_no_prompt())
        if env_overrides:
            env.update(env_overrides)
        
        cmd = [self.git_path] + args
        effective_timeout = timeout or self.timeout
        
        try:
            result = subprocess.run(
                cmd,
                cwd=cwd,
                capture_output=True,
                text=True,
                timeout=effective_timeout,
                env=env,
            )
            return result.returncode, result.stdout, result.stderr
        except subprocess.TimeoutExpired:
            raise GitBackendError(f"Git command timed out after {effective_timeout}s")
        except FileNotFoundError:
            raise GitNotFoundError(f"Git executable not found: {self.git_path}")
    
    def _run_command(
        self,
        args: List[str],
        cwd: Optional[str] = None,
        timeout: Optional[int] = None,
        env_overrides: Optional[Dict[str, str]] = None,
    ) -> Tuple[int, str, str]:
        """Execute a generic command."""
        env = os.environ.copy()
        env.update(self.env_no_prompt())
        if env_overrides:
            env.update(env_overrides)
        
        effective_timeout = timeout or self.timeout
        
        try:
            result = subprocess.run(
                args,
                cwd=cwd,
                capture_output=True,
                text=True,
                timeout=effective_timeout,
                env=env,
            )
            return result.returncode, result.stdout, result.stderr
        except subprocess.TimeoutExpired:
            raise GitBackendError(f"Command timed out after {effective_timeout}s")
        except FileNotFoundError:
            raise GitBackendError(f"Command not found: {args[0]}")
    
    def get_commit_timestamp(
        self,
        git_url: str,
        rev: str,
        timeout: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Get commit timestamp using git ls-remote and fetch."""
        # Create a temporary directory for the operation
        with tempfile.TemporaryDirectory() as tmpdir:
            # Init a bare repo
            ret, out, err = self._run_git(
                ["init", "--bare", "repo.git"],
                cwd=tmpdir,
                timeout=timeout,
            )
            if ret != 0:
                return {"ok": False, "error": f"git init failed: {err}"}
            
            repo_dir = os.path.join(tmpdir, "repo.git")
            
            # Fetch the specific commit
            ret, out, err = self._run_git(
                ["fetch", "--depth", "1", git_url, rev],
                cwd=repo_dir,
                timeout=timeout,
            )
            if ret != 0:
                # Try fetching as ref
                ret, out, err = self._run_git(
                    ["fetch", "--depth", "1", git_url, f"refs/heads/{rev}"],
                    cwd=repo_dir,
                    timeout=timeout,
                )
                if ret != 0:
                    # Try as tag
                    ret, out, err = self._run_git(
                        ["fetch", "--depth", "1", git_url, f"refs/tags/{rev}"],
                        cwd=repo_dir,
                        timeout=timeout,
                    )
                    if ret != 0:
                        return {"ok": False, "error": f"Failed to fetch {rev}: {err}"}
            
            # Get the commit SHA
            ret, out, err = self._run_git(
                ["rev-parse", "FETCH_HEAD"],
                cwd=repo_dir,
                timeout=timeout,
            )
            if ret != 0:
                return {"ok": False, "error": f"Failed to resolve FETCH_HEAD: {err}"}
            
            sha = out.strip()
            
            # Get the timestamp
            ret, out, err = self._run_git(
                ["show", "-s", "--format=%ct", "FETCH_HEAD"],
                cwd=repo_dir,
                timeout=timeout,
            )
            if ret != 0:
                return {"ok": False, "error": f"Failed to get timestamp: {err}"}
            
            try:
                timestamp = int(out.strip())
            except ValueError:
                return {"ok": False, "error": f"Invalid timestamp: {out.strip()}"}
            
            return {
                "ok": True,
                "timestamp": timestamp,
                "rev": sha,
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
        
        # Use git ls-remote to find the default branch
        ret, out, err = self._run_git(
            ["ls-remote", "--symref", git_url, "HEAD"],
            timeout=timeout,
        )
        
        if ret == 0 and out:
            # Parse output like: "ref: refs/heads/main	HEAD"
            for line in out.splitlines():
                if line.startswith("ref: refs/heads/"):
                    return line.split("/")[-1].split("\t")[0]
        
        # Fallback: try common branch names
        ret, out, err = self._run_git(
            ["ls-remote", git_url],
            timeout=timeout,
        )
        
        if ret == 0 and out:
            for line in out.splitlines():
                if "refs/heads/main" in line:
                    return "main"
                if "refs/heads/master" in line:
                    return "master"
        
        # Default fallback
        return "main"
    
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
        now_ts = int((now or datetime.now(timezone.utc)).timestamp())
        cutoff_ts = now_ts - min_age_days * 86_400
        
        resolved_ref = ref or self.resolve_default_ref(git_url, timeout=timeout)
        
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_dir = os.path.join(tmpdir, "repo.git")
            
            # Init bare repo
            ret, out, err = self._run_git(
                ["init", "--bare", repo_dir],
                timeout=timeout,
            )
            if ret != 0:
                return {"ok": False, "error": f"git init failed: {err}"}
            
            # Binary search for commit meeting age requirement
            depth = min_depth
            found_sha: Optional[str] = None
            found_ts: Optional[int] = None
            head_sha: Optional[str] = None
            head_ts: Optional[int] = None
            
            while depth <= max_depth:
                # Fetch with current depth
                fetch_args = ["fetch", "--depth", str(depth), git_url]
                if resolved_ref:
                    fetch_args.append(resolved_ref)
                
                ret, out, err = self._run_git(
                    fetch_args,
                    cwd=repo_dir,
                    timeout=timeout,
                )
                if ret != 0:
                    return {"ok": False, "error": f"Fetch failed: {err}"}
                
                # Get all commits with timestamps
                ret, out, err = self._run_git(
                    ["log", "--format=%H %ct", "--reverse"],
                    cwd=repo_dir,
                    timeout=timeout,
                )
                if ret != 0:
                    return {"ok": False, "error": f"git log failed: {err}"}
                
                commits = []
                for line in out.strip().splitlines():
                    parts = line.split()
                    if len(parts) >= 2:
                        try:
                            commits.append((parts[0], int(parts[1])))
                        except ValueError:
                            continue
                
                if not commits:
                    return {"ok": False, "error": "No commits found"}
                
                # Store HEAD info
                head_sha, head_ts = commits[-1]
                
                # Find first commit meeting age requirement
                for sha, ts in commits:
                    if ts <= cutoff_ts:
                        found_sha = sha
                        found_ts = ts
                        break
                
                if found_sha:
                    break
                
                # Check if we've fetched all history
                ret, out, err = self._run_git(
                    ["rev-list", "--count", "HEAD"],
                    cwd=repo_dir,
                    timeout=timeout,
                )
                if ret == 0:
                    try:
                        count = int(out.strip())
                        if count < depth:
                            # Reached end of history
                            break
                    except ValueError:
                        pass
                
                depth = min(depth * 2, max_depth)
            
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
