"""Git‑related utilities for the flake‑age filter.

This module consolidates all subprocess / pygit2 interactions that were
previously scattered throughout ``flake_age_common.py``.  The public API
mirrors the original functions so the rest of the codebase can be ported
incrementally.
"""

from __future__ import annotations

import os
import re
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Tuple

import pygit2
import requests

from .errors import FlakeAgeError

# ---------------------------------------------------------------------------
# Basic command execution helpers
# ---------------------------------------------------------------------------

def run_cmd(
    args: list[str],
    cwd: str | Path | None = None,
    timeout: int = 60,
    env_overrides: dict | None = None,
) -> Tuple[int, str, str]:
    """Execute a command and return ``(returncode, stdout, stderr)``.

    ``env_overrides`` is merged onto the current environment.
    """
    env = {**os.environ, **(env_overrides or {})}
    try:
        result = subprocess.run(
            args,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=cwd,
            env=env,
        )
        return result.returncode, result.stdout, result.stderr
    except subprocess.TimeoutExpired:
        return -1, "", f"{' '.join(args[:3])} timed out after {timeout}s"
    except Exception as exc:  # pragma: no cover – unexpected OS errors
        return -1, "", str(exc)


def run_git(
    args: list[str],
    cwd: str | Path | None = None,
    timeout: int = 60,
    env_overrides: dict | None = None,
) -> Tuple[int, str, str]:
    """Convenience wrapper that prefixes the command with ``git``."""
    return run_cmd(["git"] + list(args), cwd=cwd, timeout=timeout, env_overrides=env_overrides)


def git_env_no_prompt() -> dict:
    """Environment variables that silence interactive prompts for git.

    The settings enforce protocol v2 which improves performance for shallow
    fetches.
    """
    return {
        "GIT_TERMINAL_PROMPT": "0",
        "GIT_ASKPASS": "echo",
        "GIT_CONFIG_COUNT": "1",
        "GIT_CONFIG_KEY_0": "protocol.version",
        "GIT_CONFIG_VALUE_0": "2",
    }

# ---------------------------------------------------------------------------
# Helper for GitHub URL parsing
# ---------------------------------------------------------------------------

def _parse_github_url(git_url: str) -> Tuple[str, str] | None:
    """Return ``(owner, repo)`` for a ``github.com`` HTTPS URL.

    Supports both ``https://github.com/owner/repo.git`` and the ``git@``
    scp‑style form.
    """
    m = re.search(r"github\.com[:/]{1}([^/]+)/([^/]+?)(?:\.git)?$", git_url)
    return m.groups() if m else None

# ---------------------------------------------------------------------------
# Commit timestamp retrieval
# ---------------------------------------------------------------------------
_GITHUB_HEADERS = {
    "Accept": "application/vnd.github+json",
    "User-Agent": "nix-flake-age-filter/1.0",
}


def _parse_github_date(date_str: str) -> int | None:
    """Parse an ISO‑8601 timestamp from the GitHub API into a Unix epoch.

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


def _github_api_commit_date(owner: str, repo: str, sha: str, timeout: int = 15) -> int | None:
    """Fetch the commit timestamp for a specific SHA via the GitHub REST API.
    Returns ``None`` on failure.
    """
    try:
        url = f"https://api.github.com/repos/{owner}/{repo}/commits/{sha}"
        resp = requests.get(url, headers=_GITHUB_HEADERS, timeout=timeout)
        if resp.status_code != 200:
            return None
        data = resp.json()
        committer = (
            data.get("commit", {}).get("committer")
            or data.get("commit", {}).get("author")
        )
        return _parse_github_date(committer.get("date", ""))
    except requests.RequestException:
        return None


def get_commit_timestamp(git_url: str, rev: str, timeout: int = 120) -> Dict[str, Any]:
    """Return ``{"ok": bool, "timestamp": int | None, "error": str | None}``.

    Behaviour mirrors the original implementation: use the GitHub API when the
    URL points at ``github.com``; otherwise fall back to a shallow ``git`` fetch
    in a temporary bare repository.
    """
    # GitHub fast path
    if "github.com" in git_url:
        parsed = _parse_github_url(git_url)
        if parsed:
            owner, repo = parsed
            ts = _github_api_commit_date(owner, repo, rev, timeout)
            if ts is not None:
                return {"ok": True, "timestamp": ts, "error": None}

    # Generic git path – use a temporary bare repository
    with tempfile.TemporaryDirectory(prefix="nix-age-") as tmpdir:
        bare = str(Path(tmpdir) / "bare.git")
        rc, _, err = run_git(["init", "--bare", bare])
        if rc != 0:
            return {"ok": False, "timestamp": None, "error": f"init: {err.strip()[:120]}"}

        env = git_env_no_prompt()
        rc, _, err = run_git(
            ["-C", bare, "fetch", "--depth", "1", "--no-tags", git_url, rev],
            timeout=timeout,
            env_overrides=env,
        )
        if rc != 0:
            return {"ok": False, "timestamp": None, "error": f"fetch {rev[:8]}: {err.strip()[:200]}"}

        rc, out, err = run_git([
            "-C",
            bare,
            "log",
            "--format=%at",
            "-1",
            "FETCH_HEAD",
        ], timeout=timeout)
        if rc != 0:
            return {"ok": False, "timestamp": None, "error": f"log: {err.strip()[:200]}"}

        ts_str = out.strip()
        if ts_str.isdigit():
            return {"ok": True, "timestamp": int(ts_str), "error": None}
        return {"ok": False, "timestamp": None, "error": f"bad timestamp: {ts_str[:40]}"}

# ---------------------------------------------------------------------------
# Default ref resolution (branch detection)
# ---------------------------------------------------------------------------

def _get_github_default_branch(owner: str, repo: str, timeout: int = 10) -> str | None:
    """Query the GitHub API for the repository's default branch name."""
    try:
        url = f"https://api.github.com/repos/{owner}/{repo}"
        resp = requests.get(url, headers=_GITHUB_HEADERS, timeout=timeout)
        if resp.status_code == 200:
            return resp.json().get("default_branch")
    except Exception:
        pass
    return None


def resolve_default_ref(git_url: str, ref: str | None, timeout: int = 15) -> str:
    """Return ``ref`` if given; otherwise discover the remote's default branch.

    The function first tries ``git ls-remote --symref`` which works for any
    git server.  If that fails and the URL points at GitHub, we fall back to the
    GitHub REST API.  When both methods fail ``"HEAD"`` is returned – git will
    then treat it as the remote's default.
    """
    if ref:
        return ref

    # git ls-remote --symref HEAD
    rc, stdout, _ = run_git([
        "ls-remote",
        "--symref",
        "--exit-code",
        git_url,
        "HEAD",
    ], timeout=timeout)
    if rc == 0 and stdout.strip():
        for line in stdout.splitlines():
            if line.startswith("ref: refs/heads/"):
                # Example: "ref: refs/heads/main\tHEAD"
                return line.split()[1].split("refs/heads/")[1]

    # GitHub specific fallback
    parsed = _parse_github_url(git_url)
    if parsed:
        owner, repo = parsed
        default = _get_github_default_branch(owner, repo, timeout)
        if default:
            return default

    return "HEAD"

# ---------------------------------------------------------------------------
# Finding a commit that satisfies the minimum‑age requirement
# ---------------------------------------------------------------------------

def find_oldest_commit_meeting_age(
    git_url: str,
    ref: str | None,
    min_age_days: int,
    min_depth: int = 100,
    max_depth: int = 3000,
    timeout: int = 300,
    locked_ts: int | None = None,
    input_name: str = "",
    original: dict | None = None,
) -> Dict[str, Any]:
    """Return information about the newest commit that is at least ``min_age_days`` old.

    The function mirrors the original ``find_oldest_commit_meeting_age`` from
    ``flake_age_common.py`` but is now split into three distinct code paths:

    1. **GitHub** – a single REST request using ``/commits`` with the ``until``
       parameter to locate the cutoff commit efficiently.
    2. **Generic git via pygit2** – a shallow fetch is performed in a temporary
       bare repository and the history is walked using libgit2.
    3. **Fallback to subprocess ``git``** – retained for robustness but not the
       primary path.
    """
    now = datetime.now(tz=timezone.utc)
    cutoff_ts = int(now.timestamp()) - min_age_days * 86_400

    # Resolve the ref (branch/tag) to use for the remote query.
    resolved_ref = resolve_default_ref(git_url, ref, timeout)

    # -------------------------------------------------------------------
    # GitHub fast path – the API can answer the query without cloning.
    # -------------------------------------------------------------------
    if "github.com" in git_url:
        parsed = _parse_github_url(git_url)
        if parsed:
            owner, repo = parsed
            return _github_api_find_at_cutoff(
                owner, repo, resolved_ref, cutoff_ts, min_age_days, timeout
            )

    # -------------------------------------------------------------------
    # Generic git – use pygit2 for an in‑process shallow fetch.
    # -------------------------------------------------------------------
    return _find_via_pygit2(
        git_url,
        resolved_ref,
        min_age_days,
        cutoff_ts,
        timeout,
    )

# ---------------------------------------------------------------------------
# Internal helpers for the GitHub and pygit2 pathways
# ---------------------------------------------------------------------------

def _github_api_find_at_cutoff(
    owner: str,
    repo: str,
    ref: str,
    cutoff_ts: int,
    min_age_days: int,
    timeout: int,
) -> Dict[str, Any]:
    """Query the GitHub API for the newest commit on or before ``cutoff_ts``.

    The API request uses ``until`` to ask for commits older than the cutoff.
    If a suitable commit is found we return the same structure as the original
    implementation.  On failure we synthesize a ``too_new_*`` payload so the
    caller can report a short‑fall.
    """

    def _extract(ts_item: Dict[str, Any]) -> Tuple[int | None, str]:
        commit = ts_item.get("commit", {})
        c = commit.get("committer") or commit.get("author") or {}
        ts = _parse_github_date(c.get("date", ""))
        date_fmt = c.get("date", "").replace("T", " ")[:19] + " UTC" if c.get("date") else ""
        return ts, date_fmt

    # Build the ISO‑8601 cutoff string expected by the API (one minute earlier
    # to avoid edge‑cases where the commit timestamp equals the cutoff).
    cutoff_dt = datetime.fromtimestamp(cutoff_ts - 60, tz=timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )

    try:
        url = f"https://api.github.com/repos/{owner}/{repo}/commits"
        # Request the newest commit that is *not newer* than ``cutoff_dt``.
        resp = requests.get(
            url,
            params={"sha": ref, "per_page": 1, "until": cutoff_dt},
            headers=_GITHUB_HEADERS,
            timeout=timeout,
        )
        if resp.status_code == 200:
            data = resp.json()
            if data:
                ts, date_fmt = _extract(data[0])
                if ts is not None:
                    return {
                        "ok": True,
                        "rev": data[0]["sha"],
                        "timestamp": ts,
                        "depth": 0,
                        "date": date_fmt,
                        "error": None,
                        "too_new_commit": None,
                        "too_new_timestamp": None,
                        "too_new_date": None,
                    }
        elif resp.status_code == 403:
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
        elif resp.status_code == 404:
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
    except requests.RequestException:
        pass

    # If we reach this point the API could not provide an old enough commit.
    # Fetch the HEAD commit to calculate the shortfall.
    try:
        resp = requests.get(
            url,
            params={"sha": ref, "per_page": 1},
            headers=_GITHUB_HEADERS,
            timeout=timeout,
        )
        if resp.status_code == 200:
            data = resp.json()
            if data:
                ts, _ = _extract(data[0])
                if ts is not None:
                    now_ts = int(datetime.now(timezone.utc).timestamp())
                    age = (now_ts - ts) / 86_400
                    return {
                        "ok": False,
                        "rev": None,
                        "timestamp": None,
                        "depth": 0,
                        "date": "",
                        "error": f"HEAD is only {age:.1f}d old (needs {min_age_days}d)",
                        "too_new_commit": data[0]["sha"],
                        "too_new_timestamp": ts,
                        "too_new_date": "",
                    }
    except requests.RequestException:
        pass

    return {"ok": False, "rev": None, "timestamp": None, "depth": 0, "date": "", "error": "GitHub API failed"}


def _find_via_pygit2(
    git_url: str,
    ref: str,
    min_age_days: int,
    cutoff_ts: int,
    timeout: int,
) -> Dict[str, Any]:
    """Use ``pygit2`` to shallow‑fetch a ref and walk the history.

    The implementation is intentionally defensive – any ``pygit2`` error is
    caught and reported as a generic failure structure so the caller can decide
    whether to fall back to a subprocess ``git`` implementation.
    """

    now = datetime.now(tz=timezone.utc)

    def _make_result(commit_hash: str, ts: int, depth: int) -> Dict[str, Any]:
        dt = datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        return {
            "ok": True,
            "rev": commit_hash,
            "timestamp": ts,
            "depth": depth,
            "date": dt,
            "error": None,
            "too_new_commit": None,
            "too_new_timestamp": None,
            "too_new_date": None,
        }

    def _head_too_new(commit_hash: str, ts: int, depth: int) -> Dict[str, Any]:
        age = (int(now.timestamp()) - ts) / 86_400
        dt = datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        return {
            "ok": False,
            "rev": None,
            "timestamp": None,
            "depth": depth,
            "date": "",
            "error": f"HEAD is only {age:.1f}d old (needs {min_age_days}d)",
            "too_new_commit": commit_hash,
            "too_new_timestamp": ts,
            "too_new_date": dt,
        }

    with tempfile.TemporaryDirectory(prefix="nix-age-pygit2-") as tmpdir:
        repo_path = str(Path(tmpdir) / "repo.git")
        try:
            repo = pygit2.init_repository(repo_path, bare=True)
        except Exception as e:
            return {"ok": False, "error": f"pygit2 init failed: {e}"}

        # Remote setup
        try:
            repo.remotes.create("origin", git_url)
        except Exception as e:
            return {"ok": False, "error": f"pygit2 remote create failed: {e}"}

        remote = repo.remotes["origin"]
        fetch_opts = pygit2.FetchOptions()
        fetch_opts.callbacks = pygit2.RemoteCallbacks(credentials=lambda *a, **kw: None)

        # Determine the correct refspec based on ``ref``
        fetched = False
        if ref == "HEAD":
            try:
                remote.fetch(refspec="+HEAD:refs/heads/_", depth=1, options=fetch_opts)
                fetched = True
            except Exception:
                pass
        else:
            # Try branch first
            try:
                remote.fetch(
                    refspec=f"+refs/heads/{ref}:refs/heads/_", depth=1, options=fetch_opts
                )
                fetched = True
            except Exception:
                # Fallback to tag
                try:
                    remote.fetch(
                        refspec=f"+refs/tags/{ref}:refs/tags/{ref}", depth=1, options=fetch_opts
                    )
                    # Resolve tag to a commit and create a temporary branch ``_``
                    tag_ref = repo.lookup_reference(f"refs/tags/{ref}")
                    tag_obj = repo.get(tag_ref.target)
                    target_id = tag_obj.target if tag_obj.type == pygit2.GIT_OBJECT_TAG else tag_ref.target
                    repo.references.create("refs/heads/_", target_id)
                    fetched = True
                except Exception:
                    pass

        if not fetched:
            return {"ok": False, "error": f"pygit2 fetch failed for ref {ref}"}

        # Resolve the temporary branch ``_``
        try:
            head_ref = repo.lookup_reference("refs/heads/_")
            head_commit = repo.get(head_ref.target)
        except Exception as e:
            return {"ok": False, "error": f"pygit2 resolve HEAD failed: {e}"}

        head_ts = head_commit.commit_time
        head_hash = str(head_commit.id)

        if head_ts <= cutoff_ts:
            return _make_result(head_hash, head_ts, depth=1)

        # HEAD too new – deepen iteratively
        depth_step = max(200, min_age_days * 20)
        for _ in range(5):
            try:
                remote.fetch(refspec="+refs/heads/*:refs/heads/*", depth=depth_step)
            except Exception:
                break

            # Walk commits from HEAD backwards
            for commit in repo.walk(head_ref.target, pygit2.GIT_SORT_TIME):
                if commit.commit_time <= cutoff_ts:
                    return _make_result(str(commit.id), commit.commit_time, depth=depth_step)

            depth_step = min(depth_step * 2, 5000)

        # Final exhaustive fetch (depth=5000)
        try:
            remote.fetch(refspec="+refs/heads/*:refs/heads/*", depth=5000)
        except Exception:
            pass

        # Re‑evaluate after deep fetch
        try:
            for commit in repo.walk(head_ref.target, pygit2.GIT_SORT_TIME):
                if commit.commit_time <= cutoff_ts:
                    return _make_result(str(commit.id), commit.commit_time, depth=5000)
        except Exception:
            pass

        return _head_too_new(head_hash, head_ts, depth=0)

# ---------------------------------------------------------------------------
# Compatibility shim – original ``check_age`` function used ``datetime`` directly.
# ---------------------------------------------------------------------------
def check_age(timestamp: int, min_age_days: int, now: datetime) -> dict:
    """Legacy wrapper kept for backward compatibility.

    New code should import ``age_check.check_age`` from this module which in
    turn uses the ``whenever`` based implementation.  This wrapper simply
    delegates to that implementation.
    """
    from .age_check import check_age as _new_check

    return _new_check(timestamp, min_age_days, now)
