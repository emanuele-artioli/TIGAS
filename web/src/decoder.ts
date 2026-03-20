/**
 * Decoder placeholder for CMAF fragment handling and WebCodecs decode.
 */

export class DecoderPipeline {
  async initialize(): Promise<void> {
    throw new Error("Implement decoder and demux initialization.");
  }

  async pushFragment(fragment: Uint8Array): Promise<void> {
    void fragment;
    throw new Error("Implement CMAF fragment ingestion and decode dispatch.");
  }

  async shutdown(): Promise<void> {
    throw new Error("Implement decoder teardown and resource release.");
  }
}
