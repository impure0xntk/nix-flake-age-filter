#!/usr/bin/env python3
"""
nix flake age update - Update flake inputs but only adopt commits >= min_age_days.

Like `nix flake update` but with a minimum-release-age guard.
Uses git protocol to find the newest commit that satisfies the age requirement,
then runs `nix flake update --override-input` to pin that exact commit.

Usage:
    python3 nix_flake_age_update.py --min-age 3
    python3 nix_flake_age_update.py --min-age 7 nixpkgs
    python3 nix_flake_age_update.py --min-age 3 --dry-run --json
"""

import argparse
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

from rich.console import Console
from rich.table import Table
from rich import box


from flake_age_filter.core.models import FlakeInput  # noqa: E402
from flake_age_filter.core.age_check import check_age, format_duration  # noqa: E402
from flake_age_filter.core.lock_file import read_flake_inputs as extract_locked_inputs  # noqa: E402
from flake_age_filter.core.git_ops import find_oldest_commit_meeting_age, get_commit_timestamp, run_cmd  # noqa: E402
from flake_age_filter.core.lock_file import parse_flake_lock  # noqa: E402


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
    if t == "path":
        return None
    return None


def find_suitable_commit(inp: FlakeInput, min_age_days: int, timeout: int) -> dict:
    """Find the newest commit >= min_age_days on the target branch."""
    git_url = inp.to_git_url()
    if not git_url:
        return {"ok": False, "reason": f"unsupported type: {inp.input_type}"}

    ref = inp.target_ref()
    locked_ts = inp.locked.get("lastModified")

    result = find_oldest_commit_meeting_age(
        git_url, ref, min_age_days,
        min_depth=100, max_depth=1000,
        timeout=timeout,
        locked_ts=locked_ts,
        input_name=inp.name,
        original=inp.original,
    )

    if result.get("used_locked") and result.get("rev") is None:
        # The currently locked commit is already old enough — no update needed
        return {
            "ok": True,
            "rev": inp.rev,
            "timestamp": result["timestamp"],
            "age_days": result.get("depth", 0),  # placeholder, we'll recalculate
            "commit_date": result.get("date", ""),
            "already_sufficient": True,
        }

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

    if not result["ok"]:
        return {"ok": False, "reason": result.get("error", "unknown")}

    rev = result["rev"]
    ts_result = get_commit_timestamp(git_url, rev, timeout=timeout)
    if not ts_result["ok"]:
        return {"ok": False, "reason": f"commit fetch failed: {ts_result['error']}"}

    now = datetime.now(tz=timezone.utc)
    age = check_age(ts_result["timestamp"], min_age_days, now)
    return {
        "ok": True,
        "rev": rev,
        "timestamp": ts_result["timestamp"],
        "age_days": age["age_days"],
        "commit_date": age["commit_date"],
        "already_sufficient": False,
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


def generate_initial_flake_lock(flake_lock_path: Path, flake_dir: str, min_age_days: int, timeout: int) -> dict | None:
    """Generate an initial flake.lock with age enforcement.
    
    Three-step strategy:
    1. `nix flake lock` to generate initial lock (pins to HEAD).
    2. Find age-compliant commits for each input via git API/fetch.
    3. `nix flake update --override-input` to pin inputs to age-compliant commits.
    
    Returns the parsed lock data, or None if nix is unavailable (will build lock from git).
    """
    nix_bin = shutil.which("nix")
    
    # ── Step 0: Check nix availability ────────────────────────────
    if not nix_bin:
        print("nix not found in PATH. Will build flake.lock from git history directly.", file=sys.stderr)
        return _build_lock_from_git(flake_lock_path, flake_dir, min_age_days, timeout)

    common_args = [nix_bin, "--extra-experimental-features", "nix-command flakes"]

    # ── Step 1: Initial lock generation (pins to HEAD) ────────────
    print("flake.lock not found. Generating initial lock...", file=sys.stderr)
    lock_cmd = common_args + ["flake", "lock"]
    rc, _, stderr = run_cmd(lock_cmd, cwd=flake_dir, timeout=max(timeout, 300))
    if rc != 0:
        print(f"Warning: nix flake lock failed: {stderr.strip()[:400]}", file=sys.stderr)
        print("Falling back to building flake.lock from git history directly.", file=sys.stderr)
        return _build_lock_from_git(flake_lock_path, flake_dir, min_age_days, timeout)

    # Verify the file was actually created
    if not flake_lock_path.exists():
        print("Warning: nix flake lock succeeded but flake.lock was not created.", file=sys.stderr)
        print("Falling back to building flake.lock from git history directly.", file=sys.stderr)
        return _build_lock_from_git(flake_lock_path, flake_dir, min_age_days, timeout)

    # ── Step 2: Check ages and prepare overrides ──────────────────
    metadata_cmd = common_args + ["flake", "metadata", "--json"]
    rc, stdout, _ = run_cmd(metadata_cmd, cwd=flake_dir, timeout=max(timeout, 300))
    if rc != 0:
        print("Warning: couldn't fetch metadata. Keeping initial lock file without age filtering.", file=sys.stderr)
        return parse_flake_lock(str(flake_lock_path))

    try:
        meta = json.loads(stdout)
    except json.JSONDecodeError:
        return parse_flake_lock(str(flake_lock_path))

    locks = meta.get("locks", {})
    nodes = locks.get("nodes", {})
    root_node = nodes.get("root", {})
    root_inputs_raw = root_node.get("inputs", {})

    if isinstance(root_inputs_raw, dict):
        direct_names = set(root_inputs_raw.keys())
    elif isinstance(root_inputs_raw, list):
        direct_names = set(root_inputs_raw)
    else:
        direct_names = set(nodes.keys()) - {"root"}

    now = datetime.now(tz=timezone.utc)
    cutoff_ts = int(now.timestamp()) - min_age_days * 86400

    updates_to_apply: list[str] = [] # input names

    for name in sorted(direct_names):
        node = nodes.get(name)
        if not node or "original" not in node:
            continue

        original = node.get("original", {})
        inp_type = original.get("type", "")
        locked_info = node.get("locked", {})

        fake_locked = {**locked_info, "type": inp_type}
        fake_flake_input = FlakeInput(name=name, locked=fake_locked, original=original)

        git_url = fake_flake_input.to_git_url()
        if not git_url:
            continue

        ref = fake_flake_input.target_ref()
        head_ts = locked_info.get("lastModified")

        # Check if HEAD is too new
        if head_ts is not None and head_ts <= cutoff_ts:
            continue

        # HEAD is too new — find a suitable commit to downgrade to
        print(f"  Checking {name}: {git_url} ref={ref or '(auto-detect)'}", file=sys.stderr)
        result = find_oldest_commit_meeting_age(
            git_url, ref, min_age_days,
            min_depth=100, max_depth=1000,
            timeout=timeout, locked_ts=head_ts,
            input_name=name,
            original=original,
        )

        if result.get("skipped_nixpkgs"):
            print(f"    SKIP {name}: nixpkgs detected, keeping HEAD", file=sys.stderr)
            continue

        if result.get("ok") and result.get("rev"):
            override_url = build_override_url(fake_flake_input, result["rev"])
            if override_url:
                updates_to_apply.append(name)
                print(f"    Found older commit: {result['rev'][:12]}", file=sys.stderr)
        elif result.get("too_new_commit"):
            age = (int(now.timestamp()) - result["too_new_timestamp"]) / 86400
            print(f"    WARN: {name} HEAD too new ({age:.1f}d old), keeping HEAD", file=sys.stderr)
        elif result.get("error"):
            print(f"    WARN: {name}: {result['error']}, keeping HEAD", file=sys.stderr)

    # ── Step 3: Apply overrides via nix flake update ─────────────
    for name in updates_to_apply:
        node = nodes.get(name)
        original = node.get("original", {})
        lock = node.get("locked", {})
        fake_locked = {**lock, "type": original.get("type", "")}
        inp = FlakeInput(name=name, locked=fake_locked, original=original)
        
        git_url = inp.to_git_url()
        ref = inp.target_ref()
        result = find_oldest_commit_meeting_age(
            git_url, ref, min_age_days, min_depth=100, max_depth=1000, timeout=timeout
        )
        
        if result.get("ok") and result.get("rev"):
            url = build_override_url(inp, result["rev"])
            if url:
                print(f"  Downgrading {name} -> {result['rev'][:12]} ({url})", file=sys.stderr)
                rc, _, stderr = run_cmd(
                    common_args + ["flake", "update", name, "--override-input", name, url],
                    cwd=flake_dir, timeout=max(timeout, 300)
                )
                if rc != 0:
                    print(f"    Failed to update {name}: {stderr.strip()[:200]}", file=sys.stderr)

    print("Initial flake.lock generated and filtered.", file=sys.stderr)
    return parse_flake_lock(str(flake_lock_path))


def _build_lock_from_git(flake_lock_path: Path, flake_dir: str, min_age_days: int, timeout: int) -> dict:
    """Build flake.lock from scratch by parsing flake.nix and finding age-compliant commits via git.
    
    Used as fallback when nix binary is unavailable or nix flake lock fails.
    """
    flake_nix_path = Path(flake_dir) / "flake.nix"
    if not flake_nix_path.exists():
        print(f"Error: flake.nix not found at {flake_nix_path}", file=sys.stderr)
        sys.exit(1)

    inputs = _parse_flake_inputs_from_nix(flake_nix_path)
    if not inputs:
        print("Warning: no inputs found in flake.nix", file=sys.stderr)

    now = datetime.now(tz=timezone.utc)
    nodes: dict = {}
    now_ts = int(now.timestamp())
    input_order: list[str] = []

    # Root node
    for inp in inputs:
        print(f"  Resolving {inp.name}...", file=sys.stderr)
        git_url = inp.to_git_url()
        if not git_url:
            # For path/unsupported inputs, create a minimal node
            nodes[inp.name] = {
                "inputs": {},
                "original": inp.original,
                "locked": {
                    "type": inp.original.get("type", "unknown"),
                    "narHash": "sha256-0000000000000000000000000000000000000000000000000000",
                }
            }
            input_order.append(inp.name)
            continue

        ref = inp.target_ref() or "master"
        result = find_oldest_commit_meeting_age(
            git_url, ref, min_age_days,
            min_depth=100, max_depth=1000,
            timeout=timeout,
            input_name=inp.name,
            original=inp.original,
        )

        if result.get("ok") and result.get("rev"):
            rev = result["rev"]
            ts = result.get("timestamp", 0)
            if not ts:
                ts_result = get_commit_timestamp(git_url, rev, timeout=timeout)
                ts = ts_result.get("timestamp", now_ts)
            print(f"    Using {rev[:12]} (age={result.get('depth', '?')} commits back)", file=sys.stderr)
        elif result.get("too_new_commit"):
            rev = result["too_new_commit"]
            ts = result.get("too_new_timestamp", now_ts)
            age = (now_ts - ts) / 86400
            print(f"    All commits too new; using HEAD {rev[:12]} ({age:.1f}d old)", file=sys.stderr)
        elif result.get("error"):
            # Last resort: try to get HEAD via ls-remote
            ls_rc, ls_stdout, _ = run_cmd(
                ["git", "ls-remote", git_url, ref],
                timeout=timeout,
            )
            if ls_rc == 0 and ls_stdout.strip():
                rev = ls_stdout.strip().split()[0]
                ts = now_ts
                print(f"    Fallback: using ls-remote {rev[:12]}", file=sys.stderr)
            else:
                print(f"    SKIP: {result['error']}", file=sys.stderr)
                continue
        else:
            continue

        # Build locked node
        locked: dict = {
            "lastModified": ts,
            "rev": rev,
        }
        inp_type = inp.original.get("type", "unknown")
        
        if inp_type == "github":
            locked["type"] = "github"
            locked["owner"] = inp.original.get("owner", "")
            locked["repo"] = inp.original.get("repo", "")
        elif inp_type == "gitlab":
            locked["type"] = "gitlab"
            locked["host"] = inp.original.get("host", "gitlab.com")
            if "owner" in inp.original:
                locked["owner"] = inp.original["owner"]
            if "repo" in inp.original:
                locked["repo"] = inp.original["repo"]
        elif inp_type == "git":
            locked["type"] = "git"
            locked["url"] = inp.original.get("url", "")
            if "ref" in inp.original:
                locked["ref"] = inp.original["ref"]
        else:
            locked["type"] = inp_type

        nodes[inp.name] = {
            "inputs": {},
            "original": inp.original,
            "locked": locked,
        }
        input_order.append(inp.name)

    # Build flake.lock JSON
    lock_data = {
        "nodes": {
            "root": {
                "inputs": {name: [name] for name in input_order},
                "flake": False,
            },
            **nodes,
        },
        "root": "root",
        "version": 7,
    }

    # Write flake.lock
    flake_lock_path.write_text(json.dumps(lock_data, indent=2) + "\n")
    print(f"\nflake.lock created with {len(input_order)} input(s).", file=sys.stderr)
    return lock_data


def _parse_flake_inputs_from_nix(flake_nix_path: Path) -> list[FlakeInput]:
    """Parse flake.nix to extract input URLs using simple regex extraction."""
    text = flake_nix_path.read_text()
    inputs: list[FlakeInput] = []

    # Match: input-name.url = "github:owner/repo/ref";
    # or:    input-name.url = "gitlab:owner/repo/ref";
    # or:    input-name.url = "git+https://...";
    import re
    pattern = r'(\w[\w-]*)\s*\.\s*url\s*=\s*"(github|gitlab|git)\+?[:"](.*?)"\s*;'
    for m in re.finditer(pattern, text):
        name = m.group(1)
        url_type = m.group(2)
        url_rest = m.group(3)
        
        original: dict = {"type": url_type}
        
        if url_type == "github":
            parts = url_rest.rstrip("/").split("/")
            if len(parts) >= 2:
                original["owner"] = parts[0]
                original["repo"] = parts[1]
                if len(parts) >= 3:
                    original["ref"] = parts[2]
        elif url_type == "gitlab":
            # gitlab:server/owner/repo or gitlab:owner/repo
            if "/" in url_rest:
                segs = url_rest.split("/")
                if len(segs) >= 3 and "." in segs[0]:
                    original["host"] = segs[0]
                    original["owner"] = segs[1]
                    original["repo"] = segs[2] if len(segs) > 2 else ""
                else:
                    original["owner"] = segs[0]
                    original["repo"] = segs[1] if len(segs) > 1 else ""
        elif url_type == "git":
            original["url"] = url_rest

        inputs.append(FlakeInput(name=name, locked={}, original=original))

    return inputs


def main():
    parser = argparse.ArgumentParser(
        description="Update flake inputs with min-release-age guard",
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
        help="Minimum commit age in days (like npm min-release-age)",
    )
    parser.add_argument(
        "--timeout", type=int, default=120,
        help="Timeout per git/nix operation in seconds",
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

    # Generate initial flake.lock if it doesn't exist
    if not flake_lock_path.exists():
        lock_data = generate_initial_flake_lock(flake_lock_path, flake_dir, args.min_age, args.timeout)
    else:
        lock_data = parse_flake_lock(args.flake_lock)

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

    console = Console(stderr=True)

    if not args.json_output:
        console.print(f"Checking {len(inputs)} input(s) — min-age: {args.min_age}d", style="dim")

    results: list[dict] = []
    for inp in inputs:
        git_url = inp.to_git_url()
        if not git_url:
            results.append({"name": inp.name, "status": "SKIP",
                            "reason": "no git URL"})
            if not args.json_output:
                console.print(f"  [dim]SKIP[/dim] {inp.name}  no git URL")
            continue

        if args.verbose and not args.json_output:
            console.print(f"  [dim]-> {inp.name}: {git_url} ref={inp.target_ref() or 'default'}[/dim]")

        # Find suitable commit
        info = find_suitable_commit(inp, args.min_age, args.timeout)

        if info.get("already_sufficient"):
            results.append({
                "name": inp.name, "status": "OK",
                "reason": f"current rev already >= {args.min_age}d old",
                "current_rev": inp.rev[:12] if inp.rev else "?",
                "age_days": info["age_days"],
                "commit_date": info["commit_date"],
            })
            if not args.json_output:
                console.print(f"  [green]OK  [/green] {inp.name}  {inp.rev[:12]}  "
                              f"age={format_duration(info['age_days'])}  {info['commit_date']}")
            continue

        if not info["ok"]:
            if "latest_rev" in info:
                results.append({
                    "name": inp.name, "status": "WAIT",
                    "reason": f"all commits < {args.min_age}d",
                    "latest_rev": info["latest_rev"][:12],
                    "shortfall_days": info["shortfall_days"],
                    "latest_date": info.get("latest_date", ""),
                })
                if not args.json_output:
                    console.print(f"  [yellow]WAIT[/yellow] {inp.name}  {info['latest_rev'][:12]} "
                                  f"too new (needs ~{info['shortfall_days']}d more) "
                                  f"date={info.get('latest_date', '?')}")
            else:
                results.append({
                    "name": inp.name, "status": "ERROR",
                    "reason": info.get("reason", ""),
                })
                if not args.json_output:
                    console.print(f"  [red]ERR![/red] {inp.name}  {info.get('reason', '')}")
            continue

        # Build the flake URL with pinned revision
        override_url = build_override_url(inp, info["rev"])
        if not override_url:
            results.append({
                "name": inp.name, "status": "ERROR",
                "reason": "cannot build override URL",
            })
            if not args.json_output:
                console.print(f"  [red]ERR![/red] {inp.name}  cannot build override URL")
            continue

        if not args.json_output:
            label = "UPDATE" if not args.dry_run else "DRY-RUN"
            style = "cyan" if args.dry_run else "green"
            console.print(f"  [{style}]{label:>7s}[/{style}] {inp.name}  -> {info['rev'][:12]}  "
                          f"age={format_duration(info['age_days'])}  {info['commit_date']}")
            if not args.dry_run:
                console.print(f"           nix flake update {inp.name} --override-input {inp.name} {override_url}",
                              style="dim")

        # Run nix flake update
        if not args.dry_run:
            nix_result = run_nix_flake_update(
                inp.name, override_url, flake_dir,
                dry_run=args.dry_run, timeout=max(args.timeout, 300),
            )
            if not nix_result["ok"]:
                results.append({
                    "name": inp.name, "status": "ERROR",
                    "reason": f"nix flake update failed: {nix_result['error']}",
                    "target_rev": info["rev"][:12],
                })
                if not args.json_output:
                    print(f"  [ERR!] {inp.name}  nix flake update failed: {nix_result['error'][:80]}",
                          file=sys.stderr)
                continue
            results.append({
                "name": inp.name, "status": "UPDATED",
                "old_rev": inp.rev,
                "new_rev": info["rev"],
                "age_days": info["age_days"],
                "commit_date": info["commit_date"],
            })
        else:
            results.append({
                "name": inp.name, "status": "WOULD-UPDATE",
                "old_rev": inp.rev,
                "new_rev": info["rev"],
                "override_url": override_url,
                "age_days": info["age_days"],
                "commit_date": info["commit_date"],
            })

    # Summary with rich
    if not args.json_output:
        updated = sum(1 for r in results if r["status"] == "UPDATED")
        would = sum(1 for r in results if r["status"] == "WOULD-UPDATE")
        ok = sum(1 for r in results if r["status"] == "OK")
        wait = sum(1 for r in results if r["status"] == "WAIT")
        errors = sum(1 for r in results if r["status"] == "ERROR")

        console = Console(stderr=True)
        summary = Table(box=box.SIMPLE, show_header=False, pad_edge=False)
        summary.add_column("Label", style="bold")
        summary.add_column("Count", justify="right")
        summary.add_row("Updated", str(updated), style="green" if updated else "dim")
        if would:
            summary.add_row("Dry-run", str(would), style="cyan")
        summary.add_row("Already sufficient", str(ok), style="green" if ok else "dim")
        summary.add_row("Waiting", str(wait), style="yellow" if wait else "dim")
        summary.add_row("Errors", str(errors), style="red" if errors else "dim")
        console.print()
        console.print(summary)

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
