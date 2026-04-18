"""Utilities for parallel processing of flake inputs."""

from __future__ import annotations

import concurrent.futures
from typing import Callable, List, Tuple

from ..core.models import FlakeInput


def execute_parallel(
    inputs: List[FlakeInput],
    processor: Callable[[FlakeInput], dict | None],
    max_workers: int,
) -> List[Tuple[FlakeInput, dict]]:
    """Process a list of inputs in parallel (or sequentially) using a processor function.

    Args:
        inputs: List of FlakeInput objects to process.
        processor: Function that takes a FlakeInput and returns a result dict or None.
        max_workers: Number of parallel workers. If <= 0, processes sequentially.

    Returns:
        List of (input, result) tuples for non-None results.
    """
    if max_workers <= 0:
        results = []
        for inp in inputs:
            res = processor(inp)
            if res is not None:
                results.append((inp, res))
        return results

    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_inp = {
            executor.submit(processor, inp): inp for inp in inputs
        }
        results = []
        for future in concurrent.futures.as_completed(future_to_inp):
            inp = future_to_inp[future]
            res = future.result()
            if res is not None:
                results.append((inp, res))
        return results
