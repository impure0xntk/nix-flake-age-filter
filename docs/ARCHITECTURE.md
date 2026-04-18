# Architecture Overview

## Directory Structure
```
src/
└── flake_age_filter/         # Core implementation (Typer CLI, core utils)
    ├── cli/                  # Typer commands (verify, update)
    │   ├── main.py           # Top-level Typer app
    │   ├── verify.py         # Verify subcommand
    │   └── update.py         # Update subcommand
    ├── core/                 # Core logic and utilities
    │   ├── __init__.py
    │   ├── age_check.py      # Age validation logic
    │   ├── errors.py         # Custom exception types
    │   ├── flake_input.py    # Flake input representation
    │   ├── git_ops.py        # Git operations wrapper
    │   ├── lock_file.py      # flake.lock parsing and serialization
    │   ├── models.py         # Data models and enums
    │   └── parallel.py       # Parallel execution utilities
    ├── output/               # Output formatting (JSON, table, etc.)
    │   └ __init__.py
    └── standalone/           # Standalone scripts (no external deps)
        └── update.py         # Minimal update script using only stdlib
```

## Data Flow
```mermaid
flowchart TD
    A[Parse `flake.lock`] --> B[Extract input references]
    B --> C[For each input: resolve revision via git]
    C --> D[Fetch commit timestamp (Unix epoch)]
    D --> E[Compare age against `--min-age` threshold]
    E --> F{Pass?}
    F -->|Yes| G[Emit pass status]
    F -->|No| H[Emit fail/wait status]
    G --> I[JSON / console output]
    H --> I
```

## External Dependencies
| Dependency | Purpose | Notes |
|------------|---------|-------|
| `git` CLI | Fetch commits, list refs, get timestamps | Must be available |
| `nix` CLI | Optional: `flake update --override-input` for lock generation | Fallback to git-only if absent |
| `rich` | Colored CLI output and tables | Used in CLI for pretty printing |
| `whenever` | Unified date-time handling (replaces `datetime`) | Used throughout for UTC timestamps |
| `typer` | CLI framework | Builds the `verify` and `update` subcommands |
| `pygit2` | Git operations (alternative to subprocess) | Used for efficient git interactions |
| `requests` | HTTP requests (if needed for metadata) | Optional, used in some utils |
| `click` | Underlying CLI library for Typer | Transitive dependency |
| `shellingham` | Shell detection for Typer | Transitive dependency |
| `typing-extensions` | Backport of typing features | For compatibility with Python 3.9+ |

## Date/Time Handling (CRITICAL)
All timestamps are handled as UTC moments-in-time using the `whenever` library:
- `Instant.from_timestamp(ts)` — Unix timestamp → UTC Instant
- `Instant.now()` — Current time
- `Instant.parse_iso(s)` — ISO string parsing (e.g., from git logs)
- `Instant.seconds` — Extract epoch seconds for comparisons
- `str(dt)` or `dt.format(fmt)` — Formatting for display

**Never use**: `ZonedDateTime`, `PlainDateTime`, or any timezone-aware types.
This project only operates on UTC moments-in-time.

## Key Data Flow Details
1. **flake.lock parsing**: Load JSON, extract `nodes` → map of input names to metadata (including `locked` object with `rev`, `type`, etc.)
2. **Git resolution**: For each input:
   - If `type` is "git", use `git ls-remote <url> <ref>` to get latest commit SHA for the ref (branch/tag)
   - If `type` is "github", "gitlab", "sourcehut", etc., treat as git (same process)
   - If `type` is "local", skip (no age check)
   - If `type` is "path", skip (no age check)
3. **Timestamp extraction**: 
   - For resolved commit SHA, use `git show -s --format=%at <sha>` to get Unix timestamp
   - Alternatively, use `pygit2` to lookup commit time directly
4. **Age comparison**: 
   - `now_ts - commit_ts >= min_age_days * 86400` → PASS
   - Else → FAIL (too new)
5. **Update logic** (`nix-flake-age update`):
   - For each input that fails age check, attempt to find an older commit:
     - Use `git log --reverse --since=<date> --grep=.` to find first commit after threshold date
     - Or use `git rev-list -n 1 --before=<date> <ref>` to get commit just before threshold
   - If found, override input with that revision via `nix flake update --override-input <name> <url>?rev=<sha>`
   - If not found, leave as-is (or report error depending on mode)

## Migration Notes
- Legacy files `flake_age_common.py`, `nix_flake_age_filter.py`, `nix_flake_age_update.py` have been removed.
- All logic now resides in `src/flake_age_filter/` with clear separation of concerns.
- The `whenever` library is already adopted (see `core/models.py` and `core/age_check.py`).

## Future Extensions
- Plugin system for custom age policies (e.g., allow certain inputs to bypass age check).
- Integration with GitHub/GitLab APIs for faster timestamp lookup (optional, rate-limited).
- Windows compatibility testing and CI.
- Pre-commit hook integration.
