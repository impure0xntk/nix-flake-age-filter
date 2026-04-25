"""Data models for the flake‑age filter.

We keep the original `FlakeInput` class but rewrite it as an immutable
`@dataclass`.  Type hints are added and helper methods are thin wrappers
around the logic that existed in the legacy implementation.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Any, Optional


@dataclass(frozen=True)
class FlakeInput:
    """Represents a single flake input as read from ``flake.lock``.

    ``locked`` and ``original`` are the raw dictionaries coming from the lock
    file.  The class provides convenience properties for the fields that are
    needed throughout the code base.
    """

    name: str
    locked: Dict[str, Any]
    original: Dict[str, Any]

    @property
    def input_type(self) -> str:
        return self.locked.get("type", "unknown")

    @property
    def rev(self) -> Optional[str]:
        return self.locked.get("rev")

    @property
    def has_rev(self) -> bool:
        return bool(self.rev)

    @property
    def ref(self) -> Optional[str]:
        """Return the reference (branch/tag) that was locked.

        The original implementation looked at ``locked.ref`` first, then fell
        back to the original definition's ``ref`` or ``branch``.
        """
        return (
            self.locked.get("ref")
            or self.original.get("ref")
            or self.original.get("branch")
        )

    @property
    def is_path(self) -> bool:
        """Return True if this input is a local path reference."""
        return self.input_type == "path"

    # ---------------------------------------------------------------------
    # URL helpers – these are pure functions that do not perform any I/O.
    # ---------------------------------------------------------------------
    def to_git_url(self) -> Optional[str]:
        """Build a remote git URL for the input.

        Supports the typical ``github`` style (HTTPS) **and** an explicit SSH
        URL when the source dictionary already provides one.  Returns ``None``
        for inputs that are not fetchable via git (e.g. ``path``, ``file:``
        URLs, or unknown types).
        """
        t = self.input_type
        if t == "github":
            # Prefer an explicit SSH URL if the original lock entry contains it.
            url = self.locked.get("url") or self.original.get("url")
            if url and url.startswith("git@"):
                # Ensure it ends with .git for consistency.
                return url if url.endswith(".git") else f"{url}.git"
            # Fallback to the canonical HTTPS form.
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
            url = self.locked.get("url") or self.original.get("url")
            # Skip local file URLs (file: scheme) — they have no remote git history.
            if url and url.startswith("file:"):
                return None
            return url
        if t == "indirect":
            oref = self.original.get("id", "")
            if "/" in oref:
                parts = oref.split("/")
                return f"https://github.com/{parts[0]}/{'/'.join(parts[1:])}.git"
            return None
        return None

    def to_flake_url(self, rev: Optional[str] = None) -> Optional[str]:
        """Build a flake URL (e.g. ``example=github:owner/repo[/rev]``).

        The returned string is prefixed with the input name (``example=``) so that
        it can be used directly as an ``override-input`` argument for ``nix
        flake update``.  ``rev`` may be omitted – in that case the URL points to
        the input without a pinned revision.
        """
        t = self.input_type
        if t == "github":
            owner = self.locked.get("owner", "")
            repo = self.locked.get("repo", "")
            base = f"github:{owner}/{repo}"
            url = f"{base}/{rev}" if rev else base
        elif t == "gitlab":
            host = self.locked.get("host", "gitlab.com")
            owner = self.locked.get("owner", "")
            repo = self.locked.get("repo") or self.locked.get("project", "")
            base = f"gitlab:{host}/{owner}/{repo}" if owner else f"gitlab:{host}/{repo}"
            url = f"{base}/{rev}" if rev else base
        elif t == "sourcehut":
            owner = self.locked.get("owner", "")
            repo = self.locked.get("repo", self.locked.get("project", ""))
            base = f"git+https://git.sr.ht/~{owner}/{repo}"
            url = f"{base}?rev={rev}" if rev else base
        elif t == "git":
            raw = self.locked.get("url") or self.original.get("url")
            if not raw:
                return None
            if raw.startswith("git+"):
                url = f"{raw}?rev={rev}" if rev else raw
            else:
                url = f"git+{raw}?rev={rev}" if rev else f"git+{raw}"
        elif t == "indirect":
            oref = self.original.get("id", "")
            if "/" in oref:
                url = f"{oref}/{rev}" if rev else oref
            else:
                return None
        else:
            return None
        # Prefix with the input name for ``override-input`` syntax.
        return f"{self.name}={url}"
