"""Traffic control profile placeholders.

Provides a policy layer for reproducible network shaping profiles that can be
applied before headless ablation runs.
"""

from __future__ import annotations


class TcProfileManager:
    """Placeholder for Linux tc profile application and cleanup."""

    def apply(self, interface_name: str, profile_name: str) -> None:
        raise NotImplementedError("Implement tc profile application routine.")

    def clear(self, interface_name: str) -> None:
        raise NotImplementedError("Implement tc cleanup routine.")
