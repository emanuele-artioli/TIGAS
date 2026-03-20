"""Browser bridge placeholder.

Intended to host control and telemetry exchange helpers between Python
orchestration and browser runtime services.
"""

from __future__ import annotations


class BrowserRuntimeBridge:
    """Placeholder API surface for browser runtime coordination."""

    def start_session(self) -> None:
        raise NotImplementedError("Implement browser session bootstrap RPC.")

    def stop_session(self) -> None:
        raise NotImplementedError("Implement browser session teardown RPC.")
