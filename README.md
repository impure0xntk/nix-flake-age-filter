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

Output Examples

```bash
# Verify command output with --min-age 3 days
$ nix run github:impure0xntk/nix-flake-age-filter -- verify --min-age 3  flake.lock
┏━━━━━━━━━━━━━━━━━━┳━━━━━━━━┳━━━━━━━━━━━━━━┳━━━━━━━━━┳━━━━━━━━━━━┓
┃ Input            ┃ Status ┃ Rev          ┃ Age (d) ┃ Deviation ┃
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
│ flake-utils      │ ✅    │ 11707dc2f618 │ 530     │ +527      │
│ mcp-servers-nix  │ ✅    │ d0cc2a91635e │ 7       │ +4        │
│ nix4vscode       │ ✅    │ 5672772ca167 │ 4       │ +1        │
│ nixos            │ ✅    │ 10e7ad5bbcb4 │ 7       │ +4        │
│ nix-ai-tools     │ ✅    │ 5c7895e3b5ea │ 4       │ +1        │
│ nixpkgs          │ ✅    │ c3684e2a7ade │ 4       │ +1        │
│ nixos-hardware   │ ✅    │ 2096f3f411ce │ 4       │ +1        │
│ nur              │ ✅    │ 73ff59538e64 │ 4       │ +1        │
│ nixpkgs-unstable │ ✅    │ 01fbdeef22b7 │ 5       │ +2        │
│ sops-nix         │ ✅    │ bef289e22489 │ 7       │ +4        │
│ vscode-server    │ ✅    │ 92ce71c3ba5a │ 84      │ +81       │
└──────────────────┴────────┴──────────────┴─────────┴───────────┘

All inputs satisfy the minimum age requirement.

# Update with --min-age 3
$ nix run github:impure0xntk/nix-flake-age-filter -- update --min-age 3  flake.lock
┏━━━━━━━━━━━━━━━━━━┳━━━━━━━━┳━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━┳━━━━━━━━━┳━━━━━━━━━━━┓
┃ Input            ┃ Status ┃ Current Rev  ┃ New Rev      ┃ Age (d) ┃ Deviation ┃
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
│ mcp-servers-nix  │ ✅    │ d0cc2a91635e │ 978f319b9142 │ 4       │ +1        │
│ nix4vscode       │ ✅    │ 5672772ca167 │ aeaa8983f0ab │ 3       │ +0        │
│ nix-ai-tools     │ ✅    │ 5c7895e3b5ea │ 6b4673fddbbe │ 3       │ +0        │
│ nixos            │ ✅    │ 10e7ad5bbcb4 │ a4bf06618f0b │ 3       │ +0        │
│ nixpkgs          │ ✅    │ c3684e2a7ade │ 8e838372e0f7 │ 3       │ +0        │
│ nur              │ ✅    │ 73ff59538e64 │ 9c7069f64fea │ 3       │ +0        │
│ nixpkgs-unstable │ ✅    │ 01fbdeef22b7 │ 8e47d9eee184 │ 3       │ +0        │
└──────────────────┴────────┴──────────────┴──────────────┴─────────┴───────────┘

Running: nix flake lock . --override-input mcp-servers-nix github:natsukium/mcp-servers-nix/978f319b9142e00f1415abc587f935a7e40263a4 --override-input nix4vscode github:nix-community/nix4vscode/aeaa8983f0abd865c2363bd634a03db27b8b3857 --override-input nix-ai-tools github:numtide/nix-ai-tools/6b4673fddbbe1f2656b3fa8d2a32666570aafbfa --override-input nixos github:Nixos/nixpkgs/a4bf06618f0b5ee50f14ed8f0da77d34ecc19160 --override-input nixpkgs github:Nixos/nixpkgs/8e838372e0f75bc4271d5170c233481846a73768 --override-input nur github:nix-community/NUR/9c7069f64feaa27fddfb4454647ffd6a623a8da4 --override-input nixpkgs-unstable github:Nixos/nixpkgs/8e47d9eee184fb4783dda7a2024c36eb0b310ce3

# Then verify with --min-age 4: some input is too new, some are old
$ nix run github:impure0xntk/nix-flake-age-filter -- verify --min-age 4  flake.lock
┏━━━━━━━━━━━━━━━━━━┳━━━━━━━━┳━━━━━━━━━━━━━━┳━━━━━━━━━┳━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃ Input            ┃ Status ┃ Rev          ┃ Age (d) ┃ Deviation ┃ Error                     ┃
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
│ flake-utils      │ ✅    │ 11707dc2f618 │ 530     │ +526      │ -                         │
│ mcp-servers-nix  │ ✅    │ 978f319b9142 │ 4       │ +0        │ -                         │
│ nix-ai-tools     │ ✖     │ 6b4673fddbbe │ 3       │ -1        │ only 3d old (minimum: 4d) │
│ nix4vscode       │ ✖     │ aeaa8983f0ab │ 3       │ -1        │ only 3d old (minimum: 4d) │
│ nixos            │ ✖     │ a4bf06618f0b │ 3       │ -1        │ only 3d old (minimum: 4d) │
│ nixpkgs-unstable │ ✖     │ 8e47d9eee184 │ 3       │ -1        │ only 3d old (minimum: 4d) │
│ nur              │ ✖     │ 9c7069f64fea │ 3       │ -1        │ only 3d old (minimum: 4d) │
│ nixpkgs          │ ✖     │ 8e838372e0f7 │ 3       │ -1        │ only 3d old (minimum: 4d) │
│ sops-nix         │ ✅    │ bef289e22489 │ 7       │ +3        │ -                         │
│ vscode-server    │ ✅    │ 92ce71c3ba5a │ 84      │ +80       │ -                         │
└──────────────────┴────────┴──────────────┴─────────┴───────────┴───────────────────────────┘


6 input(s) too new: nix-ai-tools, nix4vscode, nixos, nixpkgs-unstable, nur, nixpkgs


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
- **Multiple Git backends**: subprocess, GitHub API (uses `gh` CLI token when available), or auto‑selection (default: GitHub API).
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
