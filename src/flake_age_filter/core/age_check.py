"""Age checking utilities using the ``whenever`` library.

The original implementation used ``datetime`` from the standard library.
Here we rely on ``whenever.Instant`` which provides UTC‑native timestamps
and convenient arithmetic.
"""

from __future__ import annotations

from typing import Union
from whenever import Instant


def _to_instant(val: Union[int, Instant]) -> Instant:
    """Convert int (Unix epoch seconds) or Instant to Instant."""
    return val if isinstance(val, Instant) else Instant.from_timestamp(val)


def check_age(
    commit: Union[int, Instant], now: Union[int, Instant], min_days: int
) -> dict:
    """Return a dict describing whether ``commit`` satisfies ``min_days``.

    Args:
        commit: Unix epoch seconds (UTC) or Instant.
        now: Unix epoch seconds (UTC) or Instant.
        min_days: Minimum age in days required.

    Returns:
        Dict with keys: ok (bool), age_days (int), commit_date (str), error (str|None)
    """
    commit_time = _to_instant(commit)
    now_instant = _to_instant(now)

    age_seconds = now_instant.timestamp() - commit_time.timestamp()
    age_days = int(age_seconds // 86_400)
    ok = age_days >= min_days

    return {
        "ok": ok,
        "age_days": age_days,
        "commit_date": str(commit_time).replace("T", " ").rsplit(".", 1)[0] + " UTC",
        "error": None if ok else f"only {age_days}d old (minimum: {min_days}d)",
    }


def format_duration(seconds: int) -> str:
    """Human‑readable formatting of a duration in seconds.

    Converts seconds to a human-readable format:
    - Less than 1 minute: "Xs"
    - Less than 1 hour: "Xm Ys"
    - Less than 1 day: "Xh Ym Zs"
    - Less than 1 week: "Xd"
    - Otherwise: "Xw Yd"

    Args:
        seconds: Duration in seconds.

    Returns:
        Human-readable string.
    """
    if seconds < 0:
        return f"{seconds}s (future)"
    if seconds < 60:
        return f"{seconds}s"
    if seconds < 3600:
        minutes, secs = divmod(seconds, 60)
        return f"{minutes}m {secs}s" if secs else f"{minutes}m"
    if seconds < 86_400:
        hours, rem = divmod(seconds, 3600)
        minutes, secs = divmod(rem, 60)
        parts = [f"{hours}h"]
        if minutes:
            parts.append(f"{minutes}m")
        if secs:
            parts.append(f"{secs}s")
        return " ".join(parts)
    days = seconds // 86_400
    if days < 7:
        return f"{days}d"
    weeks = days // 7
    remainder = days % 7
    if weeks < 52:
        return f"{weeks}w {remainder}d" if remainder else f"{weeks}w"
    years = weeks // 52
    w_rem = weeks % 52
    return f"{years}y {w_rem}w"
