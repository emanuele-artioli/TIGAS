"""eBPF integration placeholders.

This module will bridge orchestration code with kernel probes that capture
packet departure and arrival timestamps at low jitter.
"""

from __future__ import annotations


class EbpfHookManager:
    """Placeholder API for attaching and detaching eBPF probes."""

    def attach(self, interface_name: str) -> None:
        raise NotImplementedError("Implement eBPF probe attach logic.")

    def detach(self) -> None:
        raise NotImplementedError("Implement eBPF probe detach logic.")

    def read_events(self) -> list[dict]:
        raise NotImplementedError("Implement eBPF event polling and normalization.")
