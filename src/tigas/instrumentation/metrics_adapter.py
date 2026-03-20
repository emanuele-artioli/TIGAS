"""Metrics adapter placeholder.

Defines a contract-compatible adapter around a lock-free circular buffer so hot
path components can emit telemetry without blocking.
"""

from __future__ import annotations

from tigas.shared.types import MetricEvent


class MetricsBufferAdapter:
    """Placeholder adapter for lock-free metrics collection pipeline."""

    def write_event(self, event: MetricEvent) -> None:
        """Write one event to the shared-memory ring buffer."""
        raise NotImplementedError("Integrate provided metrics_buffer implementation.")

    def drain_to_parquet(self, output_path: str) -> int:
        """Drain buffered events and persist them to parquet output."""
        raise NotImplementedError("Implement non-blocking background drain worker.")
