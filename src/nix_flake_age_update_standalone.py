#!/usr/bin/env python3
"""
Standalone nix flake age update - No external dependencies.

A minimal implementation that only uses Python stdlib.
Uses git CLI for all operations (no pygit2, no rich, no requests).

Usage:
    python3 nix_flake_age_update_standalone.py --min-age 7
    python3 nix_flake_age_update_standalone.py --min-age 7 nixpkgs --dry-run
"""

import argparse
import json
import os
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


# ============================================================================
# Core Classes
# ============================================================================

@dataclass(frozen=True)
class FlakeInput:
    """Represents a flake input."""
    name: str
    locked: dict[str, Any]
    original: dict[str, Any]
    
    @property
    def input_type(self) -> str:
        return self.locked.get("type", "unknown")
    
    @property
    def rev(self) -> str | None:
        return self.locked.get("rev")
    
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


# ============================================================================
# Git Operations (stdlib only)
# ============================================================================

def run_cmd(
    args: list[str],
    cwd: str | Path | None = None,
    timeout: int = 60,
    env_overrides: dict | None = None,
) -> tuple[int, str, str]:
    """Run a command, return (returncode, stdout, stderr)."""
    env = {**os.environ, **(env_overrides or {})}
    try:
        r = subprocess.run(
            args, capture_output=True, text=True, timeout=timeout, cwd=cwd, env=env
        )
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
    """Run a git command."""
    return run_cmd(["git"] + list(args), cwd=cwd, timeout=timeout, env_overrides=env_overrides)


def git_env_no_prompt() -> dict[str, str]:
    """Environment for non-interactive git operations."""
    return {
        "GIT_TERMINAL_PROMPT": "0",
        "GIT_ASKPASS": "echo",
        "GIT_CONFIG_COUNT": "1",
        "GIT_CONFIG_KEY_0": "protocol.version",
        "GIT_CONFIG_VALUE_0": "2",
    }


def resolve_default_ref(git_url: str, ref: str | None, timeout: int = 15) -> str:
    """Resolve the effective ref for a remote.
    
    Returns the branch name (e.g., 'main', 'master') or 'HEAD' if unresolved.
    The return value is a simple branch name, NOT a full refspec.
    """
    if ref:
        return ref
    
    rc, stdout, _ = run_git(
        ["ls-remote", "--symref", "--exit-code", git_url, "HEAD"],
        timeout=timeout,
    )
    if rc == 0 and stdout.strip():
        # Output format:
        #   ref: refs/heads/main	HEAD
        #   <sha>	HEAD
        # We need to extract just the branch name 'main'
        for line in stdout.splitlines():
            if line.startswith("ref: refs/heads/"):
                # line is: "ref: refs/heads/main\tHEAD" or "ref: refs/heads/main"
                # Strip everything after whitespace and extract branch name
                ref_part = line.split()[0] if line.split() else line  # "ref:refs/heads/main" or "ref:"
                if ref_part.startswith("ref:refs/heads/"):
                    return ref_part[len("ref:refs/heads/"):]
                elif ref_part.startswith("ref: refs/heads/"):
                    return ref_part[len("ref: refs/heads/"):]
    
    return "HEAD"


def get_commit_timestamp_git(git_url: str, rev: str, timeout: int = 120) -> dict:
    """Fetch commit timestamp using git CLI (bare repo fetch)."""
    with tempfile.TemporaryDirectory(prefix="nix-age-") as tmpdir:
        bare = str(Path(tmpdir) / "bare.git")
        rc, _, stderr = run_git(["init", "--bare", bare])
        if rc != 0:
            return {"ok": False, "error": f"init: {stderr.strip()[:120]}"}
        
        env = git_env_no_prompt()
        rc, _, stderr = run_git(
            ["-C", bare, "fetch", "--depth", "1", "--no-tags", git_url, rev],
            timeout=timeout, env_overrides=env,
        )
        if rc != 0:
            return {"ok": False, "error": f"fetch {rev[:8]}: {stderr.strip()[:200]}"}
        
        rc, stdout, stderr = run_git(
            ["-C", bare, "log", "--format=%at", "-1", "FETCH_HEAD"],
            timeout=timeout,
        )
        if rc != 0:
            return {"ok": False, "error": f"log: {stderr.strip()[:200]}"}
        
        ts_str = stdout.strip()
        if ts_str.isdigit():
            return {"ok": True, "timestamp": int(ts_str)}
        return {"ok": False, "error": f"bad timestamp: {ts_str[:40]}"}


def find_oldest_commit_meeting_age(
    git_url: str,
    ref: str | None,
    min_age_days: int,
    min_depth: int = 100,
    max_depth: int = 3000,
    timeout: int = 300,
) -> dict:
    """Find the newest commit >= min_age_days on the target branch."""
    now = datetime.now(tz=timezone.utc)
    cutoff_ts = int(now.timestamp()) - min_age_days * 86400
    
    resolved_ref = resolve_default_ref(git_url, ref, timeout)
    
    with tempfile.TemporaryDirectory(prefix="nix-age-walk-") as tmpdir:
        bare = str(Path(tmpdir) / "repo.git")
        
        # Initialize bare repo
        rc, _, stderr = run_git(["init", "--bare", bare])
        if rc != 0:
            return {"ok": False, "error": f"init: {stderr.strip()[:120]}"}
        
        env = git_env_no_prompt()
        
        # Build proper refspec for fetch
        # For branches: refs/heads/<branch>
        # For HEAD: HEAD (no refspec conversion needed)
        if resolved_ref == "HEAD":
            refspec = "HEAD"
        elif resolved_ref.startswith("refs/"):
            refspec = resolved_ref
        else:
            # Assume it's a branch name
            refspec = f"refs/heads/{resolved_ref}"
        
        # Shallow fetch with proper refspec
        rc, _, stderr = run_git(
            ["-C", bare, "fetch", "--depth", str(min_depth), "--no-tags", git_url, refspec],
            timeout=timeout, env_overrides=env,
        )
        if rc != 0:
            return {"ok": False, "error": f"fetch {refspec}: {stderr.strip()[:200]}"}
        
        # Get HEAD commit info
        rc, stdout, _ = run_git(["-C", bare, "log", "-1", "--format=%H %at", "FETCH_HEAD"])
        if rc != 0:
            return {"ok": False, "error": "failed to get HEAD"}
        
        parts = stdout.strip().split()
        if len(parts) < 2:
            return {"ok": False, "error": "malformed log output"}
        
        head_rev = parts[0]
        head_ts = int(parts[1])
        
        # Check if HEAD is old enough
        if head_ts <= cutoff_ts:
            dt_str = datetime.fromtimestamp(head_ts, tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
            return {
                "ok": True,
                "rev": head_rev,
                "timestamp": head_ts,
                "date": dt_str,
                "depth": 1,
            }
        
        # HEAD is too new — need to walk history
        # Fetch deeper
        depth = min_depth
        while depth < max_depth:
            # Deepen the fetch
            rc, _, _ = run_git(
                ["-C", bare, "fetch", "--deepen", str(depth)],
                timeout=timeout, env_overrides=env,
            )
            if rc != 0:
                break
            
            # Walk commits
            rc, stdout, _ = run_git(
                ["-C", bare, "log", "--format=%H %at", "FETCH_HEAD"],
                timeout=timeout,
            )
            if rc != 0:
                break
            
            for line in stdout.strip().splitlines():
                parts = line.split()
                if len(parts) >= 2:
                    commit_rev = parts[0]
                    commit_ts = int(parts[1])
                    if commit_ts <= cutoff_ts:
                        dt_str = datetime.fromtimestamp(commit_ts, tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
                        return {
                            "ok": True,
                            "rev": commit_rev,
                            "timestamp": commit_ts,
                            "date": dt_str,
                            "depth": depth,
                        }
            
            depth = min(depth * 2, max_depth)
        
        # All commits too new
        age = (int(now.timestamp()) - head_ts) / 86400
        dt_str = datetime.fromtimestamp(head_ts, tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        return {
            "ok": False,
            "error": f"HEAD is only {age:.1f}d old (needs {min_age_days}d)",
            "too_new_commit": head_rev,
            "too_new_timestamp": head_ts,
            "too_new_date": dt_str,
        }


# ============================================================================
# Flake Lock Parser
# ============================================================================

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
    
    inputs: list[FlakeInput] = []
    
    if isinstance(root_inputs_raw, dict):
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
        for name, node_data in sorted(nodes.items()):
            if name == "root" or "locked" not in node_data:
                continue
            inputs.append(FlakeInput(
                name=name,
                locked=node_data["locked"],
                original=node_data.get("original", {}),
            ))
    
    return inputs


# ============================================================================
# Utilities
# ============================================================================

def check_age(timestamp: int, min_age_days: int, now: datetime) -> dict:
    """Check if commit age meets minimum requirement."""
    commit_time = datetime.fromtimestamp(timestamp, tz=timezone.utc)
    age_days = int((now - commit_time).total_seconds() / 86400)
    return {
        "ok": age_days >= min_age_days,
        "age_days": age_days,
        "commit_date": commit_time.strftime("%Y-%m-%d %H:%M UTC"),
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


def build_override_url(inp: FlakeInput, rev: str) -> str | None:
    """Build a flake URL with a pinned revision for --override-input."""
    t = inp.input_type
    if t == "github":
        owner = inp.locked.get("owner", "")
        repo = inp.locked.get("repo", "")
        return f"github:{owner}/{repo}/{rev}"
    if t == "gitlab":
        host = inp.locked.get("host", "gitlab.com")
        owner = inp.locked.get("owner", "")
        repo = inp.locked.get("repo") or inp.locked.get("project", "")
        base = f"gitlab:{host}/{owner}/{repo}" if owner else f"gitlab:{host}/{repo}"
        return f"{base}/{rev}"
    if t == "sourcehut":
        owner = inp.locked.get("owner", "")
        repo = inp.locked.get("repo", inp.locked.get("project", ""))
        return f"git+https://git.sr.ht/~{owner}/{repo}?rev={rev}"
    if t == "git":
        url = inp.locked.get("url") or inp.original.get("url")
        if not url:
            return None
        if url.startswith("git+"):
            return f"{url}?rev={rev}"
        return f"git+{url}?rev={rev}"
    if t == "indirect":
        oref = inp.original.get("id", "")
        if "/" in oref:
            return f"{oref}/{rev}"
        return None
    return None


# ============================================================================
# Core Logic
# ============================================================================

def find_suitable_commit(inp: FlakeInput, min_age_days: int, timeout: int) -> dict:
    """Find the newest commit >= min_age_days on the target branch."""
    git_url = inp.to_git_url()
    if not git_url:
        return {"ok": False, "reason": f"unsupported type: {inp.input_type}"}
    
    ref = inp.target_ref()
    
    result = find_oldest_commit_meeting_age(
        git_url, ref, min_age_days,
        min_depth=100, max_depth=1000,
        timeout=timeout,
    )
    
    if result.get("too_new_commit"):
        ts = result["too_new_timestamp"]
        now = datetime.now(tz=timezone.utc)
        cutoff = int(now.timestamp()) - min_age_days * 86400
        shortfall = (ts - cutoff) / 86400
        return {
            "ok": False,
            "reason": "all commits too new",
            "latest_rev": result["too_new_commit"],
            "shortfall_days": round(shortfall, 1),
            "latest_date": result.get("too_new_date", "?"),
        }
    
    if not result.get("ok"):
        return {"ok": False, "reason": result.get("error", "unknown")}
    
    rev = result["rev"]
    ts = result["timestamp"]
    now = datetime.now(tz=timezone.utc)
    age = check_age(ts, min_age_days, now)
    
    return {
        "ok": True,
        "rev": rev,
        "timestamp": ts,
        "age_days": age["age_days"],
        "commit_date": age["commit_date"],
    }


def run_nix_flake_update(
    input_name: str,
    override_url: str,
    flake_lock_dir: str,
    dry_run: bool,
    timeout: int,
) -> dict:
    """Run `nix flake update <input> --override-input <input> <url>`."""
    nix_bin = shutil.which("nix") or "nix"
    cmd = [
        nix_bin,
        "--extra-experimental-features", "nix-command flakes",
        "flake", "update",
        input_name,
        "--override-input", input_name, override_url,
    ]
    if dry_run:
        cmd.append("--no-write-lock-file")
    
    rc, stdout, stderr = run_cmd(cmd, cwd=flake_lock_dir, timeout=timeout)
    if rc != 0:
        return {"ok": False, "error": stderr.strip()[:400]}
    return {"ok": True, "stdout": stdout.strip()}


import shutil


# ============================================================================
# Main CLI
# ============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="Update flake inputs with min-release-age guard (standalone)",
    )
    parser.add_argument(
        "inputs", nargs="*",
        help="Specific inputs to update (default: all)",
    )
    parser.add_argument(
        "--flake-lock", default="flake.lock",
        help="Path to flake.lock (default: ./flake.lock)",
    )
    parser.add_argument(
        "--min-age", type=int, required=True,
        help="Minimum commit age in days",
    )
    parser.add_argument(
        "--timeout", type=int, default=120,
        help="Timeout per git operation in seconds",
    )
    parser.add_argument(
        "--exclude", nargs="*", default=["self"], metavar="INPUT",
        help="Inputs to skip",
    )
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--json", action="store_true", dest="json_output")
    parser.add_argument("--verbose", "-v", action="store_true")
    
    args = parser.parse_args()
    
    flake_lock_path = Path(args.flake_lock)
    flake_dir = str(flake_lock_path.parent.resolve())
    
    if not flake_lock_path.exists():
        print(f"Error: flake.lock not found: {flake_lock_path}", file=sys.stderr)
        sys.exit(1)
    
    lock_data = parse_flake_lock(str(flake_lock_path))
    inputs = extract_locked_inputs(lock_data)
    
    if not inputs:
        print("No locked inputs found.", file=sys.stderr)
        sys.exit(0)
    
    # Filter
    if args.inputs:
        inputs = [i for i in inputs if i.name in args.inputs]
    inputs = [i for i in inputs if i.name not in args.exclude]
    
    if not inputs:
        print("No inputs match after filtering.", file=sys.stderr)
        if args.json_output:
            print(json.dumps([], indent=2))
        sys.exit(0)
    
    if not args.json_output:
        print(f"Checking {len(inputs)} input(s) - min-age: {args.min_age}d", file=sys.stderr)
    
    results: list[dict] = []
    
    for inp in inputs:
        git_url = inp.to_git_url()
        if not git_url:
            results.append({"name": inp.name, "status": "SKIP", "reason": "no git URL"})
            if not args.json_output:
                print(f"  SKIP {inp.name}  no git URL", file=sys.stderr)
            continue
        
        if args.verbose and not args.json_output:
            print(f"  -> {inp.name}: {git_url} ref={inp.target_ref() or 'default'}", file=sys.stderr)
        
        info = find_suitable_commit(inp, args.min_age, args.timeout)
        
        if not info.get("ok"):
            if "latest_rev" in info:
                results.append({
                    "name": inp.name,
                    "status": "WAIT",
                    "reason": f"all commits < {args.min_age}d",
                    "latest_rev": info["latest_rev"][:12],
                    "shortfall_days": info["shortfall_days"],
                    "latest_date": info.get("latest_date", ""),
                })
                if not args.json_output:
                    print(f"  WAIT {inp.name}  {info['latest_rev'][:12]} "
                          f"too new (needs ~{info['shortfall_days']}d more)", file=sys.stderr)
            else:
                results.append({
                    "name": inp.name,
                    "status": "ERROR",
                    "reason": info.get("reason", ""),
                })
                if not args.json_output:
                    print(f"  ERR! {inp.name}  {info.get('reason', '')}", file=sys.stderr)
            continue
        
        # Check if already at target
        if inp.rev and inp.rev == info["rev"]:
            results.append({
                "name": inp.name,
                "status": "OK",
                "reason": "already at target",
                "current_rev": inp.rev[:12],
                "age_days": info["age_days"],
                "commit_date": info["commit_date"],
            })
            if not args.json_output:
                print(f"  OK   {inp.name}  {inp.rev[:12]}  "
                      f"age={format_duration(info['age_days'])}  {info['commit_date']}", file=sys.stderr)
            continue
        
        # Build override URL
        override_url = build_override_url(inp, info["rev"])
        if not override_url:
            results.append({
                "name": inp.name,
                "status": "ERROR",
                "reason": "cannot build override URL",
            })
            if not args.json_output:
                print(f"  ERR! {inp.name}  cannot build override URL", file=sys.stderr)
            continue
        
        if not args.json_output:
            label = "DRY-RUN" if args.dry_run else "UPDATE"
            print(f"  {label:>7} {inp.name}  -> {info['rev'][:12]}  "
                  f"age={format_duration(info['age_days'])}  {info['commit_date']}", file=sys.stderr)
            if not args.dry_run:
                print(f"         nix flake update {inp.name} --override-input {inp.name} {override_url}",
                      file=sys.stderr)
        
        # Run nix flake update
        if not args.dry_run:
            nix_result = run_nix_flake_update(
                inp.name, override_url, flake_dir,
                dry_run=args.dry_run, timeout=max(args.timeout, 300),
            )
            if not nix_result["ok"]:
                results.append({
                    "name": inp.name,
                    "status": "ERROR",
                    "reason": f"nix failed: {nix_result['error']}",
                    "target_rev": info["rev"][:12],
                })
                if not args.json_output:
                    print(f"  ERR! {inp.name}  nix failed: {nix_result['error'][:80]}", file=sys.stderr)
                continue
            results.append({
                "name": inp.name,
                "status": "UPDATED",
                "old_rev": inp.rev,
                "new_rev": info["rev"],
                "age_days": info["age_days"],
                "commit_date": info["commit_date"],
            })
        else:
            results.append({
                "name": inp.name,
                "status": "WOULD-UPDATE",
                "old_rev": inp.rev,
                "new_rev": info["rev"],
                "override_url": override_url,
                "age_days": info["age_days"],
                "commit_date": info["commit_date"],
            })
    
    # Summary
    if not args.json_output:
        updated = sum(1 for r in results if r["status"] == "UPDATED")
        would = sum(1 for r in results if r["status"] == "WOULD-UPDATE")
        ok = sum(1 for r in results if r["status"] == "OK")
        wait = sum(1 for r in results if r["status"] == "WAIT")
        errors = sum(1 for r in results if r["status"] == "ERROR")
        
        print(file=sys.stderr)
        print(f"  Updated              {updated}", file=sys.stderr)
        if would:
            print(f"  Dry-run              {would}", file=sys.stderr)
        print(f"  Already sufficient   {ok}", file=sys.stderr)
        print(f"  Waiting              {wait}", file=sys.stderr)
        print(f"  Errors               {errors}", file=sys.stderr)
    
    if args.json_output:
        print(json.dumps(results, indent=2))
    
    # Exit codes
    has_errors = any(r["status"] == "ERROR" for r in results)
    has_wait = any(r["status"] == "WAIT" for r in results)
    if has_errors:
        sys.exit(1)
    if has_wait and not args.dry_run:
        sys.exit(2)
    sys.exit(0)


if __name__ == "__main__":
    main()
