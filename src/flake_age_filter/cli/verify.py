"""CLI command to verify flake inputs against a minimum commit age.

This module uses **Typer** to expose a sub‑command compatible with the historic
``nix-flake-age-filter`` script.  All heavy lifting is delegated to the core
modules (`core.lock_file`, `core.git_ops`, `core.age_check`).
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Dict, List, Optional

import typer

from ..core import git_ops, get_backend, list_backends
from ..core.age_check import check_age, format_duration
from ..core.errors import FlakeAgeError
from ..core.git_ops import resolve_default_ref, set_backend
from ..core.lock_file import read_flake_inputs
from ..core.models import FlakeInput


app = typer.Typer(help="Verify that all flake inputs are at least a given age.")


def _process_input(
    inp: FlakeInput, min_age: int, now_ts: int, timeout: int, method: str = "auto"
) -> Dict[str, object] | None:
    """Return a dict describing the age‑check result for a single input.

    Checks whether the currently locked commit (inp.rev) satisfies the min_age.
    Does NOT search for older commits.

    Returns ``None`` for non‑git inputs (e.g. ``path`` type) which are skipped
    from the age check.
    """
    git_url = inp.to_git_url()
    if not git_url:
        # Skip path inputs – they are local and have no remote git history.
        return None

    # Must have a locked revision to check.
    if not inp.rev:
        return {
            "ok": False,
            "input": inp.name,
            "error": "No locked revision (inp.rev is None)",
        }

    # Get the timestamp for the locked revision.
    ts_res = git_ops.get_commit_timestamp(git_url, inp.rev, timeout, method=method)
    # Accept both dict and raw int responses.
    ts = None
    if isinstance(ts_res, dict):
        if not ts_res.get("ok"):
            return {
                "ok": False,
                "input": inp.name,
                "rev": inp.rev,
                "error": ts_res.get("error", "failed to get timestamp"),
            }
        ts = ts_res["timestamp"]
    else:
        # Assume raw int is the timestamp
        ts = ts_res

    if ts is None:
        return {
            "ok": False,
            "input": inp.name,
            "rev": inp.rev,
            "error": "Could not determine commit timestamp",
        }

    age_res = check_age(ts, now_ts, min_age)
    deviation = age_res["age_days"] - min_age  # 偏差：正＝超過、負＝不足
    result: Dict[str, object] = {
        "ok": age_res["ok"],
        "input": inp.name,
        "rev": inp.rev,
        "timestamp": ts,
        "age_days": age_res["age_days"],
        "deviation": deviation,
    }
    if not age_res["ok"]:
        result["error"] = age_res["error"]
    return result


def _get_token_from_env() -> Optional[str]:
    """Get GitHub token from environment.
    
    Checks GITHUB_TOKEN and GH_TOKEN environment variables.
    
    Returns:
        Token string or None if not set.
    """
    return os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")


@app.command()
def verify(
    min_age: int = typer.Option(..., "--min-age", help="Minimum age in days"),
    flake_lock: Path = typer.Argument(Path("flake.lock"), help="Path to flake.lock"),
    timeout: int = typer.Option(
        120, "--timeout", help="Network/git timeout in seconds"
    ),
    inputs: List[str] = typer.Option(
        None, "--inputs", help="Specific inputs to check (default: all)"
    ),
    json_out: bool = typer.Option(False, "--json", help="Output results as JSON"),
    verbose: bool = typer.Option(
        False, "--verbose", help="Show detailed per‑input information"
    ),
    parallel: int = typer.Option(
        4, "--parallel", help="Number of parallel workers (default=4)", min=0
    ),
    method: str = typer.Option(
        "auto",
        "--method",
        help=f"Commit search method: {', '.join(list_backends())}, or auto",
    ),
    github_token: Optional[str] = typer.Option(
        None,
        "--github-token",
        help="GitHub token for higher API rate limits (or set GITHUB_TOKEN/GH_TOKEN env var)",
        envvar="GITHUB_TOKEN",
    ),
):
    """Validate that each flake input is at least ``min_age`` days old.

    The command prints a human‑readable summary to stdout unless ``--json`` is
    given, in which case a JSON document is emitted.  Errors are reported on
    stderr and cause a non‑zero exit status.
    """
    # Validate method parameter early
    valid_methods = ["auto"] + list_backends()
    if method not in valid_methods:
        # Suggest closest match
        import difflib
        suggestions = difflib.get_close_matches(method, valid_methods, n=1, cutoff=0.6)
        msg = f"Error: Invalid method '{method}'. Valid methods: {', '.join(valid_methods)}"
        if suggestions:
            msg += f"\nDid you mean: '{suggestions[0]}'?"
        typer.secho(msg, fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1)

    # Set up backend with token if provided
    token = github_token or _get_token_from_env()
    if token or verbose:
        set_backend(method, token=token, verbose=verbose)
    else:
        set_backend(method)

    # Show rate limit info for GitHub backend
    if verbose and method in ("github", "auto"):
        backend = git_ops.get_current_backend()
        if hasattr(backend, "get_rate_limit_info"):
            rate_info = backend.get_rate_limit_info()
            if rate_info:
                typer.secho(
                    f"GitHub API Rate Limit: {rate_info.get('remaining', '?')} remaining, "
                    f"resets at {rate_info.get('reset_time', '?')}",
                    fg=typer.colors.CYAN,
                )
            elif token:
                typer.secho(
                    "GitHub API: Using authenticated requests (5,000 req/hour)",
                    fg=typer.colors.CYAN,
                )
            else:
                typer.secho(
                    "GitHub API: Using unauthenticated requests (60 req/hour). "
                    "Set GITHUB_TOKEN for higher limits.",
                    fg=typer.colors.YELLOW,
                )

    try:
        inputs_all = read_flake_inputs(flake_lock)
    except FlakeAgeError as exc:
        typer.echo(f"Error reading flake.lock: {exc}", err=True)
        raise typer.Exit(code=1)

    if inputs:
        inputs_all = [i for i in inputs_all if i.name in inputs]

    now_ts = int(__import__("time").time())
    results: List[Dict[str, object]] = []
    failures: List[str] = []

    from ..core.parallel import execute_parallel

    def _process_verify_inp(inp: FlakeInput) -> dict | None:
        return _process_input(inp, min_age, now_ts, timeout, method)

    processed = execute_parallel(inputs_all, _process_verify_inp, parallel)
    for inp, res in processed:
        results.append(res)
        if not res.get("ok"):
            failures.append(inp.name)

    if json_out:
        typer.echo(json.dumps(results, indent=2))
    else:
        from ..output.formatters import format_verify_results

        output = format_verify_results(results, verbose=verbose)
        typer.echo(output)
        if failures:
            typer.secho(
                f"\n{len(failures)} input(s) too new: {', '.join(failures)}",
                fg=typer.colors.RED,
            )
            raise typer.Exit(code=1)
        else:
            typer.secho(
                "All inputs satisfy the minimum age requirement.", fg=typer.colors.GREEN
            )


if __name__ == "__main__":
    app()
