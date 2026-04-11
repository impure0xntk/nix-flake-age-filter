# Architecture Design Document

## Overview

A tool that validates the commit dates of each input in a Nix Flake's `flake.lock`, allowing only commits older than a specified number of days.
This provides a concept equivalent to npm's `min-release-age` for the Nix ecosystem.

It provides two subcommands:

| Subcommand | Description |
|-------------|------|
| `verify` | Validates whether existing `flake.lock` inputs meet the minimum age requirement |
| `update` | Wraps `nix flake update` to adopt only commits that meet the minimum age requirement |

## Directory Structure

```
nix-flake-age-filter/
├── pyproject.toml              # Package definition, dependencies, entry points
├── README.md
├── flake.nix                   # Nix flake definition
├── shell.nix                   # Development shell
├── docs/
│   └── design.md               # This file
├── src/
│   ├── flake_age_common.py     # Legacy: Shared utilities (single-file version)
│   ├── nix_flake_age_filter.py # Legacy: verify subcommand (argparse-based)
│   ├── nix_flake_age_update.py # Legacy: update subcommand (argparse-based)
│   ├── flake_age_types.py     # New: Typed dataclasses (FetchResult, CommitSearchResult, etc.)
│   ├── age_check.py            # New: Age validation utilities (whenever-based)
│   ├── flake_lock.py           # New: flake.lock parsing and FlakeInput model
│   ├── git_operations.py       # New: Git CLI operations (ls-remote, fetch)
│   └── flake_age_filter/       # New: Modular package (WIP)
│       └── __init__.py         # Package init with version
├── tests/
│   └── (test files)
└── result                      # Nix build output (gitignored)
```

### Implementation Status

| Component | Status | Notes |
|-----------|--------|-------|
| `flake_age_common.py` | Stable | Legacy single-file implementation |
| `nix_flake_age_filter.py` | Stable | Uses `whenever` for datetime, argparse CLI |
| `nix_flake_age_update.py` | Stable | Legacy implementation with argparse |
| `flake_age_types.py` | New | Typed dataclasses for result objects |
| `flake_age_filter/` | WIP | Modular refactoring in progress |

## Dependencies

| Package | Purpose | Status |
|---------|---------|--------|
| `whenever` | Modern datetime library (UTC-native) | Active |
| `rich` | Console output formatting (tables, colored text) | Active |
| `typer` | CLI framework (new modules) | Active |
| `argparse` | CLI framework (legacy modules) | Legacy |
| `pygit2` | Git repository operations (libgit2 bindings) | Active |
| `requests` | HTTP client for GitHub API | Active |

### Note on Dependencies

- `PyGithub` is NOT used — direct `requests` calls to GitHub REST API instead
- `click` is NOT used — `typer` (new) and `argparse` (legacy) are the CLI frameworks
- `whenever` is adopted for datetime handling in new modules (see Date/Time Handling section)

## Component Design

### Overall Architecture

```
Legacy (Stable):                         New (WIP):
─────────────────────────────────────────────────────────────────────────
nix_flake_age_filter.py                  nix_flake_age_verify.py (typer)
    │                                         │
    ▼                                         ▼
flake_age_common.py                      flake_lock.py ──► FlakeInput
    │                                         │
    ▼                                         ▼
┌─────────────────┐                     age_check.py (whenever)
│ GitHub API      │                           │\│ (requests)      │                           ▼
│ pygit2 fallback │                     git_operations.py
└─────────────────┘                           │
                                              ▼
                                        commit_fetch.py
                                              │
                                              ▼
                                        flake_age_types.py
                                        (dataclasses)

nix_flake_age_update.py (argparse)
    │
    └────► flake_age_common.py
```

**Note:** The modular architecture (`flake_age_filter/` package) is WIP and not shown.

### core/ — Domain Logic

#### `flake_input.py` — FlakeInput Domain Model

Represents a single input in flake.lock. Holds information from `locked` and `original` contained in `nodes.<name>` of flake.lock.

```python
@dataclass(frozen=True)
class FlakeInput:
    name: str
    locked: dict
    original: dict
```

Responsibilities:
- Construct git URL (`to_git_url()`)
- Construct flake URL (`to_flake_url()`)
- Resolve target branch (`target_ref()`)
- Determine if nixpkgs (`is_nixpkgs()`)

URL construction supports GitHub, GitLab, SourceHut, generic git, indirect, and path types.

#### `lock_file.py` — flake.lock Parser

Parses `flake.lock` JSON and extracts only the direct root inputs.

```python
def parse_flake_lock(path: Path) -> dict:
    """Parse flake.lock and return JSON structure. Raises exception if file does not exist."""

def extract_locked_inputs(lock_data: dict) -> list[FlakeInput]:
    """Extract only the direct root inputs as a list of FlakeInput."""
```

Note that the determination logic differs depending on whether `nodes.root.inputs` is a dict or a list.

#### `age_check.py` — Age Evaluation

Determines whether the condition is met based on the commit's Unix timestamp and minimum age in days.

```python
def check_age(timestamp: int, min_age_days: int, now: datetime) -> AgeResult:
    """Calculate elapsed days and determine if threshold is met or exceeded."""

def format_duration(days: int) -> str:
    """Convert days to a human-readable string (e.g., "3w 2d", "1y 5w")."""
```

#### `errors.py` — Custom Exceptions

```python
class FlakeAgeError(Exception): ...
class FlakeLockNotFoundError(FlakeAgeError): ...
class CommitFetchError(FlakeAgeError): ...
class RateLimitError(FlakeAgeError): ...
class AgeValidationError(FlakeAgeError): ...
class NixExecutionError(FlakeAgeError): ...
```

Unify error handling with exceptions, replacing the existing `{"ok": False, "error": ...}` pattern.

### git_ops/ — Git Operations Layer

Protocol-based fallback chain: GitHub API → pygit2

#### `client.py` — GitClient Protocol

```python
class GitClient(Protocol):
    def commit_timestamp(self, url: str, rev: str, timeout: int) -> int: ...
    def find_commit_at_cutoff(self, url: str, ref: str, cutoff_ts: int, timeout: int) -> CommitSearchResult: ...
```

Retry with exponential backoff when rate limited.

#### `github_api.py` — GitHub REST API

**Current Implementation:** Direct `requests` calls to GitHub REST API.

| Purpose | Implementation |
|---------|----------------|
| Get timestamp for a specific SHA | `GET /repos/{owner}/{repo}/commits/{sha}` → `.commit.committer.date` |
| List commits on a ref | `GET /repos/{owner}/{repo}/commits?sha={ref}` |
| Rate limit handling | Check `X-RateLimit-Remaining` header, wait and retry |

If the `GITHUB_TOKEN` environment variable is set, authentication is automatic via `Authorization: Bearer` header, and the rate limit is increased (60/hr → 5000/hr).

**Fallback Chain:**
1. Try `gh` CLI if available (`gh api` command)
2. Use `requests` to GitHub REST API
3. Fall back to git protocol (ls-remote + fetch) for non-GitHub hosts

#### `libgit2.py` — pygit2 Operations

Direct git operations with pygit2 for non-GitHub hosts (GitLab, SourceHut, generic git).

Procedure:
1. Create a temporary bare repository with `pygit2.init_repository(path, bare=True)`
2. Add remote with `remote.create()`
3. Shallow fetch with `remote.fetch(depth=1)`
4. Get timestamp with `commit.commit_time`

When searching for a target commit, walk while incrementally expanding the depth.

### cli/ — Subcommands

#### verify `flake-age verify [OPTIONS] [FLAKE_LOCK]`

Validate an existing `flake.lock`.

Options:
- `--min-age` (required): Minimum age in days
- `--timeout`: Timeout in seconds per input
- `--skip-ref-check`: Skip ls-remote reference check
- `--exclude`: Exclude input name
- `--json`: JSON output
- `--verbose`/`-v`: Verbose output

Execution flow:
```
Parse flake.lock
→ For each input:
  1. Get commit timestamp via GitClient
  2. Evaluate age with check_age()
  3. Accumulate results
→ Output via formatter
→ Exit 1 if any FAIL/ERROR
```

#### update `flake-age update [OPTIONS] [INPUTS...]`

Wraps `nix flake update` to adopt only commits that meet the minimum age requirement.

Options:
- `--min-age` (required): Minimum age in days
- `--timeout`: Timeout in seconds per input
- `--exclude`: Exclude input name (default: `["self"]`)
- `--dry-run`: Do not execute nix
- `--json`: JSON output
- `--verbose`/`-v`: Verbose output
- `--flake-lock`: Path to flake.lock

Execution flow:
```
Check if flake.lock exists
  ├─ Does not exist → Extract inputs from flake.nix and generate flake.lock directly
  └─ Exists → Parse existing lock

→ For each input:
  1. Search for the latest commit meeting the condition via GitClient.find_commit_at_cutoff()
  2. Skip if the current locked_rev is sufficient
  3. If a qualifying commit is found, construct a flake URL
  4. Update with nix flake update --override-input
→ Output results
```

Fallback when `flake.lock` is missing:
1. Attempt initial lock generation with `nix flake lock`
2. If that fails, parse flake.nix with regex and resolve commits directly via pygit2/GitHub API
3. Generate flake.lock-compatible JSON directly

### output/ — Output

#### `formatters.py`

Provides formatted output using rich's `Table` and `Console`, and JSON output via `json.dumps`.

```python
def print_verify_table(results: list[VerifyResult], min_age: int, json_output: bool) -> None: ...
def print_update_summary(results: list[UpdateResult], json_output: bool, dry_run: bool) -> None: ...
def print_json(results: list[dict]) -> None: ...
```

## CLI Interface Specification

### Entry Point

```
flake-age --help
flake-age verify [OPTIONS] [FLAKE_LOCK]
flake-age update [OPTIONS] [INPUTS...]
```

Defined in pyproject.toml as follows:

```toml
[project.scripts]
flake-age = "flake_age_filter.__main__:main"
```

### `__main__.py`

```python
import click
from flake_age_filter.cli.verify import verify
from flake_age_filter.cli.update import update

@click.group()
@click.version_option()
def main():
    """CLI for validating and updating minimum age of Nix flake inputs"""
    pass

main.add_command(verify)
main.add_command(update)
```

## Data Flow

### verify Command

```
flake.lock ──► lock_file.parse_flake_lock() ──► dict
                                            │
                                            ▼
                          extract_locked_inputs() ──► list[FlakeInput]
                                                       │
                                            ┌──────────┴──────────┐
                                            ▼                      ▼
                              github_api.commit_timestamp    libgit2.commit_timestamp
                                            │                      │
                                            └──────────┬───────────┘
                                                       ▼
                                                 check_age()
                                                       │
                                                       ▼
                                              list[VerifyResult]
                                                       │
                                                       ▼
                                                formatters.py
```

### update Command

```
flake.lock exists?
  ├─ Yes → parse → list[FlakeInput]
  └─ No  → nix flake lock (or regex parse) → list[FlakeInput]
                                    │
                                    ▼
                find_commit_at_cutoff(GitClient)
                                    │
                            ┌───────┴───────┐
                            ▼               ▼
                       Existing commit   Qualifying
                       is sufficient     new commit found
                            │               │
                            ▼               ▼
                        Record result    Build override URL →
                           │             nix flake update
                           ▼               │
                                   list[UpdateResult]
                                            │
                                            ▼
                                       formatters.py
```

## Test Strategy

| Layer | Test Target | Method |
|--------|-----------|------|
| `core/flake_input` | URL conversion, ref resolution | Unit tests (no mocking needed) |
| `core/lock_file` | flake.lock parsing | Use fixture JSON |
| `core/age_check` | Date calculations | Boundary value tests (exactly at threshold, before/after) |
| `git_ops/github_api` | API calls | HTTP mocking with `responses` |
| `git_ops/libgit2` | pygit2 operations | Integration tests with temporary repositories |
| `cli/` | Subcommands | `click.testing.CliRunner` |

## Future Extension Points

- Configuration file (`.flake-age.toml`) for default values
- GitHub token authentication (`GITHUB_TOKEN` environment variable)
- Faster validation with parallel processing (`asyncio` + `aiohttp`)
- CI integration (automatic validation step in GitHub Actions)
- Additional output formats (JUnit XML, SARIF)
