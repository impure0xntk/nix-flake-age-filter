# AGENTS.md

## Project Overview

A Python CLI toolkit that enforces minimum-release-age checks on Nix flake inputs, providing supply-chain security similar to npm v11.10.0's `min-release-age`.

## Commands

- `nix-flake-age verify --min-age N flake.lock` — Validate all inputs meet minimum age
- `nix-flake-age update --min-age N [inputs...]` — Update inputs skipping fresh commits
- `nix-flake-age verify --current-date YYYY-MM-DD` — Reproducible checks

## Architecture

```
src/
└── flake_age_filter/
    ├── cli/                    ── Typer CLI commands
    │   ├── main.py             ── Entry point, app registration
    │   ├── verify.py           ── verify command
    │   ├── update.py           ── update command
    │   └── _common.py          ── CLI common utilities
    ├── core/                   ── Core logic
    │   ├── models.py           ── Data models (FlakeInput, etc.)
    │   ├── age_check.py        ── Age checking utilities
    │   ├── lock_file.py        ── flake.lock loading
    │   ├── git_ops.py          ── Git operations
    │   ├── flake_input.py      ── FlakeInput implementation
    │   ├── parallel.py         ── Parallel processing
    │   ├── errors.py           ── Error definitions
    │   └── backends/           ── Backend implementations
    │       ├── base.py         ── Base class
    │       ├── registry.py     ── Backend registry
    │       ├── github_api_backend.py
    │       └── subprocess_backend.py
    └── output/                 ── Output formatting
        └── formatters.py       ── Rich formatters
```

## Date/Time Handling (CRITICAL)

Uses the `whenever` library (migration completed):

| Operation | whenever Code | Notes |
|---|---|---|
| Unix timestamp → UTC | `Instant.from_timestamp(ts)` | Commit timestamp conversion |
| Current time | `Instant.now()` | |
| ISO string parsing | `Instant.parse_iso(s)` | |
| Formatting | `str(dt)` or `dt.format(fmt)` | |
| Get epoch seconds | `dt.timestamp()` | |

**Never use**: `ZonedDateTime`, `PlainDateTime`, or any timezone-aware types.
This project only operates on UTC moments-in-time.

## Data Flow

```
flake.lock → extract inputs → git ls-remote / git fetch → Unix timestamp
                                                    ↓
                                    compare (now_ts - min_age_days * 86400)
                                                    ↓
                                    PASS / FAIL / WAIT / ERROR
```

## External Dependencies

| Dependency | Purpose | Notes |
|---|---|---|
| `git` CLI | Commit retrieval, ref listing, timestamp extraction | Required |
| `nix` CLI | `flake update --override-input`, lock generation | Optional (fallback to git) |
| `rich` | Colored CLI output | Python package |
| `typer` | CLI framework | |
| `whenever` | Date/time handling | UTC Instant only |
| `requests` | HTTP communication (GitHub API, etc.) | |

## Testing

- Mock backend classes in `core/backends/base.py`
- Use sample `flake.lock` JSON fixtures
- Edge cases: empty lock, nixpkgs exclusion, refs not found

## Key Constraints

1. **Purity**: Nix flakes require reproducibility — no `builtins.currentTime`
2. **Git protocol only**: No GitHub API keys required; works with any git-compatible host
3. **No narHash calculation**: Computed by `nix flake update`, never manually
4. **Fallback support**: When `nix` binary is absent, build `flake.lock` from git history directly

## Coding Standards

- Type hints on all public functions
- Error handling via `dict` return values with `"ok": bool` (result pattern)
- Minimize side effects; isolate I/O from logic
- Progress/logging to stderr, final output to stdout (--json)
