"""Strongly-typed return structures for nix-flake-age operations."""
from dataclasses import dataclass


@dataclass(frozen=True)
class FetchResult:
    """Result of fetching a commit timestamp."""
    ok: bool
    rev: str | None = None
    timestamp: int | None = None
    error: str | None = None


@dataclass(frozen=True)
class CommitSearchResult:
    """Result of searching for a commit meeting age requirements."""
    ok: bool
    rev: str | None = None
    timestamp: int | None = None
    date: str | None = None
    depth: int = 0
    too_new_commit: str | None = None
    too_new_timestamp: int | None = None
    too_new_date: str | None = None
    error: str | None = None


@dataclass(frozen=True)
class AgeCheckResult:
    """Result of age validation."""
    ok: bool
    age_days: int
    commit_date: str
    error: str | None = None


@dataclass(frozen=True)
class FlakeInput:
    """Represents a single input from a flake.lock with locked and original metadata."""
    name: str
    locked: dict
    original: dict

    @property
    def input_type(self) -> str:
        return self.locked.get("type", "") or self.original.get("type", "")

    @property
    def has_rev(self) -> bool:
        return bool(self.locked.get("rev") or self.original.get("rev"))

    @property
    def rev(self) -> str:
        return self.locked.get("rev") or self.original.get("rev", "")

    def to_git_url(self) -> str | None:
        t = self.input_type
        if t == "github":
            owner = self.locked.get("owner", "")
            repo = self.locked.get("repo", "")
            if owner and repo:
                return f"https://github.com/{owner}/{repo}.git"
        elif t == "gitlab":
            host = self.locked.get("host", "gitlab.com")
            owner = self.locked.get("owner", "")
            repo = self.locked.get("repo") or self.locked.get("project", "")
            if repo:
                if owner:
                    return f"https://{host}/{owner}/{repo}.git"
                return f"https://{host}/{repo}.git"
        elif t == "sourcehut":
            owner = self.locked.get("owner", "")
            repo = self.locked.get("repo", self.locked.get("project", ""))
            if owner and repo:
                return f"https://git.sr.ht/~{owner}/{repo}"
        elif t == "git":
            url = self.locked.get("url") or self.original.get("url")
            if url:
                if url.startswith("git+"):
                    return url[4:]
                return url
        return None

    def target_ref(self) -> str | None:
        return self.original.get("ref")
