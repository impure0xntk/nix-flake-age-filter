#!/usr/bin/env python3
"""
nix-flake-age-filter: Validate nix flake input ages via git protocol.

Equivalent to npm's ``min-release-age``, but for nix flake.lock inputs.
Verifies commits through the git protocol (ls-remote for ref existence
+ shallow fetch in a temporary bare repository) and compares commit
timestamps against a minimum age.
"""

import argparse
import json
import os
import subprocess
import sys
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from rich.console import Console
from rich.table import Table
from rich import box


class FlakeInput:
    """Represents a locked flake input."""

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
        """Build a git URL for the locked input."""
        if self.input_type == "github":
            owner = self.locked.get("owner", "")
            repo = self.locked.get("repo", "")
            return f"https://github.com/{owner}/{repo}.git"

        elif self.input_type == "gitlab":
            host = self.locked.get("host", "gitlab.com")
            owner = self.locked.get("owner", "")
            repo = self.locked.get("repo", "")
            if repo:
                return f"https://{host}/{owner}/{repo}.git"
            project = self.locked.get("project", "")
            return f"https://{host}/{project}.git" if project else None

        elif self.input_type == "sourcehut":
            owner = self.locked.get("owner", "")
            repo = self.locked.get("repo", self.locked.get("project", ""))
            return f"https://git.sr.ht/~{owner}/{repo}"

        elif self.input_type == "git":
            return self.locked.get("url", self.original.get("url"))

        elif self.input_type == "path":
            return None  # Local path, no git protocol

        return None

    def locked_ref(self) -> str | None:
        """Return the git ref (branch/tag) that was locked, if available."""
        return self.locked.get("ref") or self.original.get("ref") or self.original.get("branch")


def run_cmd(
    args: list[str],
    cwd: str | None = None,
    timeout: int = 60,
    env_overrides: dict | None = None,
) -> tuple[int, str, str]:
    """Run a command and return (returncode, stdout, stderr)."""
    try:
        env = None
        if env_overrides:
            env = {**os.environ, **env_overrides}
        result = subprocess.run(
            args, capture_output=True, text=True, timeout=timeout, cwd=cwd, env=env,
        )
        return result.returncode, result.stdout, result.stderr
    except subprocess.TimeoutExpired:
        return -1, "", f"{' '.join(args[:4])} timed out after {timeout}s"
    except Exception as exc:
        return -1, "", str(exc)


def run_git(
    args: list[str],
    cwd: str | None = None,
    timeout: int = 60,
    env_overrides: dict | None = None,
) -> tuple[int, str, str]:
    """Run a git command and return (returncode, stdout, stderr)."""
    return run_cmd(["git"] + list(args), cwd=cwd, timeout=timeout, env_overrides=env_overrides)


def is_gh_available() -> bool:
    """Check if the gh CLI is available."""
    return shutil.which("gh") is not None


def gh_get_commit_timestamp(owner: str, repo: str, rev: str, timeout: int = 20) -> dict:
    """
    Get commit timestamp via gh CLI API.

    Returns: {"ok": bool, "timestamp": int | None, "error": str | None}
    """
    rc, stdout, stderr = run_cmd(
        ["gh", "api", f"/repos/{owner}/{repo}/commits/{rev}", "--jq", ".commit.committer.date"],
        timeout=timeout,
    )
    if rc != 0:
        return {"ok": False, "timestamp": None, "error": f"gh api failed: {stderr.strip()[:200]}"}

    date_str = stdout.strip()
    if not date_str:
        return {"ok": False, "timestamp": None, "error": "empty response from gh api"}

    try:
        dt = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
        return {"ok": True, "timestamp": int(dt.timestamp()), "error": None}
    except (ValueError, TypeError) as e:
        return {"ok": False, "timestamp": None, "error": f"invalid date format: {e}"}


def gh_list_refs(owner: str, repo: str, ref_prefix: str, timeout: int = 15) -> list[str]:
    """Return list of matching git refs via gh API."""
    rc, stdout, _ = run_cmd(["gh", "api", f"/repos/{owner}/{repo}/git/matching-refs/{ref_prefix}"], timeout=timeout)
    if rc != 0:
        return []
    try:
        data = json.loads(stdout)
        if isinstance(data, list):
            return [x.get("ref", "") for x in data if x.get("ref")]
        if isinstance(data, dict) and data.get("ref"):
            return [data["ref"]]
    except Exception:
        pass
    return []


def parse_flake_lock(path: str) -> dict:
    """Parse flake.lock and return the JSON structure."""
    lock_path = Path(path)
    if not lock_path.exists():
        print(f"Error: flake.lock not found at {path}", file=sys.stderr)
        sys.exit(1)
    return json.loads(lock_path.read_text())


def extract_locked_inputs(lock_data: dict) -> list[FlakeInput]:
    """Extract all locked inputs from flake.lock that are direct root inputs."""
    nodes = lock_data.get("nodes", {})
    root_node = nodes.get("root", {})

    root_inputs_raw = root_node.get("inputs", {})
    if isinstance(root_inputs_raw, dict):
        direct_names = set(root_inputs_raw.keys())
    elif isinstance(root_inputs_raw, list):
        direct_names = set(root_inputs_raw)
    else:
        direct_names = set(nodes.keys()) - {"root"}

    inputs = []
    for name in sorted(direct_names):
        node_data = nodes.get(name)
        if not node_data or "locked" not in node_data:
            continue
        inputs.append(FlakeInput(
            name=name,
            locked=node_data["locked"],
            original=node_data.get("original", {}),
        ))
    return inputs


def ls_remote_refs(git_url: str, timeout: int = 30) -> dict[str, str]:
    """
    Run git ls-remote and return {ref_name: sha} dict.

    Used to verify that a locked ref (branch/tag) actually exists on the
    remote, and optionally to check if the locked rev matches.
    """
    rc, stdout, stderr = run_git(
        ["ls-remote", "--refs", git_url], timeout=timeout,
    )
    if rc != 0:
        return {}

    refs: dict[str, str] = {}
    for line in stdout.strip().splitlines():
        if not line:
            continue
        parts = line.split("\t")
        if len(parts) == 2:
            sha, ref = parts
            refs[ref] = sha
    return refs


def fetch_commit_timestamp_via_bare(
    git_url: str, rev: str, timeout: int = 120,
) -> dict:
    """
    Fetch the commit timestamp via git protocol in a temporary bare repo.

    This is the core supply-chain verification step: we actually fetch the
    object from the remote, proving the commit exists in that repository.

    Returns:
        {"ok": bool, "timestamp": int | None, "error": str | None}
    """
    with tempfile.TemporaryDirectory(prefix="nix-age-filter-") as tmpdir:
        bare_dir = str(Path(tmpdir) / "bare.git")

        # 1. Initialize bare repository
        rc, _, stderr = run_git(["init", "--bare", bare_dir])
        if rc != 0:
            return {"ok": False, "timestamp": None, "error": f"bare init failed: {stderr.strip()}"}

        # 2. Environment: no prompts, protocol v2 for better performance
        env = {
            "GIT_TERMINAL_PROMPT": "0",
            "GIT_ASKPASS": "echo",
            "GIT_CONFIG_COUNT": "1",
            "GIT_CONFIG_KEY_0": "protocol.version",
            "GIT_CONFIG_VALUE_0": "2",
        }

        # 3. Shallow fetch the specific commit by rev
        rc, _, stderr = run_git(
            ["-C", bare_dir, "fetch", "--depth", "1", "--no-tags", git_url, rev],
            timeout=timeout, env_overrides=env,
        )

        # If shallow fetch fails, try a single-branch fetch without depth
        if rc != 0:
            rc2, _, stderr2 = run_git(
                ["-C", bare_dir, "fetch", "--no-tags", git_url, rev],
                timeout=timeout, env_overrides=env,
            )
            if rc2 != 0:
                # Try with uploadpack.allowReachableSHA1InWant (needed for GitHub
                # to fetch arbitrary SHAs not reachable from any ref)
                rc3, _, stderr3 = run_git(
                    [
                        "-c", "uploadpack.allowReachableSHA1InWant=true",
                        "-c", "uploadpack.allowAnySHA1InWant=true",
                        "-C", bare_dir,
                        "fetch", "--depth", "1", "--no-tags",
                        git_url, rev,
                    ],
                    timeout=timeout, env_overrides=env,
                )
                if rc3 != 0:
                    # Last resort: full fetch without depth
                    rc4, _, stderr4 = run_git(
                        ["-C", bare_dir, "fetch", git_url, rev],
                        timeout=max(timeout, 180), env_overrides=env,
                    )
                    if rc4 != 0:
                        err = (stderr.strip() or stderr2.strip() or stderr4.strip())[:300]
                        return {"ok": False, "timestamp": None, "error": f"fetch failed for {rev[:8]}: {err}"}

        # 4. Parse the commit object
        rc, stdout, stderr = run_git(["-C", bare_dir, "cat-file", "-p", rev])
        if rc != 0:
            return {"ok": False, "timestamp": None, "error": f"cat-file failed: {stderr.strip()[:200]}"}

        # 5. Extract committer timestamp
        for line in stdout.splitlines():
            if line.startswith("committer "):
                parts = line.split()
                if len(parts) >= 3:
                    try:
                        return {"ok": True, "timestamp": int(parts[-2]), "error": None}
                    except ValueError:
                        return {"ok": False, "timestamp": None, "error": "invalid committer timestamp format"}

        return {"ok": False, "timestamp": None, "error": "no committer line found in commit object"}


def check_age(timestamp: int, min_age_days: int, now: datetime) -> dict:
    """Check if the commit meets the minimum age requirement."""
    commit_time = datetime.fromtimestamp(timestamp, tz=timezone.utc)
    age_seconds = (now - commit_time).total_seconds()
    age_days = int(age_seconds / 86400)

    return {
        "ok": age_days >= min_age_days,
        "age_days": age_days,
        "commit_date": commit_time.strftime("%Y-%m-%d %H:%M UTC"),
        "error": None if age_days >= min_age_days
                 else f"commit is only {age_days}d old (minimum: {min_age_days}d)",
    }


def format_duration(days: int) -> str:
    """Format days into a human-readable duration."""
    if days < 0:
        return f"{days}d (future)"
    if days < 7:
        return f"{days}d"
    weeks = days // 7
    remainder = days % 7
    if weeks < 52:
        return f"{weeks}w {remainder}d" if remainder else f"{weeks}w"
    years = weeks // 52
    w_remainder = weeks % 52
    return f"{years}y {w_remainder}w"


def main():
    parser = argparse.ArgumentParser(
        description="Validate nix flake input ages via git protocol (like npm min-release-age)",
    )
    parser.add_argument(
        "flake_lock", nargs="?", default="flake.lock",
        help="Path to flake.lock (default: ./flake.lock)",
    )
    parser.add_argument(
        "--min-age", type=int, required=True,
        help="Minimum age in days (like npm's min-release-age)",
    )
    parser.add_argument(
        "--timeout", type=int, default=60,
        help="Timeout per input in seconds (default: 60)",
    )
    parser.add_argument(
        "--skip-ref-check", action="store_true",
        help="Skip the ls-remote ref verification step",
    )
    parser.add_argument(
        "--exclude", nargs="*", default=[], metavar="INPUT",
        help="Input names to skip",
    )
    parser.add_argument(
        "--json", action="store_true", dest="json_output",
        help="Output results as JSON",
    )
    parser.add_argument(
        "--verbose", "-v", action="store_true",
        help="Show detailed debug output",
    )

    args = parser.parse_args()

    lock_data = parse_flake_lock(args.flake_lock)
    inputs = extract_locked_inputs(lock_data)

    if not inputs:
        print("No locked inputs found in flake.lock.", file=sys.stderr)
        sys.exit(0)

    now = datetime.now(tz=timezone.utc)
    results: list[dict] = []

    if not args.json_output:
        print(f"Scanning {len(inputs)} input(s) -- minimum age: {args.min_age}d", file=sys.stderr)

    for inp in inputs:
        if inp.name in args.exclude:
            results.append({"name": inp.name, "status": "SKIP", "reason": "excluded"})
            continue

        if not inp.has_rev:
            results.append({"name": inp.name, "status": "SKIP", "reason": "no locked revision"})
            continue

        git_url = inp.to_git_url()
        if not git_url:
            results.append({
                "name": inp.name, "status": "SKIP",
                "reason": f"unsupported type: {inp.input_type}",
            })
            continue

        lock_ref = inp.locked_ref()

        if args.verbose and not args.json_output:
            print(f"  -> {inp.name}: {git_url} @ {inp.rev[:12]}", file=sys.stderr)

        # Step 1: Verify the ref exists via ls-remote (optional but recommended)
        if not args.skip_ref_check and lock_ref:
            refs = ls_remote_refs(git_url, timeout=min(args.timeout, 20))
            if not refs:
                if not args.json_output:
                    print(f"  Warning: could not list refs for {inp.name}, proceeding with fetch...", file=sys.stderr)
            else:
                # Check if the locked ref name exists
                matched = False
                for ref_path in refs:
                    if ref_path.endswith("/" + lock_ref) or ref_path == f"refs/heads/{lock_ref}":
                        matched = True
                        break
                    if ref_path.endswith("/" + lock_ref.replace("refs/heads/", "").replace("refs/tags/", "")):
                        matched = True
                        break

                if not matched:
                    results.append({
                        "name": inp.name, "status": "ERROR",
                        "reason": f"ref '{lock_ref}' not found on {git_url}",
                    })
                    continue

        # Step 2: Fetch commit via git protocol and extract timestamp
        fetch_result = fetch_commit_timestamp_via_bare(
            git_url, inp.rev, timeout=args.timeout,
        )
        if not fetch_result["ok"]:
            results.append({
                "name": inp.name, "status": "ERROR",
                "error": fetch_result.get("error", "fetch failed"),
            })
            continue

        # Step 3: Age check
        age_check = check_age(fetch_result["timestamp"], args.min_age, now)
        results.append({
            "name": inp.name,
            "status": "PASS" if age_check["ok"] else "FAIL",
            "age_days": age_check["age_days"],
            "commit_date": age_check["commit_date"],
            "error": age_check.get("error"),
        })

    # Output
    if args.json_output:
        print(json.dumps(results, indent=2))
        sys.exit(0 if not any(r["status"] in ("FAIL", "ERROR") for r in results) else 1)

    # Human-readable output with rich
    console = Console(stderr=False)
    table = Table(
        title=f"min-release-age check (minimum: {args.min_age} days)",
        box=box.MINIMAL_DOUBLE_HEAD,
        show_edge=False,
        pad_edge=False,
    )
    table.add_column("Status", style="bold", width=6)
    table.add_column("Input", style="cyan")
    table.add_column("Age", justify="right", width=10)
    table.add_column("Committer Date", style="dim")
    table.add_column("Details", style="italic")

    for r in results:
        status = r["status"]
        if status == "PASS":
            age_str = format_duration(r["age_days"])
            table.add_row("[green]PASS[/green]", r["name"], age_str, r["commit_date"], "")
        elif status == "SKIP":
            table.add_row("[dim]SKIP[/dim]", r["name"], "", "", r["reason"])
        elif status == "ERROR":
            err = r.get("error") or r.get("reason", "unknown error")
            table.add_row("[red]ERR![/red]", r["name"], "", "", err)
        elif status == "FAIL":
            table.add_row("[yellow]FAIL[/yellow]", r["name"], "", "", r["error"])

    console.print()
    console.print(table)

    passed = sum(1 for r in results if r["status"] == "PASS")
    failed = sum(1 for r in results if r["status"] == "FAIL")
    errors = sum(1 for r in results if r["status"] == "ERROR")
    skipped = sum(1 for r in results if r["status"] == "SKIP")

    summary = Table(box=box.SIMPLE, show_header=False, pad_edge=False)
    summary.add_column("Label", style="bold")
    summary.add_column("Count", justify="right")
    summary.add_row("Passed", str(passed), style="green")
    summary.add_row("Failed", str(failed), style="yellow" if failed else "dim")
    summary.add_row("Errors", str(errors), style="red" if errors else "dim")
    summary.add_row("Skipped", str(skipped), style="dim")
    console.print()
    console.print(summary)

    if failed > 0 or errors > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
