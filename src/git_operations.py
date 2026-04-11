"""Git command-line operations."""

import os
import subprocess
from pathlib import Path


def run_cmd(
    args: list[str],
    cwd: str | Path | None = None,
    timeout: int = 60,
    env_overrides: dict | None = None,
) -> tuple[int, str, str]:
    """Run a command, return (returncode, stdout, stderr)."""
    env = {**os.environ, **(env_overrides or {})}
    try:
        r = subprocess.run(args, capture_output=True, text=True, timeout=timeout, cwd=cwd, env=env)
        return r.returncode, r.stdout, r.stderr
    except subprocess.TimeoutExpired:
        return -1, "", f"{' '.join(args[:3])} timed out after {timeout}s"
    except Exception as e:
        return -1, "", str(e)


def run_git(
    args: list[str],
    cwd: str | Path | None = None,
    timeout: int = 60,
    env_overrides: dict | None = None,
) -> tuple[int, str, str]:
    """Run a git command."""
    return run_cmd(["git"] + list(args), cwd=cwd, timeout=timeout, env_overrides=env_overrides)


def git_env_no_prompt() -> dict:
    """Environment for non-interactive git operations."""
    return {
        "GIT_TERMINAL_PROMPT": "0",
        "GIT_ASKPASS": "echo",
        "GIT_CONFIG_COUNT": "1",
        "GIT_CONFIG_KEY_0": "protocol.version",
        "GIT_CONFIG_VALUE_0": "2",
    }


def ls_remote_refs(git_url: str, timeout: int = 30) -> dict[str, str]:
    """Run git ls-remote and return {ref_name: sha} dict."""
    rc, stdout, _ = run_git(
        ["ls-remote", "--refs", git_url], timeout=timeout,
    )
    if rc != 0:
        return {}
    refs: dict[str, str] = {}
    for line in stdout.strip().splitlines():
        if not line:
            continue
        parts = line.split("\t")
        if len(parts) == 2:
            sha, ref = parts
            refs[ref] = sha
    return refs


def resolve_default_ref(git_url: str, ref: str | None, timeout: int = 15) -> str:
    """Resolve the effective ref for a remote via git ls-remote.

    If ``ref`` is provided, return it as-is.
    Otherwise, try ``git ls-remote --symref <url> HEAD`` to discover the remote's
    default branch.  If all else fails, return ``"HEAD"``.
    """
    if ref:
        return ref

    rc, stdout, _ = run_git(
        ["ls-remote", "--symref", "--exit-code", git_url, "HEAD"],
        timeout=timeout,
    )
    if rc == 0 and stdout.strip():
        first_line = stdout.splitlines()[0]
        if first_line.startswith("ref: refs/heads/"):
            return first_line[len("ref: refs/heads/"):]

    return "HEAD"
