"""CLI command to update flake inputs while respecting a minimum commit age.

The implementation mirrors the original ``nix_flake_age_update.py`` script but
uses the new core modules and Typer for a clean sub‑command interface.
"""

from __future__ import annotations

import json
import subprocess
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
from ..core.age_check import check_age
from ..core.models import FlakeInput
from ..core.errors import FlakeAgeError

app = typer.Typer(help="Update flake inputs, ensuring each commit is at least a given age.")

def _choose_rev(inp: FlakeInput, min_age: int, now_ts: int, timeout: int) -> Dict[str, object]:
    """Return a dict with a suitable rev (or error) for *inp*.

    The function first resolves the remote reference, then attempts to fetch the
    commit timestamp for the locked revision (or the default branch).  If the
    commit is newer than ``min_age`` the function searches for an older commit
    using ``core.git_ops.find_oldest_commit_meeting_age`` (which internally
    prefers the GitHub API).  The returned dict mimics the legacy script's
    output structure.
    """
    git_url = inp.to_git_url()
    if not git_url:
        return {"ok": False, "error": "non‑git input"}

    # Resolve the effective reference (branch/tag or remote default).
    effective_ref = resolve_default_ref(git_url, inp.ref, timeout)
    start_rev = inp.rev or effective_ref

    # Try the starting revision first.
    ts_res = get_commit_timestamp(git_url, start_rev, timeout)
    if not ts_res.get("ok"):
        return {"ok": False, "error": ts_res.get("error", "failed to fetch timestamp")}

    ts = ts_res["timestamp"]
    age_res = check_age(ts, min_age, now_ts)
    if age_res["ok"]:
        return {"ok": True, "rev": start_rev, "timestamp": ts}

    # Need to find an older commit.
    from ..core.git_ops import find_oldest_commit_meeting_age

    find_res = find_oldest_commit_meeting_age(
        git_url=git_url,
        ref=effective_ref,
        min_age_days=min_age,
        timeout=timeout,
        locked_ts=inp.rev and ts,
        input_name=inp.name,
        original=inp.original,
    )
    if find_res.get("ok"):
        return {"ok": True, "rev": find_res["rev"], "timestamp": find_res["timestamp"]}
    return {"ok": False, "error": find_res.get("error", "no suitable commit found")}

@app.command()
def update(
    min_age: int = typer.Option(..., "--min-age", help="Minimum commit age in days"),
    flake_lock: Path = typer.Option(Path("flake.lock"), "--flake-lock", help="Path to flake.lock"),
    timeout: int = typer.Option(120, "--timeout", help="Network/git timeout in seconds"),
    inputs: List[str] = typer.Option(None, "--inputs", help="Specific inputs to update (default: all)"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Print overrides without running nix"),
    json_out: bool = typer.Option(False, "--json", help="Emit JSON result"),
    verbose: bool = typer.Option(False, "--verbose", help="Show detailed per‑input info"),
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

    for inp in inputs_all:
        res = _choose_rev(inp, min_age, now_ts, timeout)
        results.append({"input": inp.name, **res})
        if res.get("ok"):
            overrides.append(f"{inp.name}={inp.to_flake_url(res['rev'])}")
        else:
            failures.append(inp.name)

    if json_out:
        typer.echo(json.dumps({"results": results, "overrides": overrides}, indent=2))
        if failures:
            raise typer.Exit(code=1)
        return

    # Human‑readable output
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

    # Run nix flake update with the constructed overrides unless dry‑run.
    if dry_run:
        typer.secho("Dry‑run mode – generated overrides:", fg=typer.colors.CYAN)
        for o in overrides:
            typer.echo(o)
    else:
        if not overrides:
            typer.secho("No overrides to apply.", fg=typer.colors.YELLOW)
            raise typer.Exit(code=0)
        cmd = ["nix", "flake", "update", "--override-input"] + overrides
        typer.secho(f"Running: {' '.join(cmd)}", fg=typer.colors.BLUE)
        rc, out, err = run_git(cmd, env_overrides=git_env_no_prompt())
        if rc != 0:
            typer.echo(err or out, err=True)
            raise typer.Exit(code=rc)
        typer.echo(out)

if __name__ == "__main__":
    app()
