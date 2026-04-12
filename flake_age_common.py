"""Compatibility shim for the historic `nix_flake_age_*` scripts.

The original scripts (`nix_flake_age_filter.py` and `nix_flake_age_update.py`) were
written to import symbols from a flat module called ``flake_age_common``.  After
the refactor the implementation lives in the package
``flake_age_filter.core``.  To keep the legacy entry‑points functional we expose a
thin wrapper that re‑exports the public API from the new package.

Only the symbols that are actually used by the wrappers are re‑exported:

* ``run_git`` – thin subprocess wrapper.
* ``resolve_default_ref`` – determines the default branch/tag.
* ``get_commit_timestamp`` – fetches a commit timestamp (git or GitHub API).
* ``find_oldest_commit_meeting_age`` – helper that searches for an older commit.
* ``read_flake_inputs`` – parses ``flake.lock`` into ``FlakeInput`` objects.
* ``FlakeInput`` – immutable dataclass representing a locked input.
* ``check_age`` & ``format_duration`` – the ``whenever`` based age utilities.
* All custom exception classes from ``flake_age_filter.core.errors``.

The module is deliberately small and has no side effects; importing it simply
adds the selected names to the module namespace.
"""

# Re‑export core utilities
from flake_age_filter.core.git_ops import (
    run_git,
    resolve_default_ref,
    get_commit_timestamp,
    find_oldest_commit_meeting_age,
    GitCommandError,
)
from flake_age_filter.core.lock_file import read_flake_inputs
from flake_age_filter.core.models import FlakeInput
from flake_age_filter.core.age_check import check_age, format_duration
from flake_age_filter.core.errors import (
    FlakeAgeError,
    FlakeLockNotFoundError,
    CommitFetchError,
    RateLimitError,
    AgeValidationError,
    NixExecutionError,
)

__all__ = [
    "run_git",
    "resolve_default_ref",
    "get_commit_timestamp",
    "find_oldest_commit_meeting_age",
    "GitCommandError",
    "read_flake_inputs",
    "FlakeInput",
    "check_age",
    "format_duration",
    "FlakeAgeError",
    "FlakeLockNotFoundError",
    "CommitFetchError",
    "RateLimitError",
    "AgeValidationError",
    "NixExecutionError",
]
