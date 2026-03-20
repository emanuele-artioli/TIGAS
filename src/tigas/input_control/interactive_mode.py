"""Interactive mode placeholder.

This module will host server-side glue for ingesting browser control updates
and converting them to canonical uplink datagrams consumed by the pipeline.
"""

from __future__ import annotations

from tigas.shared.types import UplinkDatagram


class InteractivePoseIngestor:
    """Accept browser pose payloads and emit normalized datagrams.

    Future implementation targets:

    1. Validate browser payload shape and coordinate conventions.
    2. Enrich payload with sequence ids and sender timestamp.
    3. Apply client ABR request fields (LOD and target bitrate).
    """

    def from_browser_event(self, event: dict) -> UplinkDatagram:
        """Translate one browser event to canonical uplink format."""
        raise NotImplementedError(
            "Implement browser pose parsing and conversion to UplinkDatagram."
        )
