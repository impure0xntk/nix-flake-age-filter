"""CLI command to update flake inputs while respecting a minimum commit age.

The implementation mirrors the original ``nix_flake_age_update.py`` script but
uses the new core modules and Typer for a clean sub‑command interface.
"""

from __future__ import annotations

import concurrent.futures
import json
import subprocess
import sys
from pathlib import Path
from typing import List, Dict

import typer

from ..core.lock_file import read_flake_inputs
from ..core import git_ops

from ..core.age_check import check_age
from ..core.models import FlakeInput
from ..core.errors import FlakeAgeError

app = typer.Typer(help="Update flake inputs, ensuring each commit is at least a given age.")

def _choose_rev(
    inp: FlakeInput,
    min_age: int,
    timeout: int,
    method: str = "auto",
    now_ts: int | None = None,
) -> Dict[str, object] | None:
    """Return a dict with a suitable rev (or error) for *inp*.

    First checks if the locked revision (if present) is old enough.
    If so, returns that revision.
    Otherwise, searches for the newest commit that is at least min_age days old.
    Returns ``None`` for non‑git inputs (e.g. ``path`` type) which are skipped
    from the age check, and for git inputs when the newest suitable commit
    matches the currently locked revision (indicating no update is needed).
    """
    from datetime import datetime, timezone

    git_url = inp.to_git_url()
    if not git_url:
        # Skip path inputs – they are local and have no remote git history.
        return None

    # Determine current time for cutoff calculation.
    if now_ts is None:
        now_ts = int(datetime.now(tz=timezone.utc).timestamp())
    cutoff_ts = now_ts - min_age * 86_400
    now_dt = datetime.fromtimestamp(now_ts, tz=timezone.utc)

    # First, check if the locked revision (if present) is old enough.
    if inp.rev:
        locked_res = git_ops.get_commit_timestamp(git_url, inp.rev, timeout)
        if locked_res.get("ok"):
            locked_ts = locked_res["timestamp"]
            if locked_ts <= cutoff_ts:
                result = {"ok": True, "rev": inp.rev, "timestamp": locked_ts}
                return result

    # Then, search for the newest commit that is at least min_age days old.
    find_res = git_ops.find_oldest_commit_meeting_age(
        git_url=git_url,
        ref=inp.ref,
        min_age_days=min_age,
        timeout=timeout,
        locked_ts=None,
        input_name=inp.name,
        original=inp.original,
        method=method,
        now=now_dt,
    )
    if not find_res.get("ok"):
        # Propagate error.
        return find_res

    # If we have a locked revision and it matches the found rev, no update needed.
    if inp.rev and find_res["rev"] == inp.rev:
        return None

    # Otherwise, return the found commit.
    return {"ok": True, "rev": find_res["rev"], "timestamp": find_res["timestamp"]}

@app.command()
def update(
    min_age: int = typer.Option(..., "--min-age", help="Minimum commit age in days"),
    flake_lock: Path = typer.Argument(..., help="Path to flake.lock"),
    timeout: int = typer.Option(120, "--timeout", help="Network/git timeout in seconds"),
    inputs: List[str] = typer.Option(None, "--inputs", help="Specific inputs to update (default: all)"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Print overrides without running nix"),
    json_out: bool = typer.Option(False, "--json", help="Emit JSON result"),
    verbose: bool = typer.Option(False, "--verbose", help="Show detailed per‑input info"),
    parallel: int = typer.Option(4, "--parallel", help="Number of parallel workers (default=4)", min=0),
    method: str = typer.Option("auto", "--method", help="Commit search method: github, pygit2, subprocess, or auto"),
):
    """Update flake inputs that are older than ``min_age`` days.

    For each input that passes the age check a ``--override-input`` argument is
    constructed and passed to ``nix flake update``.  When ``--dry-run`` is set the
    command is not executed – only the generated overrides are printed.
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
    overrides: List[str] = []
    failures: List[str] = []



    from ..core.parallel import execute_parallel

    def _process_update_inp(inp: FlakeInput) -> dict | None:
        return _choose_rev(inp, min_age, timeout, method=method, now_ts=now_ts)

    processed = execute_parallel(inputs_all, _process_update_inp, parallel)
    for inp, res in processed:
        if res is None:
            continue
        typer.echo(f"DEBUG update: inp.name={inp.name}, res={res}, type={type(res)}", err=True)
        if not isinstance(res, dict):
            typer.echo(f"DEBUG update: Expected dict, got {type(res)} for {inp.name}", err=True)
            failures.append(inp.name)
            results.append({"input": inp.name, "ok": False, "error": f"Unexpected result type: {type(res)}"})
            continue
        results.append({"input": inp.name, **res})
        if res.get("ok"):
            overrides.append(inp.to_flake_url(res['rev']))
        else:
            failures.append(inp.name)

    if json_out:
        typer.echo(json.dumps({"results": results, "overrides": overrides}, indent=2))
        if failures:
            raise typer.Exit(code=1)
        return

    # Dry‑run handling – output overrides and exit successfully, ignoring failures.
    if dry_run:
        typer.secho("Dry‑run mode – generated overrides:", fg=typer.colors.CYAN)
        if overrides:
            for o in overrides:
                typer.echo(o)
        # Dry‑run should always exit successfully.
        raise typer.Exit(code=0)

    # Human‑readable output (non‑dry‑run)
    for r in results:
        status = "✅" if r.get("ok") else "❌"
        line = f"{status} {r['input']}"
        if r.get("ok"):
            line += f" -> {r['rev']}"
        if verbose:
            line += f" – {r.get('error', '')}"
        typer.echo(line)

    if failures:
        typer.secho(f"\nFailed inputs: {', '.join(failures)}", fg=typer.colors.RED)
        raise typer.Exit(code=1)

    # Run nix flake update with the constructed overrides.
    if not overrides:
        typer.secho("No overrides to apply.", fg=typer.colors.YELLOW)
        raise typer.Exit(code=0)
    # Build cmd: nix flake update --override-input <name> <url> --override-input ...
    cmd = ["nix", "flake", "update"]
    for o in overrides:
        # Split "name=url" into name and url for --override-input flag
        # The URL part may contain '=' (e.g., git+https://...?rev=xxx), so only split on the first '='
        if "=" not in o:
            typer.secho(f"Invalid override format: {o}", fg=typer.colors.RED)
            raise typer.Exit(code=1)
        name, url = o.split("=", 1)
        cmd.extend(["--override-input", name, url])
    typer.secho(f"Running: {' '.join(cmd)}", fg=typer.colors.BLUE)
    # Use a longer timeout for nix flake update (default 60s may be too short)
    rc, out, err = git_ops.run_cmd(cmd, env_overrides=git_ops.git_env_no_prompt(), timeout=timeout * 2)
    if rc != 0:
        typer.echo(err or out, err=True)
        raise typer.Exit(code=rc if rc > 0 else 1)
    typer.echo(out)

if __name__ == "__main__":
    app()
