# nix-flake-age-filter

## Quickstart

Run directly via `nix run` with these verified commands (tested against the actual repository):

```bash
# Verify all inputs are at least 30 days old
nix run github:impure0xntk/nix-flake-age-filter -- verify --min-age 30 flake.lock

# Update inputs older than 30 days
nix run github:impure0xntk/nix-flake-age-filter -- update --min-age 30 flake.lock

# Update inputs older than 30 days (dry-run, no modifications)
nix run github:impure0xntk/nix-flake-age-filter -- update --min-age 30 --dry-run flake.lock
```

## Repository Overview

This repository provides a pure‑Python implementation of a *minimum release‑age* filter for Nix flake inputs. The tool validates that each input in `flake.lock` is older than a configurable number of days and can automatically downgrade inputs that are too recent. It is packaged as a standard Python library with a Typer‑based CLI (`nix-flake-age`).

The legacy entry points `nix_flake_age_filter.py`, `nix_flake_age_update.py` and the compatibility shim `flake_age_common.py` have been removed.

A lightweight CLI tool that enforces a **minimum commit age** on Nix flake inputs, similar to npm's `min-release-age`. It works with plain Git (no auth tokens) and can be used both as a library and as a command‑line utility.

## Motivation

Nix flakes pin dependencies via Git commits, but recent commits can still be malicious. This tool borrows npm's `min-release-age` concept (npm v11.10.0, pnpm, Yarn, Bun) to add a time-based safety gate.

Most supply chain attacks are caught within days. By enforcing a minimum age (e.g., 30 days), you create a cooling-off period that lets the community flag malicious releases before they reach your build.

Two subcommands: `verify` checks all inputs meet the threshold; `update` refreshes inputs while skipping fresh commits.

## Features

- **Verify** that every input in `flake.lock` is at least *N* days old.
- **Update** inputs while skipping those newer than the threshold.
- **Multiple Git backends**: subprocess (default), pygit2, GitHub API, or auto‑selection.
- Pure‑Python core with full type hints; optional `rich` for pretty tables.
- Typer‑based CLI with sub‑commands `verify` and `update`.
- Parallel execution for faster batch processing (`--parallel`).
- JSON output for automation pipelines (`--json`).
- Comprehensive unit‑test suite (`tests/`).

## Installation

```bash
# Recommended: use the Nix development shell
nix develop   # enters a devShell with all dependencies (including pytest)
```

## Usage

```bash
# Verify that all inputs are at least 30 days old
nix-flake-age verify --min-age 30 flake.lock

# Dry‑run an update (shows what would be overridden but does not modify)
nix-flake-age update --min-age 30 --dry-run flake.lock

# Emit JSON for automation pipelines
nix-flake-age verify --min-age 30 --json flake.lock
```

### Flags

| Flag | Description |
|------|-------------|
| `--min-age DAYS` | Minimum commit age in days (required). |
| `--dry-run` | Simulate the operation; no `nix flake update` is executed. |
| `--json` | Output results as JSON (machine‑readable). |
| `--verbose` | Show detailed progress information. |
| `--exclude INPUT` | Skip specific inputs; can be repeated. |
| `--parallel N` | Number of parallel workers (0=serial). |

## Development

### Running the test suite

```bash
# Enter the development environment (Nix shell)
# This provides all dependencies, including pytest
nix develop
```

### Continuous Integration

GitHub Actions runs the same commands (`nix develop -c python -m pytest -q`, `ruff`, `mypy`). See `.github/workflows/ci.yml`.

### Packaging

`pyproject.toml` defines the package and entry point:

After `pip install .`, the `nix-flake-age` command is available on the PATH.

## Contributing

1. Fork the repository.
2. Create a feature branch.
3. Write tests for your changes.
4. Ensure `nix develop && python -m pytest -q` passes.
5. Open a Pull Request.
