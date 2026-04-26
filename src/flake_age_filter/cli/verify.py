"""CLI command to verify flake inputs against a minimum commit age.

This module uses **Typer** to expose a sub‑command compatible with the historic
``nix-flake-age-filter`` script.  All heavy lifting is delegated to the core
modules (`core.lock_file`, `core.git_ops`, `core.age_check`).
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Dict, List, Optional

import typer

from ..core import git_ops, list_backends
from ..core.age_check import check_age
from ..core.errors import FlakeAgeError
from ..core.lock_file import read_flake_inputs
from ..core.models import FlakeInput
from ._common import (
    get_token_from_env,
    validate_method,
    setup_backend,
    show_rate_limit_info,
)


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
    validate_method(method)

    # Set up backend with token if provided
    token = github_token or get_token_from_env()
    setup_backend(method, token, verbose)

    # Show rate limit info for GitHub backend
    show_rate_limit_info(method, token, verbose)

    try:
        inputs_all = read_flake_inputs(flake_lock)
    except FlakeAgeError as exc:
        typer.echo(f"Error reading flake.lock: {exc}", err=True)
        raise typer.Exit(code=1)

    if inputs:
        inputs_all = [i for i in inputs_all if i.name in inputs]

    now_ts = int(time.time())
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
