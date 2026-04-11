#!/usr/bin/env python3
"""
nix flake age verify - Validate flake input ages against a minimum threshold.
Equivalent to npm's min-release-age, for nix flake.lock inputs.

Usage:
    python3 nix_flake_age_verify.py --min-age 3
"""

import json
import sys
from whenever import Instant
import typer

from age_check import check_age, format_duration
from commit_fetch import get_commit_timestamp
from flake_lock import extract_locked_inputs, parse_flake_lock
from git_operations import ls_remote_refs

app = typer.Typer(
    name="nix-flake-age-verify",
    help="Verify nix flake input ages against a minimum threshold",
)


@app.command()
def main(
    flake_lock: str = typer.Argument(
        "flake.lock",
        help="Path to flake.lock (default: ./flake.lock)",
    ),
    min_age: int = typer.Option(
        ...,
        "--min-age",
        help="Minimum age in days (like npm min-release-age)",
    ),
    timeout: int = typer.Option(
        60,
        "--timeout",
        help="Timeout per input in seconds (default: 60)",
    ),
    skip_ref_check: bool = typer.Option(
        False,
        "--skip-ref-check",
        help="Skip ls-remote pre-verification step",
    ),
    exclude: list[str] = typer.Option(
        [],
        "--exclude",
        help="Input names to skip (repeatable)",
    ),
    json_output: bool = typer.Option(
        False,
        "--json",
        help="Output in JSON format",
    ),
    verbose: bool = typer.Option(
        False,
        "--verbose", "-v",
        help="Enable verbose output",
    ),
) -> None:
    """Verify nix flake input ages via git protocol"""
    from flake_lock import FlakeInput  # noqa: F811

    lock_data = parse_flake_lock(flake_lock)
    inputs = extract_locked_inputs(lock_data)

    if not inputs:
        typer.echo("No locked inputs found in flake.lock.", err=True)
        raise typer.Exit(0)

    now = Instant.now()
    results: list[dict] = []

    if not json_output:
        typer.echo(
            f"Verifying {len(inputs)} input(s) -- minimum age: {min_age}d",
            err=True,
        )

    for inp in inputs:
        if inp.name in exclude:
            results.append({"name": inp.name, "status": "SKIP", "reason": "excluded"})
            continue

        if not inp.has_rev:
            results.append({
                "name": inp.name,
                "status": "SKIP",
                "reason": "no locked revision",
            })
            continue

        git_url = inp.to_git_url()
        if not git_url:
            results.append({
                "name": inp.name,
                "status": "SKIP",
                "reason": f"unsupported type: {inp.input_type}",
            })
            continue

        lock_ref = inp.target_ref()

        if verbose and not json_output:
            typer.echo(f"  -> {inp.name}: {git_url} @ {inp.rev[:12]}", err=True)

        # Step 1: Ref existence check via ls-remote
        if not skip_ref_check and lock_ref:
            refs = ls_remote_refs(git_url, timeout=min(timeout, 20))
            if refs:
                matched = any(
                    ref_path.endswith("/" + lock_ref)
                    or ref_path == f"refs/heads/{lock_ref}"
                    for ref_path in refs
                )
                if not matched:
                    results.append({
                        "name": inp.name,
                        "status": "ERROR",
                        "reason": f"ref '{lock_ref}' not found on remote",
                    })
                    continue
            elif not json_output:
                typer.echo(
                    f"  Warning: could not list refs for {inp.name}, proceeding with fetch...",
                    err=True,
                )

        # Step 2: Fetch commit + timestamp via git protocol
        fetch_result = get_commit_timestamp(git_url, inp.rev, timeout=timeout)
        if not fetch_result.ok:
            results.append({
                "name": inp.name,
                "status": "ERROR",
                "error": fetch_result.error or "fetch failed",
            })
            continue

        # Step 3: Age check
        age_result = check_age(fetch_result.timestamp, min_age, now)
        results.append({
            "name": inp.name,
            "status": "PASS" if age_result.ok else "FAIL",
            "age_days": age_result.age_days,
            "commit_date": age_result.commit_date,
            "error": age_result.error,
        })

    # Output
    if json_output:
        typer.echo(json.dumps(results, indent=2))
        raise typer.Exit(
            0 if not any(r["status"] in ("FAIL", "ERROR") for r in results) else 1
        )

    max_len = max((len(r["name"]) for r in results), default=10)
    max_len = max(max_len, 10)

    typer.echo(f"\n=== min-age verify (minimum: {min_age} days) ===")
    typer.echo(
        f"Checked at: {str(now).replace('T', ' ').rsplit('.', 1)[0].rstrip('Z') + 'UTC'}"
    )
    typer.echo()

    for r in results:
        name = r["name"].ljust(max_len)
        status = r["status"]
        if status == "PASS":
            age_str = format_duration(r["age_days"])
            typer.echo(f"  [PASS] {name}  age={age_str:>8s}  {r['commit_date']}")
        elif status == "SKIP":
            typer.echo(f"  [SKIP] {name}  {r['reason']}")
        elif status == "ERROR":
            err = r.get("error") or r.get("reason", "unknown error")
            typer.echo(f"  [ERR!] {name}  {err}")
        elif status == "FAIL":
            typer.echo(f"  [FAIL] {name}  {r['error']}")

    typer.echo()
    passed = sum(1 for r in results if r["status"] == "PASS")
    failed = sum(1 for r in results if r["status"] == "FAIL")
    errors = sum(1 for r in results if r["status"] == "ERROR")
    skipped = sum(1 for r in results if r["status"] == "SKIP")
    typer.echo(
        f"Results: {passed} passed, {failed} failed, {errors} errors, {skipped} skipped"
    )

    if failed > 0 or errors > 0:
        raise typer.Exit(1)


if __name__ == "__main__":
    app()
