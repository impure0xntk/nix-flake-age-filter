"""FlakeInput ドメインモデル。

flake.lock 内の input を表現し、URL 変換・ref 解決などの責務を持つ。
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class FlakeInput:
    """flake.lock 内の1つの input を表す。"""

    name: str
    locked: dict
    original: dict

    @property
    def input_type(self) -> str:
        return self.locked.get("type", "unknown")

    @property
    def rev(self) -> str | None:
        return self.locked.get("rev")

    @property
    def has_rev(self) -> bool:
        return bool(self.rev)

    @property
    def locked_ts(self) -> int | None:
        ts = self.locked.get("lastModified")
        return int(ts) if ts is not None else None

    def to_git_url(self) -> str | None:
        """Construct a git HTTPS URL."""
        t = self.input_type
        if t == "github":
            return (
                f"https://github.com/{self.locked.get('owner', '')}"
                f"/{self.locked.get('repo', '')}.git"
            )
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
        # path and default inputs are skipped
        return None

    def target_ref(self) -> str | None:
        """Return the ref (branch/tag) that update will pull."""
        return self.original.get("ref") or self.original.get("branch") or None

    def to_flake_url(self, rev: str | None = None) -> str | None:
        """Construct a flake URL (github:owner/repo[/<rev>])."""
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
            if not url.startswith("git+"):
                url = f"git+{url}"
            return f"{url}?rev={rev}" if rev else url

        if t == "indirect":
            oref = self.original.get("id", "")
            if "/" in oref:
                return f"{oref}/{rev}" if rev else oref
            return None

        return None
