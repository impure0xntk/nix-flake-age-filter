"""Age checking utilities using the ``whenever`` library.

The original implementation used ``datetime`` from the standard library.
Here we rely on ``whenever.Instant`` which provides UTC‑native timestamps
and convenient arithmetic.
"""

from __future__ import annotations

from whenever import Instant


def check_age(timestamp: int, min_age_days: int, now: Instant) -> dict:
    """Return a dict describing whether ``timestamp`` satisfies ``min_age_days``.

    ``timestamp`` – Unix epoch seconds (UTC).
    ``now`` – an ``Instant`` representing the current moment.
    The result mimics the legacy output format:

    ``{"ok": bool, "age_days": int, "commit_date": str, "error": Optional[str]}``
    """
    commit_time = Instant.from_timestamp(timestamp)
    age_seconds = (now - commit_time).total_seconds()
    age_days = int(age_seconds // 86_400)
    ok = age_days >= min_age_days
    return {
        "ok": ok,
        "age_days": age_days,
        "commit_date": str(commit_time).replace("T", " ").rsplit(".", 1)[0] + " UTC",
        "error": None if ok else f"only {age_days}d old (minimum: {min_age_days}d)",
    }


def format_duration(days: int) -> str:
    """Human‑readable formatting of a day count.

    Mirrors the behaviour of the legacy ``format_duration`` function.
    """
    if days < 0:
        return f"{days}d (future)"
    if days < 7:
        return f"{days}d"
    weeks = days // 7
    remainder = days % 7
    if weeks < 52:
        return f"{weeks}w {remainder}d" if remainder else f"{weeks}w"
    years = weeks // 52
    w_rem = weeks % 52
    return f"{years}y {w_rem}w"
