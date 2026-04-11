"""Core utilities for the *nix‑flake‑age‑filter* project.

The subpackage provides:

* **models** – immutable dataclasses representing flake inputs.
* **age_check** – helpers that use the ``whenever`` library to compute commit
  age and format durations.
* **git_ops** – wrappers around ``git`` (and optional ``pygit2``) for fetching
  timestamps and resolving refs.
* **lock_file** – parsing of ``flake.lock`` and extraction of root inputs.
* **errors** – a small hierarchy of domain‑specific exceptions.
"""
