"""Backend registry for GitBackend implementations.

Provides a simple registry pattern for backend discovery and selection.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Dict, Optional, Type

if TYPE_CHECKING:
    from .base import GitBackend


# Global registry of backend classes
_backends: Dict[str, Type["GitBackend"]] = {}


def register_backend(cls: Type["GitBackend"]) -> Type["GitBackend"]:
    """Decorator to register a backend class.
    
    Usage:
        @register_backend
        class MyBackend(GitBackend):
            name = "mybackend"
            ...
    """
    if hasattr(cls, "name") and cls.name:
        _backends[cls.name] = cls
    return cls


def get_backend(
    name: str,
    timeout: int = 120,
    **kwargs,
) -> "GitBackend":
    """Get a backend instance by name.
    
    Args:
        name: Backend name ("subprocess", "pygit2", "github", "auto").
        timeout: Default timeout for operations.
        **kwargs: Additional arguments passed to backend constructor.
        
    Returns:
        Backend instance.
        
    Raises:
        ValueError: If backend not found or not available.
    """
    if name not in _backends:
        available = list_backends()
        raise ValueError(
            f"Unknown backend: {name!r}. Available: {available}"
        )
    
    backend_cls = _backends[name]
    instance = backend_cls(timeout=timeout, **kwargs)
    
    if not instance.is_available():
        raise ValueError(
            f"Backend {name!r} is not available (missing dependencies)"
        )
    
    return instance


def list_backends() -> list[str]:
    """List all registered backend names."""
    return list(_backends.keys())


def clear_backends() -> None:
    """Clear all registered backends (for testing)."""
    _backends.clear()
