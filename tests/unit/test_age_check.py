"""Tests for core.age_check utilities.

These tests rely only on the `whenever` library, which is already a dependency.
"""

import sys
import unittest
from pathlib import Path

# Ensure the src directory is on PYTHONPATH
PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from flake_age_filter.core.age_check import check_age, format_duration
from whenever import Instant, Duration


class TestAgeCheck(unittest.TestCase):
    def test_check_age_passes(self):
        now = Instant.from_timestamp(1_600_000_000)
        commit = Instant.from_timestamp(1_599_000_000)  # ~11.6 days older
        self.assertTrue(check_age(commit, now, min_days=10))

    def test_check_age_fails(self):
        now = Instant.from_timestamp(1_600_000_000)
        commit = Instant.from_timestamp(1_599_950_000)  # ~0.58 days older
        self.assertFalse(check_age(commit, now, min_days=1))

    def test_format_duration(self):
        self.assertEqual(format_duration(Duration.from_seconds(90)), "1m30s")
        self.assertEqual(format_duration(Duration.from_seconds(3661)), "1h1m1s")


if __name__ == "__main__":
    unittest.main()
