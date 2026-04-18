# nix-flake-age-filter

**Repository Overview**

This repository provides a pure‑Python implementation of a *minimum release‑age* filter for Nix flake inputs. The tool validates that each input in `flake.lock` is older than a configurable number of days and can automatically downgrade inputs that are too recent. It is packaged as a standard Python library with a Typer‑based CLI (`flake-age`).

The legacy entry points `nix_flake_age_filter.py`, `nix_flake_age_update.py` and the compatibility shim `flake_age_common.py` have been removed.


A lightweight CLI tool that enforces a **minimum commit age** on Nix flake inputs, similar to npm's `min-release-age`. It works with plain Git (no auth tokens) and can be used both as a library and as a command‑line utility.

## Features

- **Verify** that every input in `flake.lock` is at least *N* days old.
- **Update** inputs while skipping those newer than the threshold.
- Pure‑Python core with full type hints; optional `rich` for pretty tables.
- Typer‑based CLI with sub‑commands `verify` and `update`.
- Stand‑alone script (`standalone/update.py`) that only requires the standard library.
- Comprehensive unit‑test suite (`tests/`).

## Installation

```bash
# Recommended: use the Nix development shell
nix develop   # enters a devShell with all dependencies (including pytest)
```

Or install via pip after building the package:

```bash
pip install .
```

## Usage

```bash
# Verify that all inputs are at least 30 days old
flake-age verify --min-age 30 flake.lock

# Dry‑run an update (shows what would be overridden but does not modify)
flake-age update --min-age 30 --dry-run flake.lock

# Emit JSON for automation pipelines
flake-age verify --min-age 30 --json flake.lock
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

# Run the full test suite using pytest (recommended)
python -m pytest -q
```


```bash
# Enter the development environment
nix develop

# Execute all unit tests
python -m unittest discover -v
```

The suite covers:

- Model helpers (`tests/test_models.py`).
- Lock‑file parsing (`tests/test_lock_file.py`).
- Age calculations (`tests/unit/test_age_check.py`).
- Git utilities (`tests/unit/test_git_ops.py`).
- CLI behavior (`tests/unit/test_cli_verify.py`, `tests/unit/test_cli_update.py`).

### Lint & type checking

```bash
ruff check src tests
mypy src
```

### Continuous Integration

GitHub Actions runs the same commands (`nix develop -c python -m unittest discover -v`, `ruff`, `mypy`). See `.github/workflows/ci.yml`.

### Packaging

`pyproject.toml` defines the package and entry point:

```toml
[project]
name = "flake-age-filter"
...
packages = [{include = "flake_age_filter"}]

[project.scripts]
flake-age = "flake_age_filter.cli.main:app"
```

After `pip install .`, the `flake-age` command is available on the PATH.

---

## Contributing

1. Fork the repository.
2. Create a feature branch.
3. Write tests for your changes.
4. Ensure `nix develop && python -m unittest discover -v` passes.
5. Open a Pull Request.
