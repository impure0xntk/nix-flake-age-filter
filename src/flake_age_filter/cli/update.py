"""CLI command to update flake inputs while respecting a minimum commit age.

The implementation mirrors the original ``nix_flake_age_update.py`` script but
uses the new core modules and Typer for a clean sub‑command interface.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import List, Dict, Optional

import typer

from ..core.lock_file import read_flake_inputs
from ..core import git_ops, list_backends
from ..core.git_ops import set_backend

from ..core.models import FlakeInput
from ..core.errors import FlakeAgeError
from whenever import Instant


# Helper functions for subprocess operations
def run_cmd(cmd: list, env_overrides: dict | None = None, timeout: int = 300):
    """Run a command and return (returncode, stdout, stderr)."""
    import subprocess
    import os
    env = os.environ.copy()
    env["GIT_TERMINAL_PROMPT"] = "0"
    if env_overrides:
        env.update(env_overrides)
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, env=env)
    return result.returncode, result.stdout, result.stderr


def git_env_no_prompt():
    """Return environment variables to disable git prompts."""
    return {"GIT_TERMINAL_PROMPT": "0"}

app = typer.Typer(
    help="Update flake inputs, ensuring each commit is at least a given age."
)


def _get_token_from_env() -> Optional[str]:
    """Get GitHub token from environment.
    
    Checks GITHUB_TOKEN and GH_TOKEN environment variables.
    
    Returns:
        Token string or None if not set.
    """
    return os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")


def _choose_rev(
    inp: FlakeInput,
    min_age: int,
    timeout: int,
    method: str = "auto",
    now_ts: int | None = None,
    verbose: bool = False,
) -> Dict[str, object] | None:
    """Return a dict with a suitable rev (or error) for *inp*.

    First checks if the locked revision (if present) is old enough.
    If so, returns that revision.
    Otherwise, searches for the newest commit that is at least min_age days old.
    Returns ``None`` for non‑git inputs (e.g. ``path`` type) which are skipped
    from the age check, and for git inputs when the newest suitable commit
    matches the currently locked revision (indicating no update is needed).
    """
    git_url = inp.to_git_url()
    if not git_url:
        # Skip path inputs – they are local and have no remote git history.
        return None

    # Determine current time for cutoff calculation.
    if now_ts is None:
        now_ts = int(Instant.now().timestamp())
    now_instant = Instant.from_timestamp(now_ts)

    # Always search for the newest commit that is at least min_age days old.
    # This ensures we get the latest commit that meets the age requirement,
    # not just keep the current one if it happens to be old enough.
    find_res = git_ops.find_oldest_commit_meeting_age(
        git_url=git_url,
        ref=inp.ref,
        min_age_days=min_age,
        timeout=timeout,
        method=method,
        now=now_instant,
        verbose=verbose,
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
    timeout: int = typer.Option(
        300, "--timeout", help="Network/git timeout in seconds (default: 300)"
    ),
    inputs: List[str] = typer.Option(
        None, "--inputs", help="Specific inputs to update (default: all)"
    ),
    dry_run: bool = typer.Option(
        False, "--dry-run", help="Print overrides without running nix"
    ),
    json_out: bool = typer.Option(False, "--json", help="Emit JSON result"),
    verbose: bool = typer.Option(
        False, "--verbose", help="Show detailed per‑input info"
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
    """Update flake inputs that are older than ``min_age`` days.

    For each input that passes the age check a ``--override-input`` argument is
    constructed and passed to ``nix flake update``.  When ``--dry-run`` is set the
    command is not executed – only the generated overrides are printed.
    """
    # Validate method parameter early
    valid_methods = ["auto"] + list_backends()
    if method not in valid_methods:
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
    overrides: List[str] = []
    failures: List[str] = []

    from ..core.parallel import execute_parallel

    def _process_update_inp(inp: FlakeInput) -> dict | None:
        return _choose_rev(inp, min_age, timeout, method=method, now_ts=now_ts, verbose=verbose)

    processed = execute_parallel(inputs_all, _process_update_inp, parallel)
    for inp, res in processed:
        if res is None:
            continue
        if not isinstance(res, dict):
            failures.append(inp.name)
            results.append(
                {
                    "input": inp.name,
                    "ok": False,
                    "error": f"Unexpected result type: {type(res)}",
                }
            )
            continue
        results.append({"input": inp.name, **res})
        if res.get("ok"):
            overrides.append(inp.to_flake_url(res["rev"]))
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
    # Determine the flake root directory from the flake.lock path.
    flake_root = flake_lock.parent
    # Build cmd: nix flake lock <flake-root> --override-input <name> <url> ...
    # NOTE: --override-input implies --no-write-lock-file for nix flake update,
    # so we use nix flake lock instead to write the overrides to the lock file.
    cmd = ["nix", "flake", "lock", str(flake_root)]
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
    rc, out, err = run_cmd(
        cmd, env_overrides=git_env_no_prompt(), timeout=timeout * 2
    )
    if rc != 0:
        typer.echo(err or out, err=True)
        raise typer.Exit(code=rc if rc > 0 else 1)
    typer.echo(out)


if __name__ == "__main__":
    app()
