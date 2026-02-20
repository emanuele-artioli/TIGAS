# **TIGAS: 3DGS Ultra-Low Latency Streaming Pipeline**

**Architecture and Implementation Blueprint**

## **1\. System Architecture Overview**

TIGAS is an end-to-end, server-side rendering (SSR) pipeline for 3D Gaussian Splatting (3DGS). It delivers ultra-low latency interactive streaming by encoding individual frames as CMAF chunks over a QUIC (HTTP/3) transport layer.  
The system operates in two distinct modes:

* **Basic Mode (Interactive):** A human user navigates the 3D space via a Chrome GUI. The server renders and streams the viewport in real-time.  
* **Test Mode (Evaluation):** Headless automated execution driven by movement and network trace files, followed by automated VMAF quality evaluation comparing ground-truth lossless renders against network-degraded streams.

## **2\. Component Implementation Details**

### **2.1. The Client (Player & Controller)**

The client is a web application running in Google Chrome, utilizing native browser APIs for low-latency transport.

* **Video Player (dash.js):** \* Configured for **Ultra-Low Latency (ULL)**.  
  * Buffer configuration is set to near-zero.  
  * Leverages the built-in throughput-based Adaptive Bitrate (ABR) algorithm to request different CRF (Constant Rate Factor) qualities based on estimated network capacity.  
* **Control Channel (WebTransport):**  
  * Standard WebSockets are blocked by TCP head-of-line blocking. TIGAS uses **WebTransport** (running over HTTP/3/QUIC) using Unreliable Datagrams.  
  * **Payload Structure:** To minimize overhead, 6DoF data is sent as a tightly packed binary Float32Array (28 bytes total per message).  
    // Client-side WebTransport Datagram payload  
    const buffer \= new ArrayBuffer(28);  
    const view \= new Float32Array(buffer);  
    view\[0\] \= performance.now(); // Timestamp  
    view\[1\] \= x;                 // Translation X  
    view\[2\] \= y;                 // Translation Y  
    view\[3\] \= z;                 // Translation Z  
    view\[4\] \= pitch;             // Rotation X  
    view\[5\] \= yaw;               // Rotation Y  
    view\[6\] \= roll;              // Rotation Z

    // Send via WebTransport datagram writer  
    writer.write(buffer);

### **2.2. Network Layer (QUIC / HTTP/3)**

To natively support dash.js requests and WebTransport, the server is fronted by an HTTP/3 capable server layer (e.g., Nginx with quic module or a custom Node.js/Go backend utilizing HTTP/3 libraries).

* All .m4s DASH segment requests and WebTransport control messages share the same underlying UDP QUIC connection, ensuring multiplexing without TCP stream blocking.

### **2.3. Server-Side Rendering (SSR) & Encoding**

This is the most critical latency bottleneck. Bouncing raw frames to disk or through slow Python wrappers is prohibited.

* **Rendering Engine:** A C++/CUDA application (e.g., a headless fork of the SIBR viewer) loads the .ply file (/Users/manu/Desktop/Datasets/3DGS\_PLY\_sample\_data/PLY(postshot)/cactus\_splat3\_30kSteps\_142k\_splats.ply).  
* **Memory Management:** The C++ renderer must map the rendered RGB frame buffer directly into memory accessible by the encoder.  
* **Encoding via libavcodec (FFmpeg API):** Instead of piping to an FFmpeg CLI process (which limits per-frame SEI injection), the C++ renderer links directly against FFmpeg's libavcodec and libavformat.  
  * **Hardware Acceleration:** NVENC (NVIDIA Hardware Encoding) is strictly required (h264\_nvenc or hevc\_nvenc).  
  * **Latency Tuning Parameters:**  
    * \-tune zerolatency  
    * \-preset p1 or p2 (fastest encoding)  
    * \-bf 0 (No B-frames)  
    * \-g 1 (GOP size of 1, forcing every frame to be an I-frame/IDR, allowing 1-frame segment independence).  
* **DASH/CMAF Chunking:**  
  * The encoder outputs strictly **1 frame per CMAF segment**.  
  * **Live Profile MPD:** The MPD uses a SegmentTemplate with $Number$ addressing. This prevents the client from needing to constantly download the MPD.  
    \<\!-- TIGAS MPD Snippet \--\>  
    \<SegmentTemplate timescale="60" initialization="init.mp4" media="chunk\_$Number$.m4s" duration="1" startNumber="1"/\>

### **2.4. SEI Frame Matching (Option A)**

To perfectly align ground-truth frames with lossy streamed frames during Test Mode evaluation, exact Frame IDs/Timestamps are injected directly into the encoded video bitstream.

* **Implementation:** Inside the C++ rendering loop, before submitting the AVPacket to libavformat for CMAF muxing, a Supplemental Enhancement Information (SEI) NAL unit containing the frame\_id and timestamp is prepended to the encoded frame's payload.  
* The evaluation decoder will parse these SEI messages to map the decoded output back to the exact source frame, regardless of network drops or ABR shifts.

## **3\. Test Mode & Evaluation Pipeline**

When TIGAS runs in Test Mode, the interactive GUI is disabled, and the system executes a deterministic pipeline.

### **Step 1: Ground Truth Pre-computation**

1. The server reads a **Movement Trace File** (e.g., CSV of \[timestamp, x, y, z, pitch, yaw, roll\]).  
2. The renderer generates the frames for these exact 6DoF coordinates and saves them locally as lossless PNGs or a lossless FFV1 MKV file.

### **Step 2: Network Shaping**

Before the client connects, the server shapes its outgoing network interface using the Linux Traffic Control (tc) system, guided by a **Network Trace File** (defining bandwidth, latency, and packet loss over time).  
\# Example tc command applying 50ms latency, 10mbit cap, and 1% packet loss  
tc qdisc add dev eth0 root handle 1: netem delay 50ms loss 1%  
tc qdisc add dev eth0 parent 1:1 handle 10: tbf rate 10mbit burst 32kbb latency 400ms

### **Step 3: Headless Execution**

1. A Headless Chrome instance is launched via Puppeteer/Selenium.  
2. The client reads the identical **Movement Trace File** and transmits the 6DoF coordinates via WebTransport.  
3. dash.js requests the ULL DASH stream. Due to the tc shaping, the ABR algorithm will dynamically request varying CRF qualities.  
4. The server renders, injects the SEI, encodes at the requested CRF, and sends the CMAF chunks.  
5. The server saves the generated lossy stream to disk (test\_stream\_lossy.mp4).

### **Step 4: Quality Evaluation (VMAF)**

Once the streaming session concludes, the evaluation script extracts the frames and computes VMAF.

1. **SEI Extraction:** ffprobe or a custom script reads the SEI messages from test\_stream\_lossy.mp4 to map each frame to its corresponding ground-truth frame ID.  
2. **VMAF Calculation:** FFmpeg calculates the VMAF score using the matched lossless and lossy frames.  
   ffmpeg \-i test\_stream\_lossy.mp4 \-i ground\_truth\_lossless.mkv \\  
     \-lavfi "\[0:v\]\[1:v\]libvmaf=model\_path=vmaf\_v0.6.1.json:log\_path=vmaf\_results.json:log\_fmt=json" \\  
     \-f null \-

## **4\. Required Dependencies summary**

* **Server OS:** Linux (required for tc network shaping).  
* **Renderer:** C++17, CUDA Toolkit, libavcodec/libavformat/libavutil (FFmpeg 6.0+).  
* **Transport:** HTTP/3 Server implementation supporting WebTransport.  
* **Client:** Google Chrome (Headless mode for testing), dash.js ULL profile.  
* **Evaluation:** FFmpeg compiled with \--enable-libvmaf.