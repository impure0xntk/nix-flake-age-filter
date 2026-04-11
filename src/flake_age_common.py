#!/usr/bin/env python3
"""
Common utilities for nix flake age filtering.
Shared between verify and update scripts.
"""

import json
import os
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import pygit2
import requests


class FlakeInput:
    """Represents a flake input (locked or original)."""

    def __init__(self, name: str, locked: dict, original: dict):
        self.name = name
        self.locked = locked
        self.original = original
        self.input_type = locked.get("type", "unknown")
        self.rev = locked.get("rev")
        self.ref = locked.get("ref")

    @property
    def has_rev(self) -> bool:
        return bool(self.rev)

    def to_git_url(self) -> str | None:
        """Build a git HTTPS URL for the input."""
        t = self.input_type
        if t == "github":
            return f"https://github.com/{self.locked.get('owner', '')}/{self.locked.get('repo', '')}.git"
        if t == "gitlab":
            host = self.locked.get("host", "gitlab.com")
            repo = self.locked.get("repo") or self.locked.get("project", "")
            owner = self.locked.get("owner", "")
            if repo and owner:
                return f"https://{host}/{owner}/{repo}.git"
            if repo:
                return f"https://{host}/{repo}.git"
            return None
        if t == "sourcehut":
            owner = self.locked.get("owner", "")
            repo = self.locked.get("repo", self.locked.get("project", ""))
            return f"https://git.sr.ht/~{owner}/{repo}"
        if t == "git":
            return self.locked.get("url") or self.original.get("url")
        if t == "indirect":
            oref = self.original.get("id", "")
            if "/" in oref:
                parts = oref.split("/")
                return f"https://github.com/{parts[0]}/{'/'.join(parts[1:])}.git"
            return None
        if t == "path":
            return None
        return None

    def target_ref(self) -> str | None:
        """Return the ref (branch/tag) that update would pull from."""
        return (
            self.original.get("ref")
            or self.original.get("branch", "")
            or None
        )

    def to_flake_url(self, rev: str | None = None) -> str | None:
        """Build a flake URL like github:owner/repo[/<rev>]."""
        t = self.input_type
        if t == "github":
            owner = self.locked.get("owner", "")
            repo = self.locked.get("repo", "")
            base = f"github:{owner}/{repo}"
            if rev:
                return f"{base}/{rev}"
            return base
        if t == "gitlab":
            host = self.locked.get("host", "gitlab.com")
            owner = self.locked.get("owner", "")
            repo = self.locked.get("repo") or self.locked.get("project", "")
            base = f"gitlab:{host}/{owner}/{repo}" if owner else f"gitlab:{host}/{repo}"
            if rev:
                return f"{base}/{rev}"
            return base
        if t == "sourcehut":
            owner = self.locked.get("owner", "")
            repo = self.locked.get("repo", self.locked.get("project", ""))
            base = f"git+https://git.sr.ht/~{owner}/{repo}"
            if rev:
                return f"{base}?rev={rev}"
            return base
        if t == "git":
            url = self.locked.get("url") or self.original.get("url")
            if not url:
                return None
            if url.startswith("git+"):
                if rev:
                    return f"{url}?rev={rev}"
                return url
            if not url.startswith("git+"):
                if rev:
                    return f"git+{url}?rev={rev}"
                return f"git+{url}"
            return url
        if t == "indirect":
            oref = self.original.get("id", "")
            if rev:
                return f"{oref}/{rev}"
            return oref if "/" in oref else None
        if t == "path":
            return None
        return None


def run_cmd(
    args: list[str],
    cwd: str | Path | None = None,
    timeout: int = 60,
    env_overrides: dict | None = None,
) -> tuple[int, str, str]:
    """Run a command, return (returncode, stdout, stderr)."""
    env = {**os.environ, **(env_overrides or {})}
    try:
        r = subprocess.run(args, capture_output=True, text=True, timeout=timeout, cwd=cwd, env=env)
        return r.returncode, r.stdout, r.stderr
    except subprocess.TimeoutExpired:
        return -1, "", f"{' '.join(args[:3])} timed out after {timeout}s"
    except Exception as e:
        return -1, "", str(e)


def run_git(
    args: list[str],
    cwd: str | Path | None = None,
    timeout: int = 60,
    env_overrides: dict | None = None,
) -> tuple[int, str, str]:
    return run_cmd(["git"] + list(args), cwd=cwd, timeout=timeout, env_overrides=env_overrides)


def git_env_no_prompt() -> dict:
    """Environment for non-interactive git operations."""
    return {
        "GIT_TERMINAL_PROMPT": "0",
        "GIT_ASKPASS": "echo",
        "GIT_CONFIG_COUNT": "1",
        "GIT_CONFIG_KEY_0": "protocol.version",
        "GIT_CONFIG_VALUE_0": "2",
    }


def parse_flake_lock(path: str) -> dict:
    """Parse flake.lock and return the JSON structure."""
    lock_path = Path(path)
    if not lock_path.exists():
        print(f"Error: flake.lock not found at {path}", file=sys.stderr)
        sys.exit(1)
    return json.loads(lock_path.read_text())


def extract_locked_inputs(lock_data: dict) -> list[FlakeInput]:
    """Extract direct root inputs from flake.lock."""
    nodes = lock_data.get("nodes", {})
    root_node = nodes.get("root", {})
    root_inputs_raw = root_node.get("inputs", {})

    inputs = []
    if isinstance(root_inputs_raw, dict):
        # Keys are input attribute names (e.g. "nixpkgs"), values are node names (e.g. "nixpkgs_2")
        for name, target in root_inputs_raw.items():
            if isinstance(target, str):
                node_name = target
            elif isinstance(target, list) and len(target) > 0:
                node_name = target[0]
            else:
                continue

            node_data = nodes.get(node_name)
            if not node_data or "locked" not in node_data:
                continue
            inputs.append(FlakeInput(
                name=name,
                locked=node_data["locked"],
                original=node_data.get("original", {}),
            ))
    elif isinstance(root_inputs_raw, list):
        for node_name in root_inputs_raw:
            node_data = nodes.get(node_name)
            if not node_data or "locked" not in node_data:
                continue
            inputs.append(FlakeInput(
                name=node_name,
                locked=node_data["locked"],
                original=node_data.get("original", {}),
            ))
    else:
        # Fallback: use all non-root nodes
        for name, node_data in sorted(nodes.items()):
            if name == "root" or "locked" not in node_data:
                continue
            inputs.append(FlakeInput(
                name=name,
                locked=node_data["locked"],
                original=node_data.get("original", {}),
            ))
    return inputs


def get_commit_timestamp(git_url: str, rev: str, timeout: int = 120) -> dict:
    """
    Fetch commit timestamp.  Lightweight: uses GitHub API when possible,
    falls back to git fetch only for non-GitHub repos.
    Returns {"ok": bool, "timestamp": int|None, "error": str|None}.
    """
    # ── GitHub: single API request ──────────────────────────
    if "github.com" in git_url:
        parsed = _parse_github_url(git_url)
        if parsed:
            owner, repo_name = parsed
            ts = _github_api_commit_date(owner, repo_name, rev, timeout)
            if ts is not None:
                return {"ok": True, "timestamp": ts, "error": None}

    # ── Generic git: bare repo fetch + cat-file ─────────────
    with tempfile.TemporaryDirectory(prefix="nix-age-") as tmpdir:
        bare = str(Path(tmpdir) / "bare.git")
        rc, _, stderr = run_git(["init", "--bare", bare])
        if rc != 0:
            return {"ok": False, "timestamp": None, "error": f"init: {stderr.strip()[:120]}"}

        env = git_env_no_prompt()
        # Single-rev fetch (minimal data transfer)
        rc, _, stderr = run_git(
            ["-C", bare, "fetch", "--depth", "1", "--no-tags", git_url, rev],
            timeout=timeout, env_overrides=env,
        )
        if rc != 0:
            return {"ok": False, "timestamp": None, "error": f"fetch {rev[:8]}: {stderr.strip()[:200]}"}

        rc, stdout, stderr = run_git(
            ["-C", bare, "log", "--format=%at", "-1", "FETCH_HEAD"],
            timeout=timeout,
        )
        if rc != 0:
            return {"ok": False, "timestamp": None, "error": f"log: {stderr.strip()[:200]}"}

        ts_str = stdout.strip()
        if ts_str.isdigit():
            return {"ok": True, "timestamp": int(ts_str), "error": None}
        return {"ok": False, "timestamp": None, "error": f"bad timestamp: {ts_str[:40]}"}


def _is_nixpkgs(name: str, git_url: str, original: dict) -> bool:
    """Detect if this input is nixpkgs by name, URL, or flake ID."""
    name_lower = name.lower()
    if "nixpkgs" in name_lower or "nixos" in name_lower:
        return True
    url_check = git_url.lower()
    if "nixpkgs" in url_check or ("nixos" in url_check and "nixpkgs" in url_check):
        return True
    flake_id = original.get("id", "").lower() or original.get("owner", "").lower()
    if "nixpkgs" in flake_id:
        return True
    return False


def _get_github_default_branch(owner: str, repo: str, timeout: int = 10) -> str | None:
    """Fetch the default branch for a GitHub repository."""
    try:
        url = f"https://api.github.com/repos/{owner}/{repo}"
        resp = requests.get(url, headers=_GITHUB_HEADERS, timeout=timeout)
        if resp.status_code == 200:
            return resp.json().get("default_branch")
    except Exception:
        pass
    return None


def resolve_default_ref(git_url: str, ref: str | None, timeout: int = 15) -> str:
    """Resolve the effective ref for a remote, falling back to the remote's default branch.

    If ``ref`` is provided, return it as-is.
    Otherwise, try ``git ls-remote --symref <url> HEAD`` to discover the remote's
    default branch.  For GitHub repos, fall back to the REST API.
    If all else fails, return ``"HEAD"`` so git operations use the remote default.
    """
    if ref:
        return ref

    # Try git ls-remote --symref (works for any git remote)
    rc, stdout, _ = run_git(
        ["ls-remote", "--symref", "--exit-code", git_url, "HEAD"],
        timeout=timeout,
    )
    if rc == 0 and stdout.strip():
        # Output format:
        #   ref: refs/heads/main\tHEAD\n<sha>\tHEAD
        # Parse by splitting on tab, then extracting branch name
        for line in stdout.splitlines():
            if line.startswith("ref: refs/heads/"):
                # line is: "ref: refs/heads/main\tHEAD"
                ref_part = line.split("\t")[0]  # "ref: refs/heads/main"
                if ref_part.startswith("ref: refs/heads/"):
                    return ref_part[len("ref: refs/heads/"):]

    # GitHub fallback
    parsed = _parse_github_url(git_url)
    if parsed:
        owner, repo_name = parsed
        default_branch = _get_github_default_branch(owner, repo_name, timeout)
        if default_branch:
            return default_branch

    return "HEAD"


def find_oldest_commit_meeting_age(git_url: str, ref: str | None, min_age_days: int,
                                    min_depth: int = 100, max_depth: int = 3000,
                                    timeout: int = 300,
                                    locked_ts: int | None = None,
                                    input_name: str = "",
                                    original: dict | None = None) -> dict:
    """
    Find the newest commit >= min_age_days on the target branch.

    If ``ref`` is None, the remote's default branch is auto-detected via
    ``resolve_default_ref``.

    Priority:
    1. If locked_ts is provided (existing flake.lock timestamp) and it's old
       enough, return it immediately — no network needed.
    2. GitHub: REST API /repos/{owner}/{repo}/commits (no clone)
    3. Others: git fetch + log in a bare repo (unavoidable without API)

    nixpkgs is treated the same as any other input — no special bypass.
    """
    now = datetime.now(tz=timezone.utc)

    cutoff_ts = int(now.timestamp()) - min_age_days * 86400

    # Resolve the target ref, falling back to the remote's default branch
    resolved_ref = resolve_default_ref(git_url, ref, timeout)

    # Note: We used to short-circuit here if locked_ts < cutoff_ts, but that prevented
    # finding a *newer* commit that also satisfies the age requirement.
    # We always need to check the remote to find the newest valid commit.

    # ── GitHub: REST API (no clone, early cutoff) ─────────────
    if "github.com" in git_url:
        parsed = _parse_github_url(git_url)
        if parsed:
            owner, repo_name = parsed
            return _github_api_find_at_cutoff(
                owner, repo_name, resolved_ref, cutoff_ts, min_age_days, timeout
            )

    # ── Generic git: pygit2 (libgit2) ───────────────────────────────
    return _find_via_pygit2(git_url, resolved_ref, min_age_days, cutoff_ts, timeout)


def _parse_github_url(git_url: str) -> tuple[str, str] | None:
    import re
    m = re.search(r'github\.com[:/]([^/]+)/([^/]+?)(?:\.git)?$', git_url)
    return m.groups() if m else None


_GITHUB_HEADERS = {
    "Accept": "application/vnd.github+json",
    "User-Agent": "nix-flake-age-filter/1.0",
}


def _parse_github_date(date_str: str) -> int | None:
    """Parse ISO 8601 date from GitHub API to unix timestamp."""
    if not date_str or not date_str.endswith("Z"):
        return None
    try:
        dt = datetime(
            int(date_str[:4]), int(date_str[5:7]), int(date_str[8:10]),
            int(date_str[11:13]), int(date_str[14:16]), int(date_str[17:19]),
            tzinfo=timezone.utc,
        )
        return int(dt.timestamp())
    except Exception:
        return None


def _github_api_commit_date(owner: str, repo: str, sha: str,
                             timeout: int = 15) -> int | None:
    """GET /repos/{owner}/{repo}/commits/{sha} — single commit lookup via requests."""
    try:
        url = f"https://api.github.com/repos/{owner}/{repo}/commits/{sha}"
        resp = requests.get(url, headers=_GITHUB_HEADERS, timeout=timeout)
        if resp.status_code != 200:
            return None
        body = resp.json()
        c = body.get("commit", {}).get("committer") or body.get("commit", {}).get("author")
        return _parse_github_date((c or {}).get("date", ""))
    except requests.RequestException:
        return None


def _github_api_find_at_cutoff(
    owner: str, repo: str, ref: str,
    cutoff_ts: int, min_age_days: int, timeout: int,
) -> dict:
    """
    GitHub API: find newest commit authored on or before `cutoff_ts` via requests.
    Uses `until` query parameter to find the closest old-enough commit in 1 request.
    """
    def get_ts_and_date(item):
        c = item.get("commit", {})
        committer = (c.get("committer") or c.get("author") or {})
        ts = _parse_github_date(committer.get("date", ""))
        date_str = committer.get("date", "")
        if date_str and date_str.endswith("Z"):
            date_fmt = date_str[:19].replace("T", " ") + " UTC"
        else:
            date_fmt = ""
        return ts, date_fmt

    cutoff_dt = datetime.fromtimestamp(cutoff_ts - 60, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    try:
        # 1. Find newest commit <= cutoff_ts
        url = f"https://api.github.com/repos/{owner}/{repo}/commits"
        resp = requests.get(url, params={"sha": ref, "per_page": 1, "until": cutoff_dt},
                            headers=_GITHUB_HEADERS, timeout=timeout)
        if resp.status_code == 200:
            body = resp.json()
            if body:
                ts, date_fmt = get_ts_and_date(body[0])
                if ts is not None:
                    return {
                        "ok": True, "rev": body[0]["sha"], "timestamp": ts,
                        "depth": 0, "date": date_fmt,
                        "error": None, "too_new_commit": None,
                        "too_new_timestamp": None, "too_new_date": None,
                    }
        elif resp.status_code == 403:
            return {"ok": False, "rev": None, "timestamp": None, "depth": 0, "date": "",
                    "error": "GitHub API rate limited (403)", "fallback": True}
        elif resp.status_code == 404:
            return {"ok": False, "rev": None, "timestamp": None, "depth": 0, "date": "",
                    "error": "ref not found"}

        # 2. No commits before cutoff — get HEAD to report shortfall
        resp = requests.get(url, params={"sha": ref, "per_page": 1},
                            headers=_GITHUB_HEADERS, timeout=timeout)
        if resp.status_code == 200:
            body = resp.json()
            if body:
                newest_ts, _ = get_ts_and_date(body[0])
                if newest_ts is not None:
                    now_ts = int(datetime.now(timezone.utc).timestamp())
                    age = (now_ts - newest_ts) / 86400
                    return {
                        "ok": False, "rev": None, "timestamp": None, "depth": 0, "date": "",
                        "error": f"HEAD is only {age:.1f}d old (needs {min_age_days}d)",
                        "too_new_commit": body[0]["sha"],
                        "too_new_timestamp": newest_ts,
                        "too_new_date": "",
                    }
    except requests.RequestException:
        pass

    return {"ok": False, "rev": None, "timestamp": None, "depth": 0, "date": "",
            "error": "GitHub API failed"}


def _find_via_pygit2(
    git_url: str, ref: str, min_age_days: int, cutoff_ts: int, timeout: int,
    use_git_fallback: bool = False,
) -> dict:
    """
    Fallback for non-GitHub hosts using pygit2 (libgit2).
    Replaces subprocess git with in-process operations — no git binary needed.
    Falls back to subprocess git if pygit2 fails.
    ``ref`` should already be resolved by ``resolve_default_ref``.
    """
    now = datetime.now(tz=timezone.utc)

    def _result(commit_hash: str, ts: int, depth: int) -> dict:
        dt_str = datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        return {
            "ok": True, "rev": commit_hash, "timestamp": ts, "depth": depth,
            "date": dt_str,
            "error": None,
            "too_new_commit": None, "too_new_timestamp": None, "too_new_date": None,
        }

    def _head_too_new(commit_hash: str, ts: int, depth: int) -> dict:
        age = (int(now.timestamp()) - ts) / 86400
        dt_str = datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        return {
            "ok": False, "rev": None, "timestamp": None, "depth": depth, "date": "",
            "error": f"HEAD is only {age:.1f}d old (needs {min_age_days}d)",
            "too_new_commit": commit_hash,
            "too_new_timestamp": ts,
            "too_new_date": dt_str,
            "fallback": True,
        }

    with tempfile.TemporaryDirectory(prefix="nix-age-pygit2-") as tmpdir:
        repo_dir = str(Path(tmpdir) / "r.git")

        # ── Step 1: Initialize bare repository ──────────────────────
        try:
            repo = pygit2.init_repository(repo_dir, bare=True)
        except pygit2.GitError as e:
            return _fail(f"pygit2 init: {e}")

        # Add remote
        try:
            repo.remotes.create("origin", git_url)
        except pygit2.GitError as e:
            return _fail(f"pygit2 remote create: {e}")

        remote = repo.remotes["origin"]
        # Suppress callbacks (no auth prompts)
        fetch_opts = pygit2.FetchOptions()
        fetch_opts.callbacks = pygit2.RemoteCallbacks(credentials=lambda *args: None)

        # ── Step 2: Shallow fetch the resolved ref ──────────────────
        # ref may be a branch name or "HEAD"
        fetch_ok = False
        if ref == "HEAD":
            # Fetch the remote's default branch directly
            try:
                remote.fetch(refspec="+HEAD:refs/heads/_", depth=1, options=fetch_opts)
                fetch_ok = True
            except pygit2.GitError:
                pass
        else:
            # Try as branch first
            try:
                remote.fetch(refspec=f"+refs/heads/{ref}:refs/heads/_", depth=1, options=fetch_opts)
                fetch_ok = True
            except pygit2.GitError:
                # Try as tag
                try:
                    remote.fetch(refspec=f"+refs/tags/{ref}:refs/tags/{ref}", depth=1, options=fetch_opts)
                    # Map tag ref to _ for unified walk
                    try:
                        tag_ref = repo.lookup_reference(f"refs/tags/{ref}")
                        tag = repo.get(tag_ref.target)
                        if tag.type == pygit2.GIT_OBJECT_TAG:
                            target_id = tag.target
                        else:
                            target_id = tag_ref.target
                        repo.references.create("refs/heads/_", target_id)
                        fetch_ok = True
                    except (pygit2.GitError, KeyError):
                        pass
                except pygit2.GitError:
                    pass

        if not fetch_ok:
            return _fail(f"pygit2 fetch {ref}: all refspecs failed")

        # ── Step 3: Resolve _ and get HEAD commit timestamp ─────────
        try:
            head_ref = repo.lookup_reference("refs/heads/_")
            head_commit = repo.get(head_ref.target)
        except (pygit2.GitError, KeyError) as e:
            return _fail(f"pygit2 resolve HEAD: {e}")

        head_ts = head_commit.commit_time
        head_hash = str(head_commit.id)

        # HEAD is old enough — done
        if head_ts <= cutoff_ts:
            return _result(head_hash, head_ts, depth=1)

        # ── Step 3: HEAD too new — deepen and search ───────────────
        depth_step = max(200, min_age_days * 20)

        for attempt in range(5):
            try:
                remote.fetch(refspec="+refs/heads/*:refs/heads/*", depth=depth_step)
            except pygit2.GitError:
                break

            # Walk commits from HEAD, stop at cutoff
            found_commit = None
            count = 0
            try:
                for commit in repo.walk(head_ref.target, pygit2.GIT_SORT_TIME):
                    count += 1
                    if commit.commit_time <= cutoff_ts:
                        found_commit = commit
                        break
            except pygit2.GitError:
                break

            if found_commit:
                return _result(str(found_commit.id), found_commit.commit_time, depth=depth_step)

            if count == 0:
                break

            depth_step = min(depth_step * 2, 5000)

        # ── Exhaustive: deep fetch (depth=5000) ────────────────────
        try:
            remote.fetch(refspec="+refs/heads/*:refs/heads/*", depth=5000)
        except pygit2.GitError:
            pass

        # Re-check head after deepen
        try:
            head_ref = repo.lookup_reference("refs/heads/_")
            for commit in repo.walk(head_ref.target, pygit2.GIT_SORT_TIME):
                if commit.commit_time <= cutoff_ts:
                    return _result(str(commit.id), commit.commit_time, depth=5000)
        except (pygit2.GitError, KeyError):
            pass

        # Return HEAD too-new info
        return _head_too_new(head_hash, head_ts, depth=0)


def _fail(msg: str) -> dict:
    return {
        "ok": False, "rev": None, "timestamp": None, "depth": 0, "date": "",
        "error": msg,
        "too_new_commit": None, "too_new_timestamp": None, "too_new_date": None,
    }


def check_age(timestamp: int, min_age_days: int, now: datetime) -> dict:
    """Check if commit age meets minimum requirement."""
    commit_time = datetime.fromtimestamp(timestamp, tz=timezone.utc)
    age_days = int((now - commit_time).total_seconds() / 86400)
    return {
        "ok": age_days >= min_age_days,
        "age_days": age_days,
        "commit_date": commit_time.strftime("%Y-%m-%d %H:%M UTC"),
        "error": None if age_days >= min_age_days else f"only {age_days}d old (minimum: {min_age_days}d)",
    }


def format_duration(days: int) -> str:
    """Format days into a human-readable duration."""
    if days < 0:
        return f"{days}d (future)"
    if days < 7:
        return f"{days}d"
    w = days // 7
    r = days % 7
    if w < 52:
        return f"{w}w {r}d" if r else f"{w}w"
    y = w // 52
    wr = w % 52
    return f"{y}y {wr}w"
