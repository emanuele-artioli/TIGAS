/**
 * Pose capture placeholder.
 *
 * Planned behavior:
 * 1. Listen to camera movement from mouse, touch, or headset APIs.
 * 2. Convert user pose into a 4x4 matrix in agreed coordinate system.
 * 3. Emit at stable cadence for low-jitter control updates.
 */

export interface PoseCaptureSample {
  timestamp_ms: number;
  camera_matrix_4x4: number[];
}

export class PoseCaptureService {
  start(): void {
    throw new Error("Implement camera event subscription and sampling loop.");
  }

  stop(): void {
    throw new Error("Implement capture loop cleanup.");
  }

  readLatest(): PoseCaptureSample {
    throw new Error("Implement latest sample retrieval.");
  }
}
