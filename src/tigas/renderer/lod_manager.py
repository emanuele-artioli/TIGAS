"""LOD registry and lookup helpers.

This module maps symbolic LOD ids to backend-specific model variants, allowing
the ABR layer to request quality changes without knowing backend details.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class LodVariant:
    """Single model variant used for quality and performance tradeoffs."""

    lod_id: str
    model_path: str
    notes: str


class LodRegistry:
    """In-memory registry of available LOD variants."""

    def __init__(self) -> None:
        self._variants: dict[str, LodVariant] = {}

    def register(self, variant: LodVariant) -> None:
        """Add or replace one LOD variant entry."""
        self._variants[variant.lod_id] = variant

    def resolve(self, lod_id: str) -> LodVariant:
        """Resolve a symbolic LOD id to concrete model resources."""
        if lod_id not in self._variants:
            raise KeyError(f"Unknown LOD id: {lod_id}")
        return self._variants[lod_id]
