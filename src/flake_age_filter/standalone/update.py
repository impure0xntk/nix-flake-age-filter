"""Standalone update script for nix-flake-age-filter.

This version purposefully avoids optional third‑party dependencies (``pygit2``
and ``requests``).  It relies only on the standard library and the core
utilities that wrap the ``git`` command.  The behaviour mirrors the original
``nix_flake_age_update_standalone.py`` but forwards all heavy lifting to the
functions in :pymod:`flake_age_filter.core`.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import List

from ..core.lock_file import read_flake_inputs
from ..core.git_ops import (
    get_commit_timestamp,
    resolve_default_ref,
    run_git,
    git_env_no_prompt,
)
from ..core.age_check import check_age, format_duration
from ..core.models import FlakeInput


def _build_override_url(inp: FlakeInput, rev: str) -> str:
    """Return a ``flake`` URL that pins ``rev`` for the given input.

    The function mirrors the logic from the legacy script: ``github:owner/repo``
    becomes ``github:owner/repo/<rev>``; other sources keep their original scheme
    but add ``?rev=`` when appropriate.
    """
    url = inp.to_flake_url(rev)
    if not url:
        raise ValueError(f"cannot build flake URL for input {inp.name}")
    return f"{inp.name}={url}"


def _process_input(
    inp: FlakeInput, min_age: int, now_ts: int, timeout: int
) -> dict:
    """Find a commit that satisfies ``min_age`` for a single input.

    Returns a dictionary compatible with the original script's output schema.
    """
    # Resolve the ref to use (branch/tag or default HEAD)
    git_url = inp.to_git_url()
    if not git_url:
        return {"ok": False, "error": "non‑git input"}

    ref = inp.ref
    effective_ref = resolve_default_ref(git_url, ref, timeout)

    # Try to obtain a timestamp for the candidate rev (starting with the locked rev)
    candidate_rev = inp.rev or effective_ref
    ts_res = get_commit_timestamp(git_url, candidate_rev, timeout)
    if not ts_res.get("ok"):
        return {"ok": False, "error": ts_res.get("error")}

    ts = ts_res["timestamp"]
    age_res = check_age(ts, min_age, now_ts)
    if age_res["ok"]:
        return {
            "ok": True,
            "rev": candidate_rev,
            "timestamp": ts,
            "age_days": age_res["age_days"],
        }
    return {"ok": False, "error": age_res["error"]}


def main(argv: List[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="nix-flake-age-update-standalone",
        description="Update flake inputs while respecting a minimum commit age.",
    )
    parser.add_argument(
        "--min-age",
        type=int,
        required=True,
        help="Minimum age in days for a commit to be considered safe.",
    )
    parser.add_argument(
        "--flake-lock",
        type=Path,
        default=Path("flake.lock"),
        help="Path to the lock file (default: ./flake.lock)",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=120,
        help="Network/git timeout in seconds.",
    )
    parser.add_argument(
        "inputs",
        nargs="*",
        help="Specific input names to update (default: all).",
    )
    args = parser.parse_args(argv)

    try:
        inputs = read_flake_inputs(args.flake_lock)
    except Exception as exc:
        print(f"Failed to read flake.lock: {exc}", file=sys.stderr)
        return 1

    if args.inputs:
        inputs = [i for i in inputs if i.name in args.inputs]

    now_ts = int(__import__("time").time())
    results = {}
    overrides = []
    for inp in inputs:
        res = _process_input(inp, args.min_age, now_ts, args.timeout)
        results[inp.name] = res
        if res.get("ok"):
            overrides.append(_build_override_url(inp, res["rev"]))

    # Print a simple JSON‑like summary (compatible with the original script)
    import json
    print(json.dumps({"results": results, "overrides": overrides}, indent=2))
    return 0

if __name__ == "__main__":
    sys.exit(main())
