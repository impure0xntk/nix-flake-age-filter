# nix-flake-age-filter

A utility library for Nix Flake that provides functionality similar to npm v11.10.0's `min-release-age`.

## Overview

`min-release-age` is a supply chain attack mitigation feature that prevents installation of packages that have been published less than a specified number of days ago. This library implements a similar age check for Nix Flake, using the `lastModified` timestamp of flake inputs.

## Usage

### Using from another flake

```nix
{
  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
    age-filter.url = "github:impure0xntk/nix-flake-age-filter";
  };

  outputs = { self, nixpkgs, age-filter }:
    let
      inherit (age-filter.lib) checkAllInputs mkAgeCheck;
    in
    {
      # Get age check results
      yourCheck = age-filter.lib.checkAllInputs {
        inputs = self.inputs;
        minAgeDays = 3;        # Minimum 3 days old
        referenceTime = self.lastModified or 0;
        excludeInputs = [ "self" ];
      };

      # Register as a flake check
      checks.x86_64-linux.input-age = age-filter.lib.mkAgeCheck {
        inputs = self.inputs;
        minAgeDays = 3;
        referenceTime = self.lastModified or 0;
        system = "x86_64-linux";
        excludeInputs = [ "self" "nixpkgs" ];
      };
    };
}
```

### Defining your own check

```nix
{
  inputs = {
    age-filter.url = "github:impure0xntk/nix-flake-age-filter";
  };

  outputs = { self, age-filter }:
    {
      checks.x86_64-linux.my-inputs = age-filter.lib.mkAgeCheck {
        inputs = self.inputs;
        minAgeDays = 7;  # Reject inputs younger than 7 days
        referenceTime = self.lastModified or 0;
        system = "x86_64-linux";
        excludeInputs = [ "self" ];
      };
    };
}
```

## Comparison: npm vs nix-flake-age-filter

| Feature | npm (`min-release-age`) | nix-flake-age-filter |
|------|------------------------|---------------------|
| Input value | Package publish date | flake input `lastModified` |
| Current time | System clock (impure) | `self.lastModified` / `referenceTime` (pure) |
| When it runs | `npm install` | `nix flake check` |
| Configuration | `.npmrc` | flake outputs `checks` |
| Default | None | None |

## Technical Background

### How npm `min-release-age` works

The `min-release-age` feature introduced in npm v11.10.0 excludes package versions that have been published fewer than a specified number of days ago when building the package tree.

```ini
# .npmrc
min-release-age=3
```

### Challenges implementing this in Nix

Nix flakes must be **pure**, meaning they cannot depend on mutable values like `builtins.currentTime`. Therefore, this library uses **`self.lastModified`** as the reference time.

`self.lastModified` is the timestamp when the flake was last updated (e.g., the last git commit time). For the same revision, it always returns the same value, making it compatible with pure evaluation.

## API Reference

### `lib.checkInputAge`

Checks the age of a single input.

```nix
age-filter.lib.checkInputAge {
  input = inputs.foo;
  minAgeDays = 3;
  referenceTime = self.lastModified or 0;
}
# => { ok = true, ageDays = 15, error = null; }
```

### `lib.checkAllInputs`

Checks all inputs at once.

```nix
age-filter.lib.checkAllInputs {
  inputs = self.inputs;
  minAgeDays = 3;
  referenceTime = self.lastModified or 0;
  excludeInputs = [ "self" "nixpkgs" ];
}
# => { ok = true, results = { ... }, failed = [], error = null; }
```

### `lib.mkAgeCheck`

Creates a derivation usable as a flake check.

```nix
age-filter.lib.mkAgeCheck {
  inputs = self.inputs;
  minAgeDays = 3;
  referenceTime = self.lastModified or 0;
  system = "x86_64-linux";
  excludeInputs = [ "self" "nixpkgs" ];
}
```

### `lib.mkChecks`

Generates checks for all systems in `flakeExposed`.

```nix
age-filter.lib.mkChecks {
  inputs = self.inputs;
  minAgeDays = 3;
  referenceTime = self.lastModified or 0;
  excludeInputs = [ "self" "nixpkgs" ];
}
```

### `lib.daysToSeconds`

Converts days to seconds.

```nix
age-filter.lib.daysToSeconds 3
# => 259200
```

## CLI Tool

The `nix-flake-age` command lets you check and update flake input ages from the CLI.

### Installation

```bash
# Run with nix run
nix run github:impure0xntk/nix-flake-age-filter -- verify --min-age 3 /path/to/flake.lock

# Install locally
nix profile install github:impure0xntk/nix-flake-age-filter
nix-flake-age verify --min-age 3 flake.lock
```

### `verify` subcommand

Checks input ages in the lock file. A library-equivalent of `nix flake check`.

```bash
# Basic: allow only inputs older than 3 days
nix-flake-age verify --min-age 3 flake.lock

# Custom "now" time (YYYY-MM-DD)
nix-flake-age verify --min-age 7 --current-date 2026-04-04 flake.lock

# JSON output
nix-flake-age verify --min-age 3 --json flake.lock

# Exit codes
# 0 = all passed / 1 = one or more failed
```

### `update` subcommand

Use instead of `nix flake update` to only adopt commits published at least a specified number of days ago. Equivalent to `npm install --min-release-age=3`.

```bash
# Basic: update flake.lock, but skip commits younger than 3 days
nix-flake-age update --min-age 3

# Update only specific inputs
nix-flake-age update --min-age 3 nixpkgs home-manager

# Dry run (no changes applied)
nix-flake-age update --min-age 3 --dry-run

# JSON output
nix-flake-age update --min-age 3 --json
```

**Update behavior:**

- Walks back the commit history of each input's branch to find the newest commit that meets the minimum age
- If no commit meets the criteria, the input is skipped (`WAIT` status)
- Calculates the narHash of the selected commit and updates `flake.lock`

## Limitations

- Using `self.lastModified` as `referenceTime` means check strictness may vary depending on how frequently the flake is updated
- Non-git input sources (URL, path, etc.) may not have `lastModified` available; those inputs are skipped
- The CLI `update` subcommand requires both `nix` and `git`

## License

Apache License 2.0
