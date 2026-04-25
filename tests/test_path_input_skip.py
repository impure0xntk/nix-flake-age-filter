"""Tests for skipping path-type and file:-URL git inputs."""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from flake_age_filter.core.models import FlakeInput


class TestPathInputSkip:
    """Verify that path-type inputs and file: URL inputs are skipped."""

    def test_to_git_url_path_type_is_none(self):
        """Path type inputs should return None from to_git_url()."""
        inp = FlakeInput(
            name="local-path",
            locked={"type": "path", "path": "./submodules/foo"},
            original={"type": "path", "path": "./submodules/foo"},
        )
        assert inp.to_git_url() is None

    def test_to_git_url_git_type_with_file_url_is_none(self):
        """Git type inputs with file: URL should return None from to_git_url()."""
        inp = FlakeInput(
            name="local-git",
            locked={"type": "git", "url": "file:./submodules/foo"},
            original={"type": "git", "url": "file:./submodules/foo"},
        )
        assert inp.to_git_url() is None

    def test_to_git_url_git_type_with_file_url_in_original_is_none(self):
        """Git type inputs with file: URL in original dict should also return None."""
        inp = FlakeInput(
            name="local-git2",
            locked={"type": "git", "rev": "abc123"},
            original={"type": "git", "url": "file:./submodules/bar"},
        )
        assert inp.to_git_url() is None

    def test_is_path_property_true_for_path_type(self):
        """is_path property returns True for path-type inputs."""
        inp = FlakeInput(
            name="local",
            locked={"type": "path"},
            original={"type": "path"},
        )
        assert inp.is_path is True

    def test_is_path_property_false_for_git_type(self):
        """is_path property returns False for git-type inputs."""
        inp = FlakeInput(
            name="remote",
            locked={"type": "git", "url": "https://example.com/repo.git"},
            original={"type": "git", "url": "https://example.com/repo.git"},
        )
        assert inp.is_path is False

    def test_is_path_property_false_for_github_type(self):
        """is_path property returns False for github-type inputs."""
        inp = FlakeInput(
            name="gh",
            locked={"type": "github", "owner": "o", "repo": "r"},
            original={"type": "github", "owner": "o", "repo": "r"},
        )
        assert inp.is_path is False
