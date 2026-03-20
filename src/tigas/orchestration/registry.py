"""Component registry placeholder.

Maps configuration names to concrete implementations for predictors, renderers,
encoders, and transports while preserving explicit interface boundaries.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class ComponentRegistry:
    """Runtime lookup tables for component factories."""

    predictors: dict[str, object]
    renderers: dict[str, object]
    encoders: dict[str, object]
    transports: dict[str, object]


def build_default_registry() -> ComponentRegistry:
    """Build registry with placeholder factory entries.

    Concrete factories will be wired as module implementations are completed.
    """
    return ComponentRegistry(predictors={}, renderers={}, encoders={}, transports={})
