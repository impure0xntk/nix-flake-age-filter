"""Top‑level Typer application exposing ``verify`` and ``update`` sub‑commands.

The individual command implementations live in ``cli.verify`` and
``cli.update``.  Importing them here registers the commands on the shared Typer
instance, which can be used as the console entry point.
"""

from __future__ import annotations

import typer

# Import command functions directly.
from .verify import verify
from .update import update

app = typer.Typer(help="nix‑flake‑age‑filter CLI – verify and update flake inputs.")

# Register commands directly on the main app.
app.command(name="verify")(verify)
app.command(name="update")(update)

if __name__ == "__main__":
    app()
