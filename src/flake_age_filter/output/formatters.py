"""Result formatting utilities for the flake‑age CLI.

The CLI commands (``verify`` and ``update``) produce lists of dictionaries.
These helpers render them as human‑readable tables in two modes:

* **Rich table** – when the ``rich`` library is available.
* **Plain text** – aligned‑column fallback.

Both commands share the same rendering engine via :func:`format_table`, with
command‑specific convenience wrappers:

* :func:`format_verify_results` – for ``verify`` output
* :func:`format_update_results` – for ``update`` output
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, List, Mapping, Sequence


# ---------------------------------------------------------------------------
# Shared internals
# ---------------------------------------------------------------------------


def _try_import_rich():
    """Return ``(Table, Console)`` if *rich* is available, else ``(None, None)``."""
    try:
        from rich.table import Table
        from rich.console import Console

        return Table, Console
    except Exception:  # pragma: no cover – import failure path
        return None, None


def _plain_row(columns: Sequence[str], widths: Sequence[int]) -> str:
    """Return a single formatted row for plain‑text output.

    Columns are left‑justified to their respective width.
    """
    padded = [c.ljust(w) for c, w in zip(columns, widths)]
    return "  ".join(padded)


@dataclass
class _Column:
    """Lightweight descriptor for a single table column."""

    header: str
    key: str  # key used to look up the value in a result dict
    fmt: str = "str"  # format hint: "str" | "signed" | "short_rev"
    condition: str | None = None  # only include when this key is truthy


# Common column definitions ------------------------------------------------

_VERIFY_COLUMNS: List[_Column] = [
    _Column("Input", "input"),
    _Column("Status", "_status"),
    _Column("Rev", "rev", fmt="short_rev", condition="rev"),
    _Column("Age (d)", "age_days", condition="age_days"),
    _Column("Deviation", "deviation", fmt="signed", condition="deviation"),
    _Column("Error", "error", condition="_has_error"),
]

_UPDATE_COLUMNS: List[_Column] = [
    _Column("Input", "input"),
    _Column("Status", "_status"),
    _Column("Current Rev", "current_rev", fmt="short_rev", condition="current_rev"),
    _Column("New Rev", "rev", fmt="short_rev", condition="rev"),
    _Column("Age (d)", "age_days", condition="age_days"),
    _Column("Error", "error", condition="_has_error"),
]


def _format_cell(value: object, fmt: str) -> str:
    """Format a single cell value according to the format hint."""
    if fmt == "signed" and isinstance(value, (int, float)):
        return f"{value:+d}"
    if fmt == "short_rev" and isinstance(value, str) and len(value) > 12:
        return value[:12]
    return "-" if value is None else str(value)


def _should_show(
    col: _Column, results: List[Mapping[str, object]], *, verbose: bool = False
) -> bool:
    """Decide whether *col* should appear for the given *results*.

    A column is shown when at least one row has a non‑empty value for the
    condition key, **or** when *verbose* is ``True`` and the column is
    optional (i.e. has a ``condition``).
    """
    cond = col.condition
    if cond is None:
        # Base columns are always shown.
        return True
    if cond == "_has_error":
        return verbose or any(not r.get("ok") for r in results)
    return verbose or any(r.get(cond) is not None for r in results)


def _cell_value(result: Mapping[str, object], col: _Column) -> str:
    """Extract and format the cell value from a single result row."""
    if col.key == "_status":
        return "OK" if result.get("ok") else "FAIL"
    return _format_cell(result.get(col.key), col.fmt)


def _cell_value_rich(result: Mapping[str, object], col: _Column) -> str:
    """Like :func:`_cell_value` but uses Rich‑style symbols."""
    if col.key == "_status":
        return "✅" if result.get("ok") else "❌"
    return _format_cell(result.get(col.key), col.fmt)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def format_table(
    results: Iterable[Mapping[str, object]],
    columns: Sequence[_Column],
    *,
    verbose: bool = False,
) -> str:
    """Render *results* as a human‑readable table string.

    Uses Rich when available, otherwise falls back to plain text.
    This is the low‑level rendering function used by the command‑specific
    wrappers below.
    """
    Table, Console = _try_import_rich()
    results = list(results)

    if not results:
        return "(no results)"

    visible = [c for c in columns if _should_show(c, results, verbose=verbose)]

    if Table is not None:
        table = Table(show_header=True, header_style="bold cyan")
        for col in visible:
            table.add_column(col.header)
        for r in results:
            row = [_cell_value_rich(r, col) for col in visible]
            table.add_row(*row)
        from io import StringIO

        sio = StringIO()
        console = Console(file=sio, force_terminal=False)
        console.print(table)
        return sio.getvalue()

    # Plain‑text fallback
    sample_rows: List[List[str]] = []
    for r in results:
        sample_rows.append([_cell_value(r, col) for col in visible])
    header_texts = [col.header for col in visible]
    # Compute column widths from header + data
    col_widths: List[int] = []
    for idx, hdr in enumerate(header_texts):
        data_max = max((len(row[idx]) for row in sample_rows), default=0)
        col_widths.append(max(len(hdr), data_max, 8))
    lines: List[str] = []
    lines.append(_plain_row(header_texts, col_widths))
    lines.append("-" * (sum(col_widths) + 2 * (len(col_widths) - 1)))
    for row in sample_rows:
        lines.append(_plain_row(row, col_widths))
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Legacy function (backward compatibility)
# ---------------------------------------------------------------------------


def format_results(
    results: Iterable[Mapping[str, object]], verbose: bool = False
) -> str:
    """Format verification results (legacy API).

    This function is kept for backward compatibility with existing code.
    Prefer :func:`format_verify_results` for new code.
    """
    return format_table(results, _VERIFY_COLUMNS, verbose=verbose)


# ---------------------------------------------------------------------------
# Command‑specific wrappers
# ---------------------------------------------------------------------------


def format_verify_results(
    results: Iterable[Mapping[str, object]], *, verbose: bool = False
) -> str:
    """Format verification results (verify command).

    Columns: Input | Status | Rev | Age (d) | Deviation | Error
    """
    return format_table(results, _VERIFY_COLUMNS, verbose=verbose)


def format_update_results(
    results: Iterable[Mapping[str, object]], *, verbose: bool = False
) -> str:
    """Format update results (update command).

    Columns: Input | Status | Current Rev | New Rev | Age (d) | Error
    """
    return format_table(results, _UPDATE_COLUMNS, verbose=verbose)
