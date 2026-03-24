# **Architecture Prompt: Modular 3DGS/4DGS Remote Rendering Testbed**

## **1\. Project Goal**

Develop a research-grade remote rendering system for 3D Gaussian Splatting (3DGS) and 4DGS. The system strives to achieve \<100ms motion-to-photon latency using a modern transport stack (MoQ/QUIC) and support extensive ablation studies through a modular, containerized architecture. Since this is research software, performance is an objective but not a strict hard gate; novelty, reproducibility, and usability across operating systems and GPU vendors are equally important. This is achieved by keeping components separated and interacting via explicit dataflow contracts, so workflow ownership is clear, debugging is easier, and modules can be swapped for ablations.

## **2\. Core Tech Stack**

* **Transport**: Media over QUIC (MoQ) via WebTransport.  
* **Packaging**: CMAF (Fragmented MP4) for video chunks.  
* **Client**: Browser-based (WebCodecs for decoding, WebGPU for optional Super-Resolution).  
* **Server**: Python/C++ orchestrator with CUDA/C++/Apple Silicon renderer support.  
* **Containerization**: Docker-based micro-services for each module.

## **3\. Modular Component Requirements (Standardized I/O)**

### **A. Input & Control (Uplink)**

* **Interactive Mode**: Browser (JS) captures 6-DOF camera poses.  
* **Headless Mode**: Trace-replayer reads standardized .json movement traces.  
* **Piggybacking**: Every uplink datagram must contain: \[Seq\_ID | Timestamp | 4x4\_Matrix | Requested\_LOD | Target\_Bitrate\].  
* **Protocol**: Unreliable QUIC Datagrams.

### **B. Intelligence Layer**

* **Pose Predictor**: Module to extrapolate camera angles at $t \+ RTT$. Implement a baseline (No-op) and a Kalman Filter.  
* **ABR Controller**:  
  * **Client-side**: Throughput estimation to request specific Bitrate/LOD.  
  * **Server-side**: Monitor GPU frame-times to trigger model quantization/sampling.

### **C. Rendering Engine (The "Wrapper" Pattern)**

* Interface must accept (pose, lod, time\_offset). time\_offset ensures 4DGS compatibility.  
* Implementations: gsplat (CUDA), WebGPU (General GPU), and a CPU fallback.  
* **LOD Management**: Server must hold multiple 3DGS variations (e.g., Full, 50% sampled, 8-bit quantized).

### **D. Media Coder**

* Standardized wrapper for encoding raw frames into CMAF fragments.  
* Support: h264\_nvenc, av1\_nvenc, libx264, and Apple VideoToolbox.  
* **Prioritization**: Tag MoQ Objects with priorities (I-frames \= High, P-frames \= Normal).

### **E. Client-Side Post-Processing**

* **WebGPU Super-Resolution**: Optional modular component to upscale 720p renders to 1080p locally to save bandwidth.

### **F. Evaluation & Ablation Component (Offline Only)**

* Must be a dedicated module separated from runtime-critical components.
* Owns all experiment-only work: frame dumps, metric aggregation, SSIM/quality proxies, tradeoff-curve generation, and video encoding.
* Must support matrix sweeps over:
  * splat sparsity levels,
  * output resolutions,
  * quantization strengths.
* Must compute an image-quality proxy (at least SSIM against a full-reference run at the same resolution).
* Runtime modules (renderer/orchestrator/transport) must not include evaluation-specific logic that would add hot-path latency.

## **4\. Performance & Research Instrumentation**

* **Zero-Interference Metrics**: Use the provided metrics\_buffer.py. Hot-paths (Renderer/Transport) write to a lock-free circular buffer in shared memory. A background thread drains to .parquet.  
* **eBPF Integration**: Provide scripts to hook into the Linux kernel to measure exact packet departure/arrival at the NIC, bypassing application-layer jitter.  
* **Network Shaping**: Integration with Linux tc (Traffic Control) for reproducible network ablation (5G, LTE, Wi-Fi traces).

## **5\. Development Workflow**

* **Docker**: Each module (renderer, encoder, predictor) must have its own Dockerfile.  
* **GitHub Actions**: Create a workflow that runs an "Ablation Matrix" (Headless Client \+ Server) across different configurations and uploads metrics as artifacts.  
* **Isolation**: Every component must be usable in isolation if its standardized I/O (defined in the project spec) is respected.
* **Evaluation Decoupling**: Evaluation should be runnable repeatedly during development, but fully optional once runtime validation is complete.

## **6\. Success Criteria**

1. Successful rendering of a 3DGS scene in a browser via MoQ with \<100ms latency.  
2. Ability to run a "Headless Ablation" that compares h264 vs av1 using a movement trace and outputs a performance report.  
3. 4DGS ready: The system clock must be passed through the entire pipeline to support temporal splats.

## **7\. Current Implementation Snapshot (March 2026)**

Implemented now:

1. Headless runtime rendering path with CPU and gsplat backends.
2. Offline evaluation module with frame metrics, SSIM proxy, video encoding, and tradeoff curves.
3. Standardized movement/network trace selection by file path or trace name.
4. File-based ABR profiles with runtime selection (`throughput`, `bola`, `robustmpc`).
5. Optional best-effort Linux `tc` shaping hooks.

Not fully implemented yet:

1. Full interactive browser-to-transport production path.
2. End-to-end MoQ runtime validation against strict latency targets.
3. Transport-coupled throughput measurement (current ABR estimator is renderer-payload based).

## **8\. Re-entry Plan**

When resuming development after a pause:

1. Start with `docs/REENTRY.md` and follow the startup checklist.
2. Re-run tests and a short runtime smoke experiment.
3. Re-run ABR comparison using fixed movement and network traces.
4. Use generated reports to choose next ABR/profile tuning or transport integration task.
5. Update docs immediately after any architectural or CLI change.