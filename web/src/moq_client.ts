/**
 * MoQ client placeholder.
 *
 * This module will own WebTransport lifecycle and object stream handling.
 */

export class MoqClient {
  async connect(url: string): Promise<void> {
    void url;
    throw new Error("Implement WebTransport session setup and MoQ handshake.");
  }

  async sendUplinkDatagram(payload: Uint8Array): Promise<void> {
    void payload;
    throw new Error("Implement unreliable datagram send path.");
  }

  async close(): Promise<void> {
    throw new Error("Implement transport teardown.");
  }
}
