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
from whenever import Instant


class TestAgeCheck(unittest.TestCase):
    def test_check_age_passes(self):
        now = Instant.from_timestamp(1_600_000_000)
        commit = Instant.from_timestamp(1_599_000_000)  # ~11.6 days older
        self.assertTrue(check_age(commit, now, min_days=10)["ok"])

    def test_check_age_fails(self):
        now = Instant.from_timestamp(1_600_000_000)
        commit = Instant.from_timestamp(1_599_950_000)  # ~0.58 days older
        self.assertFalse(check_age(commit, now, min_days=1)["ok"])

    def test_check_age_with_int_timestamps(self):
        """Test that int timestamps work correctly."""
        now_int = 1_600_000_000
        commit_int = 1_599_000_000  # ~11.6 days older
        result = check_age(commit_int, now_int, min_days=10)
        self.assertTrue(result["ok"])
        self.assertEqual(result["age_days"], 11)

    def test_format_duration_seconds(self):
        self.assertEqual(format_duration(30), "30s")
        self.assertEqual(format_duration(59), "59s")

    def test_format_duration_minutes(self):
        self.assertEqual(format_duration(60), "1m")
        self.assertEqual(format_duration(90), "1m 30s")
        self.assertEqual(format_duration(150), "2m 30s")

    def test_format_duration_hours(self):
        self.assertEqual(format_duration(3600), "1h")
        self.assertEqual(format_duration(3661), "1h 1m 1s")
        self.assertEqual(format_duration(7325), "2h 2m 5s")

    def test_format_duration_days(self):
        self.assertEqual(format_duration(86_400), "1d")
        self.assertEqual(format_duration(172_800), "2d")
        self.assertEqual(format_duration(604_800), "1w")
        self.assertEqual(format_duration(691_200), "1w 1d")


if __name__ == "__main__":
    unittest.main()
