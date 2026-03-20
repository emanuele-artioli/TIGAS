/**
 * Browser runtime entrypoint placeholder.
 *
 * Final implementation should orchestrate:
 * 1. Pose capture
 * 2. Uplink datagram emission
 * 3. MoQ fragment reception
 * 4. Decode and optional super-resolution
 * 5. Frame presentation timing metrics
 */

import { MoqClient } from "./moq_client";
import { PoseCaptureService } from "./pose_capture";

export async function bootstrapClient(url: string): Promise<void> {
  const client = new MoqClient();
  const poseCapture = new PoseCaptureService();

  await client.connect(url);
  poseCapture.start();

  throw new Error("Implement main browser loop and pipeline wiring.");
}
