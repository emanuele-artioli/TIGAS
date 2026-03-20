# Browser Client Scaffold

This folder contains browser-side placeholders for interactive pose capture,
WebTransport and MoQ data transport, WebCodecs decode, and optional WebGPU
super-resolution.

## Planned Modules

1. `pose_capture.ts`: 6-DOF camera updates from user interaction.
2. `uplink_datagram.ts`: Datagrams with pose, LOD, and bitrate request fields.
3. `moq_client.ts`: WebTransport and MoQ session management.
4. `decoder.ts`: CMAF fragment buffering and WebCodecs decode path.
5. `super_resolution.ts`: Optional upscaling stage.
6. `main.ts`: Runtime wiring and adaptive policy hooks.

All files currently contain descriptive placeholders to guide incremental
implementation.
