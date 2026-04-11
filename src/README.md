# src Directory Overview

This directory contains the core implementation of **nix‑flake‑age‑filter**.

| File / Package | Purpose |
|----------------|---------|
| `age_check.py` | High‑level CLI entry points (`verify`, `update`). |
| `flake_age_common.py` | Shared data classes, Git helpers, age calculation logic. |
| `flake_age_types.py` | Typed data structures used across the project. |
| `flake_lock.py` | Helpers for parsing `flake.lock` files. |
| `git_operations.py` | Thin wrapper around the `git` CLI for fetching commit timestamps. |
| `nix_flake_age_filter.py` | Implementation of the `verify` sub‑command (validation only). |
| `nix_flake_age_update.py` | Implementation of the `update` sub‑command (override inputs). |
| `nix_flake_age_update_standalone.py` | Stand‑alone script used by CI / tests. |
| `nix_flake_age_verify.py` | Wrapper that invokes the verification logic. |
| `flake_age_filter/` | Future plugin architecture (currently empty). |
| `flake_age_filter/core/` | Core library code for the plugin system (errors, input handling, lock parsing). |
| `flake_age_filter/output/` | Output formatting utilities (e.g., table, JSON). |

The top‑level modules are deliberately thin wrappers that delegate the heavy lifting to the utilities in `src/`.  This keeps the CLI commands easy to test and maintain.
