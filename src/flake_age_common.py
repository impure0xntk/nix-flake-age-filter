"""Compatibility shim for the legacy ``flake_age_common`` module.

The original project stored all core logic in this single file.  After the
refactor the implementation lives in the ``flake_age_filter.core`` package.
This shim re‑exports the public symbols so that any external scripts that still
import ``flake_age_common`` continue to work without modification.
"""

from __future__ import annotations

# Re‑export the new implementations
from .flake_age_filter.core.age_check import check_age, format_duration  # noqa: F401
from .flake_age_filter.core.errors import (
    FlakeAgeError,
    FlakeLockNotFoundError,
    CommitFetchError,
    RateLimitError,
    AgeValidationError,
    NixExecutionError,
)  # noqa: F401
from .flake_age_filter.core.git_ops import (
    get_commit_timestamp,
    resolve_default_ref,
    run_git,
    git_env_no_prompt,
)  # noqa: F401
from .flake_age_filter.core.lock_file import read_flake_inputs  # noqa: F401
from .flake_age_filter.core.models import FlakeInput  # noqa: F401

__all__ = [
    "check_age",
    "format_duration",
    "FlakeAgeError",
    "FlakeLockNotFoundError",
    "CommitFetchError",
    "RateLimitError",
    "AgeValidationError",
    "NixExecutionError",
    "get_commit_timestamp",
    "resolve_default_ref",
    "run_git",
    "git_env_no_prompt",
    "read_flake_inputs",
    "FlakeInput",
]
