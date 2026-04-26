"""Shared utilities for CLI commands."""

from __future__ import annotations

import difflib
import os
from typing import Optional

import typer

from ..core import git_ops, list_backends


def get_token_from_env() -> Optional[str]:
    """Get GitHub token from environment.

    Checks GITHUB_TOKEN and GH_TOKEN environment variables.

    Returns:
        Token string or None if not set.
    """
    return os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")


def validate_method(method: str) -> None:
    """Validate the backend method parameter.

    Raises typer.Exit(code=1) with a helpful error message if invalid.
    """
    valid_methods = ["auto"] + list_backends()
    if method not in valid_methods:
        suggestions = difflib.get_close_matches(method, valid_methods, n=1, cutoff=0.6)
        msg = f"Error: Invalid method '{method}'. Valid methods: {', '.join(valid_methods)}"
        if suggestions:
            msg += f"\nDid you mean: '{suggestions[0]}'?"
        typer.secho(msg, fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1)


def setup_backend(method: str, token: Optional[str], verbose: bool) -> None:
    """Configure the global backend with token and verbosity."""
    if token or verbose:
        git_ops.set_backend(method, token=token, verbose=verbose)
    else:
        git_ops.set_backend(method)


def show_rate_limit_info(method: str, token: Optional[str], verbose: bool) -> None:
    """Display GitHub API rate limit information when relevant."""
    if not verbose or method not in ("github", "auto"):
        return

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
