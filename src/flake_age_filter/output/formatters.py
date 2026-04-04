"""Output formatters for verify and update.

Provides table display using rich and JSON output.
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass, asdict
from typing import Literal

from rich.console import Console
from rich.table import Table
from rich.progress import Progress, SpinnerColumn, TextColumn


# ── Data Models ──────────────────────────────────────────────

@dataclass
class VerifyResult:
    name: str
    status: Literal["PASS", "FAIL", "ERROR", "SKIP"]
    age_days: int | None
    commit_date: str | None
    rev: str | None
    error: str | None


@dataclass
class UpdateResult:
    name: str
    status: Literal["UPDATED", "SKIPPED", "ERROR"]
    from_rev: str | None
    to_rev: str | None
    age_days: int | None
    error: str | None


# ── Helpers ──────────────────────────────────────────────────

_STATUS_COLOR: dict[str, str] = {
    "PASS": "green",
    "FAIL": "red",
    "ERROR": "bold red",
    "SKIP": "yellow",
    "UPDATED": "green",
    "SKIPPED": "yellow",
}

console = Console(stderr=True)


def format_duration(days: int) -> str:
    if days < 0:
        return f"{days}d (future)"
    if days < 7:
        return f"{days}d"
    w = days // 7
    r = days % 7
    if w < 52:
        return f"{w}w {r}d" if r else f"{w}w"
    y = w // 52
    wr = w % 52
    return f"{y}y {wr}w"


# ── Verify Output ───────────────────────────────────────────

def print_verify_table(results: list[VerifyResult], min_age: int) -> None:
    table = Table(title=f"Age Verification (min: {min_age}d)")
    table.add_column("Input", style="cyan")
    table.add_column("Status")
    table.add_column("Age", justify="right")
    table.add_column("Commit Date")
    table.add_column("Rev", style="dim")
    table.add_column("Error", style="red")

    for r in results:
        color = _STATUS_COLOR.get(r.status, "")
        table.add_row(
            r.name,
            f"[{color}]{r.status}[/{color}]",
            format_duration(r.age_days) if r.age_days is not None else "-",
            r.commit_date or "-",
            (r.rev or "")[:8] if r.rev else "-",
            r.error or "",
        )

    console.print(table)

    summary = _verify_summary(results)
    console.print(
        f"[bold]Summary:[/bold] {summary['pass']} pass, "
        f"[bold red]{summary['fail']}[/bold red] fail, "
        f"[red]{summary['error']}[/red] error"
    )


def _verify_summary(results: list[VerifyResult]) -> dict[str, int]:
    summary: dict[str, int] = {"pass": 0, "fail": 0, "error": 0, "skip": 0}
    for r in results:
        key = r.status.lower()
        if key in summary:
            summary[key] += 1
    return summary


# ── Update Output ────────────────────────────────────────────

def print_update_summary(results: list[UpdateResult], dry_run: bool) -> None:
    label = "Update Preview (dry-run)" if dry_run else "Update Results"
    table = Table(title=label)
    table.add_column("Input", style="cyan")
    table.add_column("Status")
    table.add_column("From Rev", style="dim")
    table.add_column("To Rev", style="dim")
    table.add_column("Age")
    table.add_column("Error", style="red")

    for r in results:
        color = _STATUS_COLOR.get(r.status, "")
        table.add_row(
            r.name,
            f"[{color}]{r.status}[/{color}]",
            (r.from_rev or "")[:8] if r.from_rev else "-",
            (r.to_rev or "")[:8] if r.to_rev else "-",
            format_duration(r.age_days) if r.age_days is not None else "-",
            r.error or "",
        )

    console.print(table)


# ── JSON Output ─────────────────────────────────────────────

def print_json_verify(
    results: list[VerifyResult], min_age: int, flake_path: str
) -> None:
    summary = _verify_summary(results)
    output = {
        "flake": flake_path,
        "min_age": min_age,
        "inputs": [asdict(r) for r in results],
        "summary": {
            "total": len(results),
            **summary,
        },
        "exit_code": 0 if summary["fail"] == 0 and summary["error"] == 0 else 1,
    }
    _print_json(output)


def print_json_update(
    results: list[UpdateResult], flake_path: str, dry_run: bool
) -> None:
    updates = [asdict(r) for r in results]
    output = {
        "flake": flake_path,
        "dry_run": dry_run,
        "updates": updates,
    }
    _print_json(output)


def _print_json(data: dict) -> None:
    out = Console(file=sys.stdout)
    out.print(json.dumps(data, indent=2, ensure_ascii=False))


# ── Progress Display ─────────────────────────────────────────

def make_progress(description: str, total: int) -> Progress:
    return Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
    )
