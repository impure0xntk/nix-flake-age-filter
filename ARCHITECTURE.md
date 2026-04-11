# Architecture Overview

## Directory Structure
```
src/
├── flake_age_common.py       # Core logic, data classes, git operations, age calculations
├── nix_flake_age_filter.py   # `verify` subcommand (validation only)
├── nix_flake_age_update.py   # `update` subcommand (walk history, override inputs)
└── flake_age_filter/         # Plugin architecture (future work)
```

## Data Flow
```mermaid
flowchart TD
    A[Parse `flake.lock`] --> B[Fetch commit timestamps via git]
    B --> C[Convert timestamps to UTC (datetime/Instant)]
    C --> D[Compare age against `--min-age`]
    D --> E{Pass?}
    E -->|Yes| F[Emit pass status]
    E -->|No| G[Emit fail/wait status]
    F --> H[JSON / console output]
    G --> H
```

## External Dependencies
| Dependency | Purpose |
|------------|---------|
| `git` CLI  | Retrieve commit history and timestamps. |
| `nix` CLI  | Optional: perform `flake update` with `--override-input`. |
| `rich`     | Pretty console output. |
| `whenever` (planned) | Unified date‑time handling. |

## Migration Notes
- All timestamps are stored as **UTC seconds since the epoch**.
- When moving to `whenever`, replace `datetime.fromtimestamp` with `Instant.from_timestamp`, etc. (see migration table in project docs).

## Future Extensions
- Plugin system (`flake_age_filter/`) for custom age policies.
- Integration tests with mocked git interactions.
