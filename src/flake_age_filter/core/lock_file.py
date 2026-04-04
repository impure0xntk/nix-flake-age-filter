"""flake.lock のパース。"""

from __future__ import annotations

import json
from pathlib import Path

from flake_age_filter.core.errors import FlakeLockNotFoundError, FlakeLockParseError
from flake_age_filter.core.flake_input import FlakeInput


def parse_flake_lock(path: str) -> dict:
    """Load flake.lock and return JSON structure."""
    p = Path(path)
    if not p.exists():
        raise FlakeLockNotFoundError(f"flake.lock not found at {path}")
    try:
        return json.loads(p.read_text())
    except json.JSONDecodeError as e:
        raise FlakeLockParseError(f"Failed to parse flake.lock: {e}") from e


def extract_locked_inputs(lock_data: dict) -> list[FlakeInput]:
    """Extract direct root inputs from flake.lock."""
    nodes = lock_data.get("nodes", {})
    root_node = nodes.get("root", {})
    root_inputs_raw = root_node.get("inputs", {})

    inputs: list[FlakeInput] = []

    if isinstance(root_inputs_raw, dict):
        for name, target in root_inputs_raw.items():
            node_name = _resolve_node_ref(target)
            if node_name is None:
                continue
            node_data = nodes.get(node_name)
            if not node_data or "locked" not in node_data:
                continue
            inputs.append(FlakeInput(
                name=name,
                locked=node_data["locked"],
                original=node_data.get("original", {}),
            ))
    elif isinstance(root_inputs_raw, list):
        for node_name in root_inputs_raw:
            node_data = nodes.get(node_name)
            if not node_data or "locked" not in node_data:
                continue
            inputs.append(FlakeInput(
                name=node_name,
                locked=node_data["locked"],
                original=node_data.get("original", {}),
            ))
    else:
        # Fallback: all nodes other than root
        for name, node_data in sorted(nodes.items()):
            if name == "root" or "locked" not in node_data:
                continue
            inputs.append(FlakeInput(
                name=name,
                locked=node_data["locked"],
                original=node_data.get("original", {}),
            ))

    return inputs


def _resolve_node_ref(target: str | list | dict) -> str | None:
    if isinstance(target, str):
        return target
    if isinstance(target, list) and len(target) > 0:
        return target[0] if isinstance(target[0], str) else None
    return None
