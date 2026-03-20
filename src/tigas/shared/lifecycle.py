"""Lifecycle contracts for start, stop, and health checks.

Every runtime subcomponent should implement this protocol so the orchestrator
can uniformly control startup ordering, teardown, and fault handling.
"""

from __future__ import annotations

from typing import Protocol


class LifecycleComponent(Protocol):
    """Common lifecycle contract for all runtime modules."""

    def start(self) -> None:
        """Allocate resources and begin serving requests."""

    def stop(self) -> None:
        """Gracefully release resources and flush pending data."""

    def healthcheck(self) -> bool:
        """Return True if component is operational."""
