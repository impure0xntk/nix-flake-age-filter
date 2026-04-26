# External Tools and Libraries

| Tool / Library | Purpose | Version |
|----------------|---------|---------|
| `git` CLI | Fetch commit timestamps and refs | any (>=2.30) |
| `nix` CLI | Optional flake update and lock generation | any (>=2.18) |
| `rich` | Pretty console output and tables | >=13.0 |
| `whenever` | UTC datetime handling (Instant) | >=0.3 |
| `typer` | CLI framework for verify/update subcommands | >=0.12 |
| `pygit2` | Git operations via libgit2 (optional backend) | >=1.14 |
| `requests` | HTTP requests for GitHub API backend | >=2.31 |
| `pytest` | Test framework | >=7.0 |
| `mypy` | Static type checking | >=1.0 |
| `ruff` | Linting and auto-formatting | >=0.3 |
| `click` | Underlying CLI library for Typer | transitive |
| `shellingham` | Shell detection for Typer | transitive |
| `typing-extensions` | Backport of typing features | For Python 3.9+ |

These tools are used directly or as dependencies of the `nix-flake-age-filter` package. The list will be kept up-to-date as the project evolves.

## Backend-Specific Dependencies

### subprocess backend (default)
- No additional dependencies beyond `git` CLI
- Uses `subprocess` module to call git commands

### pygit2 backend
- Requires `pygit2` package
- System library `libgit2` must be installed
- Faster than subprocess for bulk operations

### github backend
- Requires `requests` package
- Network access to GitHub API v3
- Optional `GITHUB_TOKEN` environment variable for higher rate limits

## Development Tools

| Tool | Purpose | Notes |
|------|---------|-------|
| `pytest` | Run unit and integration tests | `python -m pytest` |
| `mypy` | Static type checking | `mypy src/` |
| `ruff` | Linting and formatting | `ruff check .` and `ruff format .` |
| `pre-commit` | Git hooks (optional) | See `.pre-commit-config.yaml` |

## Version Management

Python version: >=3.9 (see `pyproject.toml` `requires-python`)
