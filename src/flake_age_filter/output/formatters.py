"""Result formatting utilities for the flake‑age CLI.

The CLI commands (`verify` and `update`) produce a list of dictionaries with the
following keys (a superset of the original script's output):

* ``input`` – name of the flake input
* ``ok`` – boolean indicating whether the age requirement was satisfied
* ``rev`` – the commit SHA (or the chosen rev for ``update``)
* ``timestamp`` – Unix epoch of the commit
* ``age_days`` – integer age in days (when ``ok`` is ``True``)
* ``error`` – optional error message when ``ok`` is ``False``
* ``duration`` – human‑readable string produced by ``core.age_check.format_duration``

These helpers provide two output modes:

* **Rich table** – when the ``rich`` library is available.  The table includes
  colour‑coded status, age, and error columns.
* **Plain text** – fallback when ``rich`` cannot be imported; a simple aligned
  column layout is used.
"""

from __future__ import annotations

from typing import Iterable, List, Mapping

# The core ``format_duration`` function is re‑exported for convenience.
from ..core.age_check import format_duration


def _try_import_rich():
    try:
        from rich.table import Table
        from rich.console import Console
        return Table, Console
    except Exception:  # pragma: no cover – import failure path
        return None, None


def _plain_row(columns: List[str], widths: List[int]) -> str:
    """Return a single formatted row for plain‑text output.

    ``columns`` and ``widths`` must have the same length.  Columns are left‑
    justified to their respective width.
    """
    padded = [c.ljust(w) for c, w in zip(columns, widths)]
    return "  ".join(padded)


def format_results(
    results: Iterable[Mapping[str, object]], *, verbose: bool = False
) -> str:
    """Format *results* into a human‑readable string.

    If the ``rich`` library is available a colorful table is returned, otherwise
    a plain‑text table is produced.  The function never prints directly – the
    caller decides where to send the output (stdout, file, etc.).
    """
    Table, Console = _try_import_rich()
    results = list(results)  # materialise for width calculations / iteration

    # Determine column set – always include ``Input`` and ``Status``.
    base_cols = ["Input", "Status"]
    extra_cols = []
    if any(r.get("rev") for r in results):
        extra_cols.append("Rev")
    if any(r.get("age_days") is not None for r in results):
        extra_cols.append("Age (d)")
    if any(r.get("duration") for r in results):
        extra_cols.append("Duration")
    if verbose:
        extra_cols.append("Error")

    headers = base_cols + extra_cols

    if Table:  # Rich available
        table = Table(show_header=True, header_style="bold cyan")
        for h in headers:
            table.add_column(h)
        for r in results:
            status = "✅" if r.get("ok") else "❌"
            row = [r.get("input", ""), status]
            if "Rev" in extra_cols:
                row.append(str(r.get("rev", "-")))
            if "Age (d)" in extra_cols:
                row.append(str(r.get("age_days", "-")))
            if "Duration" in extra_cols:
                row.append(str(r.get("duration", "-")))
            if verbose:
                row.append(str(r.get("error", "")))
            table.add_row(*row)
        from rich.console import Console
        from io import StringIO
        sio = StringIO()
        console = Console(file=sio, force_terminal=False)
        console.print(table)
        return sio.getvalue()

    # Plain‑text fallback – compute column widths
    col_widths = [max(len(h), max(len(str(r.get(k.lower(), "-"))) for r in results)) for h, k in zip(headers, headers)]
    # Ensure a minimum width for readability
    col_widths = [max(w, 8) for w in col_widths]
    lines = [_plain_row(headers, col_widths)]
    lines.append("-" * (sum(col_widths) + 2 * (len(col_widths) - 1)))
    for r in results:
        status = "OK" if r.get("ok") else "FAIL"
        row_vals = [str(r.get("input", "")), status]
        if "Rev" in extra_cols:
            row_vals.append(str(r.get("rev", "-")))
        if "Age (d)" in extra_cols:
            row_vals.append(str(r.get("age_days", "-")))
        if "Duration" in extra_cols:
            row_vals.append(str(r.get("duration", "-")))
        if verbose:
            row_vals.append(str(r.get("error", "")))
        lines.append(_plain_row(row_vals, col_widths))
    return "\n".join(lines)
