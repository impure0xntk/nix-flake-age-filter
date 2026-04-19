"""Tests for core.lock_file.read_flake_inputs."""

import json
import sys
import tempfile
import unittest
from pathlib import Path

# Ensure src on PYTHONPATH (tests/__init__ already does it, but keep safety)
PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from flake_age_filter.core.lock_file import read_flake_inputs


class TestLockFileParsing(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.lock_path = Path(self.tmp_dir.name) / "flake.lock"
        # Minimal lock JSON with two inputs
        data = {
            "nodes": {
                "inputs/example": {
                    "locked": {
                        "type": "github",
                        "owner": "user",
                        "repo": "repo",
                        "rev": "deadbeef",
                        "url": "https://github.com/user/repo",
                    }
                },
                "inputs/another": {
                    "locked": {
                        "type": "github",
                        "owner": "other",
                        "repo": "lib",
                        "rev": "c0ffee",
                        "url": "git@github.com:other/lib",
                    }
                },
            }
        }
        self.lock_path.write_text(json.dumps(data))

    def tearDown(self):
        self.tmp_dir.cleanup()

    def test_read_flake_inputs(self):
        inputs = read_flake_inputs(self.lock_path)
        self.assertEqual(len(inputs), 2)
        names = {i.name for i in inputs}
        self.assertIn("example", names)
        self.assertIn("another", names)
        example = next(i for i in inputs if i.name == "example")
        self.assertEqual(example.rev, "deadbeef")
        self.assertTrue(example.has_rev)


if __name__ == "__main__":
    unittest.main()
