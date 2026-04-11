"""Age validation utilities."""

from whenever import Instant

from flake_age_types import AgeCheckResult


def check_age(timestamp: int, min_age_days: int, now: Instant) -> AgeCheckResult:
    """Check if commit age meets minimum requirement."""
    commit_time = Instant.from_timestamp(timestamp)
    age_days = int((now.timestamp() - commit_time.timestamp()) / 86400)
    return AgeCheckResult(
        ok=age_days >= min_age_days,
        age_days=age_days,
        commit_date=commit_time.to_stdlib().strftime("%Y-%m-%d %H:%M UTC"),
        error=None if age_days >= min_age_days else f"only {age_days}d old (minimum: {min_age_days}d)",
    )


def format_duration(days: int) -> str:
    """Format days into a human-readable duration."""
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
