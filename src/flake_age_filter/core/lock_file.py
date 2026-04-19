"""Flake lock file parsing utilities.

This module isolates the logic for reading ``flake.lock`` and extracting
the root inputs.  The public functions are thin wrappers around JSON
parsing and dataclass construction, making them trivial to unit‑test.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

from .models import FlakeInput
from .errors import FlakeLockNotFoundError


def parse_flake_lock(path: str | Path) -> Dict[str, Any]:
    """Load and parse ``flake.lock`` from ``path``.

    Raises:
        FlakeLockNotFoundError: If the file does not exist.
        json.JSONDecodeError: If the file is not valid JSON.
    """
    lock_path = Path(path)
    if not lock_path.exists():
        raise FlakeLockNotFoundError(f"flake.lock not found at {path}")
    return json.loads(lock_path.read_text())


def extract_locked_inputs(lock_data: Dict[str, Any]) -> List[FlakeInput]:
    """Return the list of direct root inputs from a parsed ``flake.lock``.

    The function walks the ``nodes`` dictionary and builds :class:`FlakeInput`
    instances for each entry referenced from the ``root`` node.  The logic
    mirrors the original implementation but returns the new immutable
    dataclass instead of the legacy class.
    """
    nodes = lock_data.get("nodes", {})
    root_node = nodes.get("root", {})
    root_inputs_raw = root_node.get("inputs", {})

    inputs: List[FlakeInput] = []

    # ---------------------------------------------------------------
    # Modern lock format – ``root`` node contains a dict of inputs.
    # ---------------------------------------------------------------
    if isinstance(root_inputs_raw, dict) and root_inputs_raw:
        for name, target in root_inputs_raw.items():
            # Strip possible namespace prefixes (e.g., "inputs/")
            name = name.split("/")[-1]
            if isinstance(target, str):
                node_name = target
            elif isinstance(target, list) and len(target) > 0:
                node_name = target[0]
            else:
                continue

            node_data = nodes.get(node_name)
            if not node_data or "locked" not in node_data:
                continue
            inputs.append(
                FlakeInput(
                    name=name,
                    locked=node_data["locked"],
                    original=node_data.get("original", {}),
                )
            )
    # ---------------------------------------------------------------
    # Older lock format – ``root`` inputs is a list of node names.
    # ---------------------------------------------------------------
    elif isinstance(root_inputs_raw, list) and root_inputs_raw:
        for node_name in root_inputs_raw:
            # Strip possible namespace prefixes (e.g., "inputs/")
            node_name = node_name.split("/")[-1]
            node_data = nodes.get(node_name)
            if not node_data or "locked" not in node_data:
                continue
            inputs.append(
                FlakeInput(
                    name=node_name,
                    locked=node_data["locked"],
                    original=node_data.get("original", {}),
                )
            )
    # ---------------------------------------------------------------
    # Fallback – enumerate all non‑root nodes that have a ``locked`` dict.
    # ---------------------------------------------------------------
    else:
        for name, node_data in sorted(nodes.items()):
            if name == "root" or "locked" not in node_data:
                continue
            # Strip possible namespace prefixes (e.g., "inputs/")
            clean_name = name.split("/")[-1]
            inputs.append(
                FlakeInput(
                    name=clean_name,
                    locked=node_data["locked"],
                    original=node_data.get("original", {}),
                )
            )
    return inputs


def read_flake_inputs(flake_lock_path: str | Path) -> List[FlakeInput]:
    """Convenience wrapper that parses the lock file and extracts inputs.

    Equivalent to::

        lock_data = parse_flake_lock(flake_lock_path)
        inputs = extract_locked_inputs(lock_data)

    This function exists to provide a single call‑site for the CLI modules.
    """  # noqa: D401
    lock_data = parse_flake_lock(flake_lock_path)
    return extract_locked_inputs(lock_data)
