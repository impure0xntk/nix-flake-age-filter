"""Age validation logic."""

from __future__ import annotations

import time
from dataclasses import dataclass


@dataclass(frozen=True)
class AgeResult:
    """Result of age validation."""

    age_days: int
    commit_timestamp: int
    is_old_enough: bool
    threshold_days: int


def check_age(
    commit_ts: int,
    threshold_days: int,
    *,
    reference_ts: int | None = None,
) -> AgeResult:
    """Calculate commit age and compare against threshold.

    Args:
        commit_ts: Commit UNIX timestamp
        threshold_days: Minimum required age in days
        reference_ts: Reference time (default: current time)
    """
    now = reference_ts or int(time.time())
    age_seconds = now - commit_ts
    age_days = age_seconds // 86400  # 86400 = 60 * 60 * 24
    return AgeResult(
        age_days=age_days,
        commit_timestamp=commit_ts,
        is_old_enough=age_days >= threshold_days,
        threshold_days=threshold_days,
    )
