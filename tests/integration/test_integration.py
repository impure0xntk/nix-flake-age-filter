"""Integration tests for the full CLI workflow.

These tests spin up a temporary flake.lock file, mock out all external Git/network calls
and then execute the `verify` and `update` Typer commands using ``CliRunner``.
The goal is to ensure the end‑to‑end flow works without raising unexpected exceptions.
"""

import sys
import json
import unittest
import shutil
import tempfile
from pathlib import Path
from unittest.mock import patch
from typer.testing import CliRunner

# Add the project src directory to PYTHONPATH
PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from flake_age_filter.cli.verify import app as verify_app
from flake_age_filter.cli.update import app as update_app


class TestEndToEndWorkflow(unittest.TestCase):
    def setUp(self):
        self.runner = CliRunner()
        # Create a temporary directory for the isolated filesystem
        self.tmp_dir = Path(tempfile.mkdtemp())

        # Minimal flake.lock containing two inputs
        self.lock_path = self.tmp_dir / "flake.lock"
        lock_content = {
            "nodes": {
                "inputs/example": {
                    "locked": {
                        "type": "github",
                        "owner": "user",
                        "repo": "repo",
                        "rev": "deadbeef",
                        "url": "https://github.com/user/repo"
                    }
                },
                "inputs/another": {
                    "locked": {
                        "type": "github",
                        "owner": "other",
                        "repo": "lib",
                        "rev": "c0ffee",
                        "url": "git@github.com:other/lib"
                    }
                }
            }
        }
        self.lock_path.write_text(json.dumps(lock_content))

    def tearDown(self):
        # Clean up temporary directory
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    @patch("flake_age_filter.core.git_ops.get_commit_timestamp")
    @patch("flake_age_filter.core.age_check.check_age")
    def test_verify_and_update_flow(self, mock_check_age, mock_get_ts):
        # Simulate both inputs being old enough (check_age returns dict with ok=True)
        mock_check_age.side_effect = lambda *args, **kwargs: {
            "ok": True,
            "age_days": 30,
            "commit_date": "2024-01-01 00:00 UTC",
            "error": None,
        }
        mock_get_ts.return_value = 1_599_000_000  # arbitrary old timestamp

        # ---- Verify ----
        result_verify = self.runner.invoke(
            verify_app,
            ["--min-age", "10", "--json", str(self.lock_path)]
        )
        self.assertEqual(result_verify.exit_code, 0)
        output = json.loads(result_verify.output)
        self.assertIsInstance(output, list)
        self.assertEqual(len(output), 2)
        for entry in output:
            self.assertTrue(entry.get("ok"))

        # ---- Update (dry‑run) ----
        result_update = self.runner.invoke(
            update_app,
            ["--min-age", "10", "--dry-run", str(self.lock_path)]
        )
        self.assertEqual(result_update.exit_code, 0)
        self.assertIn("dry‑run", result_update.output.lower())
        self.assertIn("example=", result_update.output)
        self.assertIn("another=", result_update.output)


if __name__ == "__main__":
    unittest.main()
