#!/usr/bin/env python3
"""
nix flake age verify - Validate flake input ages against a minimum threshold.
Equivalent to npm's min-release-age, for nix flake.lock inputs.

Usage:
    python3 nix_flake_age_verify.py --min-age 3
"""

import argparse
import json
import sys
from datetime import datetime, timezone

from flake_age_common import (
    FlakeInput,
    check_age,
    extract_locked_inputs,
    format_duration,
    get_commit_timestamp,
    parse_flake_lock,
    run_git,
)


def ls_remote_refs(git_url: str, timeout: int = 30) -> dict[str, str]:
    """Run git ls-remote and return {ref_name: sha} dict."""
    rc, stdout, _ = run_git(
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


def main():
    parser = argparse.ArgumentParser(
        description="Verify nix flake input ages via git protocol",
    )
    parser.add_argument(
        "flake_lock", nargs="?", default="flake.lock",
        help="Path to flake.lock (default: ./flake.lock)",
    )
    parser.add_argument(
        "--min-age", type=int, required=True,
        help="Minimum age in days (like npm min-release-age)",
    )
    parser.add_argument(
        "--timeout", type=int, default=60,
        help="Timeout per input in seconds (default: 60)",
    )
    parser.add_argument(
        "--skip-ref-check", action="store_true",
        help="Skip ls-remote pre-verification step",
    )
    parser.add_argument(
        "--exclude", nargs="*", default=[], metavar="INPUT",
        help="Input names to skip",
    )
    parser.add_argument("--json", action="store_true", dest="json_output")
    parser.add_argument("--verbose", "-v", action="store_true")

    args = parser.parse_args()

    lock_data = parse_flake_lock(args.flake_lock)
    inputs = extract_locked_inputs(lock_data)

    if not inputs:
        print("No locked inputs found in flake.lock.", file=sys.stderr)
        sys.exit(0)

    now = datetime.now(tz=timezone.utc)
    results: list[dict] = []

    if not args.json_output:
        print(f"Verifying {len(inputs)} input(s) -- minimum age: {args.min_age}d", file=sys.stderr)

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

        lock_ref = inp.target_ref()

        if args.verbose and not args.json_output:
            print(f"  -> {inp.name}: {git_url} @ {inp.rev[:12]}", file=sys.stderr)

        # Step 1: Ref existence check via ls-remote
        if not args.skip_ref_check and lock_ref:
            refs = ls_remote_refs(git_url, timeout=min(args.timeout, 20))
            if refs:
                matched = any(
                    ref_path.endswith("/" + lock_ref)
                    or ref_path == f"refs/heads/{lock_ref}"
                    for ref_path in refs
                )
                if not matched:
                    results.append({
                        "name": inp.name, "status": "ERROR",
                        "reason": f"ref '{lock_ref}' not found on remote",
                    })
                    continue
            elif not args.json_output:
                print(f"  Warning: could not list refs for {inp.name}, proceeding with fetch...",
                      file=sys.stderr)

        # Step 2: Fetch commit + timestamp via git protocol
        fetch_result = get_commit_timestamp(git_url, inp.rev, timeout=args.timeout)
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

    max_len = max((len(r["name"]) for r in results), default=10)
    max_len = max(max_len, 10)

    print(f"\n=== min-age verify (minimum: {args.min_age} days) ===")
    print(f"Checked at: {now.strftime('%Y-%m-%d %H:%M UTC')}")
    print()

    for r in results:
        name = r["name"].ljust(max_len)
        status = r["status"]
        if status == "PASS":
            age_str = format_duration(r["age_days"])
            print(f"  [PASS] {name}  age={age_str:>8s}  {r['commit_date']}")
        elif status == "SKIP":
            print(f"  [SKIP] {name}  {r['reason']}")
        elif status == "ERROR":
            err = r.get("error") or r.get("reason", "unknown error")
            print(f"  [ERR!] {name}  {err}")
        elif status == "FAIL":
            print(f"  [FAIL] {name}  {r['error']}")

    print()
    passed = sum(1 for r in results if r["status"] == "PASS")
    failed = sum(1 for r in results if r["status"] == "FAIL")
    errors = sum(1 for r in results if r["status"] == "ERROR")
    skipped = sum(1 for r in results if r["status"] == "SKIP")
    print(f"Results: {passed} passed, {failed} failed, {errors} errors, {skipped} skipped")

    if failed > 0 or errors > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
