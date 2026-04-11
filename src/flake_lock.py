"""flake.lock parsing and FlakeInput data model."""

import json
import sys
from pathlib import Path


class FlakeInput:
    """Represents a flake input (locked or original)."""

    def __init__(self, name: str, locked: dict, original: dict):
        self.name = name
        self.locked = locked
        self.original = original
        self.input_type = locked.get("type", "unknown")
        self.rev = locked.get("rev")
        self.ref = locked.get("ref")

    @property
    def has_rev(self) -> bool:
        return bool(self.rev)

    def to_git_url(self) -> str | None:
        """Build a git HTTPS URL for the input."""
        t = self.input_type
        if t == "github":
            return f"https://github.com/{self.locked.get('owner', '')}/{self.locked.get('repo', '')}.git"
        if t == "gitlab":
            host = self.locked.get("host", "gitlab.com")
            repo = self.locked.get("repo") or self.locked.get("project", "")
            owner = self.locked.get("owner", "")
            if repo and owner:
                return f"https://{host}/{owner}/{repo}.git"
            if repo:
                return f"https://{host}/{repo}.git"
            return None
        if t == "sourcehut":
            owner = self.locked.get("owner", "")
            repo = self.locked.get("repo", self.locked.get("project", ""))
            return f"https://git.sr.ht/~{owner}/{repo}"
        if t == "git":
            return self.locked.get("url") or self.original.get("url")
        if t == "indirect":
            oref = self.original.get("id", "")
            if "/" in oref:
                parts = oref.split("/")
                return f"https://github.com/{parts[0]}/{'/'.join(parts[1:])}.git"
            return None
        if t == "path":
            return None
        return None

    def target_ref(self) -> str | None:
        """Return the ref (branch/tag) that update would pull from."""
        return (
            self.original.get("ref")
            or self.original.get("branch", "")
            or None
        )

    def to_flake_url(self, rev: str | None = None) -> str | None:
        """Build a flake URL like github:owner/repo[/<rev>]."""
        t = self.input_type
        if t == "github":
            owner = self.locked.get("owner", "")
            repo = self.locked.get("repo", "")
            base = f"github:{owner}/{repo}"
            return f"{base}/{rev}" if rev else base
        if t == "gitlab":
            host = self.locked.get("host", "gitlab.com")
            owner = self.locked.get("owner", "")
            repo = self.locked.get("repo") or self.locked.get("project", "")
            base = f"gitlab:{host}/{owner}/{repo}" if owner else f"gitlab:{host}/{repo}"
            return f"{base}/{rev}" if rev else base
        if t == "sourcehut":
            owner = self.locked.get("owner", "")
            repo = self.locked.get("repo", self.locked.get("project", ""))
            base = f"git+https://git.sr.ht/~{owner}/{repo}"
            return f"{base}?rev={rev}" if rev else base
        if t == "git":
            url = self.locked.get("url") or self.original.get("url")
            if not url:
                return None
            if url.startswith("git+"):
                return f"{url}?rev={rev}" if rev else url
            return f"git+{url}?rev={rev}" if rev else f"git+{url}"
        if t == "indirect":
            oref = self.original.get("id", "")
            return f"{oref}/{rev}" if rev else (oref if "/" in oref else None)
        return None


def parse_flake_lock(path: str) -> dict:
    """Parse flake.lock and return the JSON structure."""
    lock_path = Path(path)
    if not lock_path.exists():
        print(f"Error: flake.lock not found at {path}", file=sys.stderr)
        sys.exit(1)
    return json.loads(lock_path.read_text())


def extract_locked_inputs(lock_data: dict) -> list[FlakeInput]:
    """Extract direct root inputs from flake.lock."""
    nodes = lock_data.get("nodes", {})
    root_node = nodes.get("root", {})
    root_inputs_raw = root_node.get("inputs", {})

    inputs: list[FlakeInput] = []
    if isinstance(root_inputs_raw, dict):
        for name, target in root_inputs_raw.items():
            node_name = target if isinstance(target, str) else (target[0] if isinstance(target, list) and target else None)
            if not node_name:
                continue
            node_data = nodes.get(node_name)
            if not node_data or "locked" not in node_data:
                continue
            inputs.append(FlakeInput(name=name, locked=node_data["locked"], original=node_data.get("original", {})))
    elif isinstance(root_inputs_raw, list):
        for node_name in root_inputs_raw:
            node_data = nodes.get(node_name)
            if not node_data or "locked" not in node_data:
                continue
            inputs.append(FlakeInput(name=node_name, locked=node_data["locked"], original=node_data.get("original", {})))
    else:
        for name, node_data in sorted(nodes.items()):
            if name == "root" or "locked" not in node_data:
                continue
            inputs.append(FlakeInput(name=name, locked=node_data["locked"], original=node_data.get("original", {})))
    return inputs
