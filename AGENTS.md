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
├── flake_age_common.py       ── Shared data classes, git ops, age math
├── nix_flake_age_filter.py   ── `verify` subcommand (validate-only)
├── nix_flake_age_update.py   ── `update` subcommand (walk history + override-input)
└── flake_age_filter/         ── Plugin architecture (WIP)
```

## Date/Time Handling (CRITICAL)

### Current State
- `datetime.datetime.fromtimestamp(ts, tz=timezone.utc)` — Unix timestamp → UTC datetime
- `datetime.now(tz=timezone.utc)` — Current time
- `datetime.fromisoformat(str)` — ISO string parsing
- **All timestamps stored and compared as integers (Unix epoch or ISO strings)**
- No timezone conversions needed — everything is UTC-native
- Display formatting only: `.strftime("%Y-%m-%d %H:%M UTC")`

### Migration to `whenever` (planned)
When migrating to the `whenever` library, follow these rules:

| Current (stdlib) | Target (whenever) | Notes |
|---|---|---|
| `datetime.fromtimestamp(ts, tz=timezone.utc)` | `Instant.from_timestamp(ts)` | Primary conversion for commit timestamps |
| `datetime.now(tz=timezone.utc)` | `Instant.now()` | Current time |
| `datetime.fromisoformat(s.replace("Z","+00:00"))` | `Instant.parse_iso(s)` | ISO parsing |
| `dt.strftime(fmt)` | `str(dt)` or `dt.format(fmt)` | Formatting |
| `int(dt.timestamp())` | `dt.seconds` | Extract epoch seconds |

**Never use**: `ZonedDateTime`, `PlainDateTime`, or any timezone-aware types.
This project only operates on UTC moments-in-time.

## Key Data Flow

```
flake.lock → extract inputs → git ls-remote / git fetch → unix timestamp
                                                          ↓
                                      compare (now_ts - min_age_days * 86400)
                                                          ↓
                                      PASS / FAIL / WAIT / ERROR
```

## External Dependencies

| Dependency | Purpose | Notes |
|---|---|---|
| `git` CLI | Fetch commits, list refs, get timestamps | Must be available |
| `nix` CLI | `flake update --override-input`, lock generation | Optional (fallback to git) |
| `rich` | Colored CLI output | Python package |

## Testing

- Tests should mock `run_git` and `run_cmd` in `flake_age_common`
- Use sample `flake.lock` JSON fixtures
- Test edge cases: empty lock, nixpkgs exclusion, refs not found

## Important Constraints

1. **Purity**: Nix flakes require reproducibility — no `builtins.currentTime`
2. **Git protocol only**: No GitHub API keys; works with any git-compatible host
3. **No narHash calculation**: Computed by `nix flake update`, never manually
4. **Fallback support**: When `nix` binary is absent, build `flake.lock` from git history directly

## Coding Standards

- Type hints on all public functions
- `dict` return values with `"ok": bool` for error handling (result pattern)
- Minimal side effects; isolate I/O from logic
- stderr for progress/logging, stdout for final output (--json)
