"""CLI package for nix-flake-age-filter.

Provides verify and update commands for checking and updating
flake inputs against minimum age requirements.
"""

from __future__ import annotations

from .main import app

__all__ = ["app"]
