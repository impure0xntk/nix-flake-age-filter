# src Directory Overview

This directory contains the core implementation of **nix‑flake‑age‑filter**.

| File / Package | Purpose |
|----------------|---------|
| `flake_age_filter/` | Future plugin architecture (currently empty). |
| `flake_age_filter/core/` | Core library code for the plugin system (errors, input handling, lock parsing). |
| `flake_age_filter/output/` | Output formatting utilities (e.g., table, JSON). |

The top‑level modules are deliberately thin wrappers that delegate the heavy lifting to the utilities in `src/`.  This keeps the CLI commands easy to test and maintain.
