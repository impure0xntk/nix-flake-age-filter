"""CLI command to verify flake inputs against a minimum commit age.

This module uses **Typer** to expose a sub‑command compatible with the historic
``nix-flake-age-filter`` script.  All heavy lifting is delegated to the core
modules (`core.lock_file`, `core.git_ops`, `core.age_check`).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import List, Dict

import typer

from ..core.lock_file import read_flake_inputs
from ..core.git_ops import (
    get_commit_timestamp,
    resolve_default_ref,
    run_git,
    git_env_no_prompt,
)
from ..core.age_check import check_age, format_duration
from ..core.models import FlakeInput
from ..core.errors import FlakeAgeError

app = typer.Typer(help="Verify that all flake inputs are at least a given age.")

def _process_input(
    inp: FlakeInput, min_age: int, now_ts: int, timeout: int
) -> Dict[str, object]:
    """Return a dict describing the age‑check result for a single input.

    ``now_ts`` is the current Unix epoch (seconds).  The function resolves the
    remote reference, fetches the commit timestamp (using the fast GitHub API
    when possible), and finally checks the age with ``core.age_check``.
    """
    git_url = inp.to_git_url()
    if not git_url:
        return {"ok": False, "error": "non‑git input"}

    # Resolve the ref (branch/tag) to use for the remote query.
    effective_ref = resolve_default_ref(git_url, inp.ref, timeout)

    # Determine which revision to query – prefer the locked rev if it exists.
    rev = inp.rev or effective_ref
    ts_res = get_commit_timestamp(git_url, rev, timeout)
    if not ts_res.get("ok"):
        return {"ok": False, "error": ts_res.get("error", "unknown error")}

    ts = ts_res["timestamp"]
    age_res = check_age(ts, min_age, now_ts)
    result: Dict[str, object] = {
        "ok": age_res["ok"],
        "input": inp.name,
        "rev": rev,
        "timestamp": ts,
        "age_days": age_res["age_days"],
    }
    if not age_res["ok"]:
        result["error"] = age_res["error"]
    else:
        result["duration"] = format_duration(age_res["age_days"])
    return result

@app.command()
def verify(
    min_age: int = typer.Option(..., "--min-age", help="Minimum age in days"),
    flake_lock: Path = typer.Option(Path("flake.lock"), "--flake-lock", help="Path to flake.lock"),
    timeout: int = typer.Option(120, "--timeout", help="Network/git timeout in seconds"),
    inputs: List[str] = typer.Option(None, "--inputs", help="Specific inputs to check (default: all)"),
    json_out: bool = typer.Option(False, "--json", help="Output results as JSON"),
    verbose: bool = typer.Option(False, "--verbose", help="Show detailed per‑input information"),
):
    """Validate that each flake input is at least ``min_age`` days old.

    The command prints a human‑readable summary to stdout unless ``--json`` is
    given, in which case a JSON document is emitted.  Errors are reported on
    stderr and cause a non‑zero exit status.
    """
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
    for inp in inputs_all:
        res = _process_input(inp, min_age, now_ts, timeout)
        results.append(res)
        if not res.get("ok"):
            failures.append(inp.name)

    if json_out:
        typer.echo(json.dumps({"results": results}, indent=2))
    else:
        from ..output.formatters import format_results
        output = format_results(results, verbose=verbose)
        typer.echo(output)
        if failures:
            typer.secho(f"\n{len(failures)} input(s) too new: {', '.join(failures)}", fg=typer.colors.RED)
            raise typer.Exit(code=1)
        else:
            typer.secho("All inputs satisfy the minimum age requirement.", fg=typer.colors.GREEN)

if __name__ == "__main__":
    app()
