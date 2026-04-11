"""Top‑level Typer application exposing ``verify`` and ``update`` sub‑commands.

The individual command implementations live in ``cli.verify`` and
``cli.update``.  Importing them here registers the commands on the shared Typer
instance, which can be used as the console entry point.
"""

from __future__ import annotations

import typer

# Import sub‑commands to register them on the Typer app.
from .verify import app as verify_app
from .update import app as update_app

app = typer.Typer(help="nix‑flake‑age‑filter CLI – verify and update flake inputs.")

app.add_typer(verify_app, name="verify")
app.add_typer(update_app, name="update")

if __name__ == "__main__":
    app()
