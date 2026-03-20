/**
 * Uplink datagram contract used by browser runtime.
 *
 * This mirrors the server schema so interactive and headless sources share
 * identical control semantics.
 */

export type LodId = "full" | "sampled_50" | "quant_8bit" | "adaptive";

export interface UplinkDatagram {
  seq_id: number;
  timestamp_ms: number;
  camera_matrix_4x4: number[];
  requested_lod: LodId;
  target_bitrate_kbps: number;
}

export function serializeDatagram(datagram: UplinkDatagram): Uint8Array {
  const payload = JSON.stringify(datagram);
  return new TextEncoder().encode(payload);
}
