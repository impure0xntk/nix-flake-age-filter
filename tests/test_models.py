"""Unittest suite for core.models.FlakeInput.

Uses only the Python standard library (no external dependencies).
"""

import sys
import unittest
from pathlib import Path

# Ensure the project's src directory is on PYTHONPATH for import resolution
PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from flake_age_filter.core.models import FlakeInput


class TestFlakeInput(unittest.TestCase):
    def test_to_git_url_http(self):
        inp = FlakeInput(
            name="example",
            locked={
                "type": "github",
                "owner": "user",
                "repo": "repo",
                "rev": "deadbeef",
                "url": "https://github.com/user/repo",
            },
            original={},
        )
        self.assertEqual(inp.to_git_url(), "https://github.com/user/repo.git")

    def test_to_git_url_ssh(self):
        inp = FlakeInput(
            name="example",
            locked={
                "type": "github",
                "owner": "user",
                "repo": "repo",
                "rev": "deadbeef",
                "url": "git@github.com:user/repo",
            },
            original={},
        )
        self.assertEqual(inp.to_git_url(), "git@github.com:user/repo.git")

    def test_to_flake_url(self):
        inp = FlakeInput(
            name="example",
            locked={
                "type": "github",
                "owner": "user",
                "repo": "repo",
                "rev": "deadbeef",
                "url": "https://github.com/user/repo",
            },
            original={},
        )
        self.assertEqual(
            inp.to_flake_url("1234567"),
            "example=github:user/repo/1234567",
        )


if __name__ == "__main__":
    unittest.main()
