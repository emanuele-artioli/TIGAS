"""MoQ publisher placeholder.

This module is responsible for publishing CMAF fragments as MoQ objects while
respecting per-object priority metadata.
"""

from __future__ import annotations

from tigas.shared.types import CmafFragment


class MoqObjectPublisher:
    """Placeholder for prioritized object publication over MoQ."""

    def publish(self, fragment: CmafFragment) -> None:
        """Publish one CMAF fragment as a MoQ object."""
        raise NotImplementedError("Implement MoQ object publication path.")
