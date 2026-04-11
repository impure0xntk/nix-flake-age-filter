"""Legacy wrapper – forwards to the new Typer CLI.

The original project exposed a ``nix_flake_age_filter`` script.  After the
refactor the functional implementation lives under ``flake_age_filter.cli``.
This thin wrapper preserves the historic entry‑point while delegating all work
to the new Typer application.
"""

from flake_age_filter.cli.main import app

if __name__ == "__main__":
    import sys
    # Preserve the original script name for help/usage output.
    sys.argv[0] = "nix_flake_age_filter"
    app()
