"""Pipeline orchestration placeholder.

Intended responsibilities:

1. Create module instances from runtime configuration.
2. Wire dataflow between input, intelligence, rendering, coding, and transport.
3. Emit lifecycle and metrics events for observability.
"""

from __future__ import annotations

from tigas.shared.config import RuntimeConfig


class TigasPipeline:
    """Placeholder orchestrator for interactive and replay execution."""

    def __init__(self, config: RuntimeConfig) -> None:
        self.config = config

    def start(self) -> None:
        raise NotImplementedError("Implement startup sequence and component wiring.")

    def step(self) -> None:
        raise NotImplementedError("Implement one pipeline tick for deterministic testing.")

    def stop(self) -> None:
        raise NotImplementedError("Implement orderly shutdown and metrics flush.")
