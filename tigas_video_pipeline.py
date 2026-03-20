#!/usr/bin/env python3
"""Low-latency H.264 frame pipeline for TIGAS.

This module provides three core building blocks for per-frame remote rendering:

1) VideoEncoder: hardware-preferred H.264 encoding with low-latency options.
2) StreamManager: frame bitstream -> NAL units -> QUIC-safe packets.
3) VideoDecoder: packet reassembly and real-time decoding with stale-frame drop.

It also includes a latency-aware ABR controller that adjusts encoder CRF/bitrate.
"""

from __future__ import annotations

import logging
import platform
import struct
import time
from dataclasses import dataclass, field
from fractions import Fraction
from typing import Callable, Dict, Iterable, Iterator, Optional, Sequence

import av
import numpy as np

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class EncoderConfig:
    """Runtime configuration for low-latency H.264 encoding."""

    width: int
    height: int
    fps: int = 30
    prefer_hardware: bool = True
    codec_candidates: Optional[Sequence[str]] = None
    initial_bitrate_bps: int = 4_000_000
    initial_crf: int = 25
    thread_count: int = 0
    pix_fmt: str = "yuv420p"

    def __post_init__(self) -> None:
        if self.width <= 0 or self.height <= 0:
            raise ValueError("width and height must be positive")
        if self.fps <= 0:
            raise ValueError("fps must be positive")
        if self.initial_bitrate_bps <= 0:
            raise ValueError("initial_bitrate_bps must be positive")
        if not (0 <= self.initial_crf <= 51):
            raise ValueError("initial_crf must be in [0, 51]")
        if self.pix_fmt == "yuv420p" and (self.width % 2 != 0 or self.height % 2 != 0):
            raise ValueError(
                "yuv420p requires even width/height; "
                f"got {self.width}x{self.height}"
            )


@dataclass(frozen=True)
class EncodedFrame:
    """Single encoded frame payload and metadata."""

    frame_id: int
    nal_units: list[bytes]
    is_keyframe: bool
    total_bytes: int
    encode_ms: float
    codec_name: str


@dataclass(frozen=True)
class PacketMetadata:
    """Metadata extracted from a transport packet header."""

    frame_id: int
    nal_index: int
    nal_count: int
    frag_index: int
    frag_count: int
    flags: int
    payload: bytes


@dataclass(frozen=True)
class DecodedFrame:
    """Fully decoded frame with timing metadata."""

    frame_id: int
    frame_rgb: np.ndarray
    decode_ms: float
    codec_name: str


@dataclass
class AbrSample:
    """Per-frame telemetry used by latency-driven ABR."""

    frame_id: int
    frame_bytes: int
    network_ms: float
    render_ms: float
    encode_ms: float
    decode_ms: float
    packet_loss_ratio: float = 0.0


@dataclass(frozen=True)
class AbrDecision:
    """ABR decision to apply on the encoder."""

    bitrate_bps: int
    crf: int
    reason: str


@dataclass
class _FrameAssembly:
    """Internal reassembly state for a frame's fragmented NAL units."""

    frame_id: int
    nal_count: int
    is_keyframe: bool
    created_at_ms: float
    updated_at_ms: float
    fragments: Dict[int, Dict[int, bytes]] = field(default_factory=dict)
    frag_counts: Dict[int, int] = field(default_factory=dict)

    def add_fragment(
        self,
        *,
        nal_index: int,
        frag_index: int,
        frag_count: int,
        payload: bytes,
        now_ms: float,
    ) -> None:
        self.updated_at_ms = now_ms
        self.fragments.setdefault(nal_index, {})[frag_index] = payload
        if nal_index not in self.frag_counts:
            self.frag_counts[nal_index] = frag_count
        else:
            self.frag_counts[nal_index] = max(self.frag_counts[nal_index], frag_count)

    def is_complete(self) -> bool:
        if self.nal_count <= 0:
            return False
        if len(self.fragments) < self.nal_count:
            return False
        for nal_index in range(self.nal_count):
            if nal_index not in self.fragments:
                return False
            expected = self.frag_counts.get(nal_index)
            if expected is None:
                return False
            have = self.fragments[nal_index]
            if len(have) < expected:
                return False
            for frag_index in range(expected):
                if frag_index not in have:
                    return False
        return True

    def to_annexb(self) -> bytes:
        out = bytearray()
        for nal_index in range(self.nal_count):
            frag_count = self.frag_counts[nal_index]
            nal_payload = bytearray()
            for frag_index in range(frag_count):
                nal_payload.extend(self.fragments[nal_index][frag_index])
            out.extend(b"\x00\x00\x00\x01")
            out.extend(nal_payload)
        return bytes(out)


def split_h264_nal_units(payload: bytes) -> list[bytes]:
    """Split an H.264 access unit into NAL payloads.

    Supports Annex-B and AVCC (4-byte length-prefixed) bitstreams.
    """

    if not payload:
        return []

    # Annex-B path.
    starts: list[tuple[int, int]] = []
    i = 0
    end = len(payload)
    while i + 3 < end:
        if payload[i : i + 3] == b"\x00\x00\x01":
            starts.append((i, 3))
            i += 3
            continue
        if i + 4 < end and payload[i : i + 4] == b"\x00\x00\x00\x01":
            starts.append((i, 4))
            i += 4
            continue
        i += 1

    if starts:
        nal_units: list[bytes] = []
        for idx, (start, prefix_len) in enumerate(starts):
            nal_start = start + prefix_len
            nal_end = starts[idx + 1][0] if idx + 1 < len(starts) else end
            nal = payload[nal_start:nal_end]
            if nal:
                nal_units.append(nal)
        if nal_units:
            return nal_units

    # AVCC path with 4-byte big-endian NAL lengths.
    cursor = 0
    avcc_nals: list[bytes] = []
    while cursor + 4 <= end:
        nal_len = int.from_bytes(payload[cursor : cursor + 4], "big", signed=False)
        cursor += 4
        if nal_len <= 0:
            return [payload]
        next_cursor = cursor + nal_len
        if next_cursor > end:
            return [payload]
        avcc_nals.append(payload[cursor:next_cursor])
        cursor = next_cursor
    if avcc_nals and cursor == end:
        return avcc_nals

    # Fallback: return the payload as one unit.
    return [payload]


class VideoEncoder:
    """Low-latency H.264 encoder with hardware-preferred codec selection.

    Required low-latency settings are applied whenever supported:
    - tune=zerolatency
    - bframes=0
    - intra-refresh=1
    - sliced-threads=1
    """

    def __init__(self, config: EncoderConfig):
        self.config = config
        self._active_codec_name: Optional[str] = None
        self._ctx: Optional[av.codec.context.CodecContext] = None
        self._bitrate_bps = int(config.initial_bitrate_bps)
        self._crf = int(config.initial_crf)
        self._open_encoder()

    @property
    def codec_name(self) -> str:
        if not self._active_codec_name:
            raise RuntimeError("encoder is not initialized")
        return self._active_codec_name

    @property
    def bitrate_bps(self) -> int:
        return self._bitrate_bps

    @property
    def crf(self) -> int:
        return self._crf

    def close(self) -> None:
        if self._ctx is None:
            return
        try:
            self._ctx.encode(None)
        except Exception:  # pragma: no cover - close should be best effort
            pass
        self._ctx = None

    def set_rate_control(self, *, bitrate_bps: Optional[int] = None, crf: Optional[int] = None) -> None:
        """Apply ABR updates to bitrate and/or CRF.

        PyAV does not reliably support runtime CRF updates on an open context,
        so the context is rebuilt when any RC parameter changes.
        """

        next_bitrate = self._bitrate_bps if bitrate_bps is None else int(max(1, bitrate_bps))
        next_crf = self._crf if crf is None else int(min(51, max(0, crf)))
        if next_bitrate == self._bitrate_bps and next_crf == self._crf:
            return
        self._bitrate_bps = next_bitrate
        self._crf = next_crf
        self._open_encoder()

    def encode_frame(self, frame_rgb: np.ndarray, frame_id: int) -> EncodedFrame:
        if self._ctx is None:
            raise RuntimeError("encoder context is not initialized")

        if frame_rgb.ndim != 3 or frame_rgb.shape[2] not in (3, 4):
            raise ValueError("frame_rgb must have shape (H, W, 3|4)")
        if frame_rgb.shape[0] != self.config.height or frame_rgb.shape[1] != self.config.width:
            raise ValueError(
                f"frame shape {frame_rgb.shape[:2]} does not match "
                f"encoder {(self.config.height, self.config.width)}"
            )

        if frame_rgb.shape[2] == 4:
            frame_rgb = frame_rgb[:, :, :3]
        if frame_rgb.dtype != np.uint8:
            frame_rgb = np.clip(frame_rgb, 0, 255).astype(np.uint8)

        video_frame = av.VideoFrame.from_ndarray(frame_rgb, format="rgb24")
        video_frame.pts = frame_id

        started = time.perf_counter()
        packets = self._ctx.encode(video_frame)
        encode_ms = (time.perf_counter() - started) * 1000.0

        nal_units: list[bytes] = []
        total_bytes = 0
        is_keyframe = False

        for packet in packets:
            raw = bytes(packet)
            if not raw:
                continue
            total_bytes += len(raw)
            nal_units.extend(split_h264_nal_units(raw))
            is_keyframe = is_keyframe or bool(getattr(packet, "is_keyframe", False))

        return EncodedFrame(
            frame_id=frame_id,
            nal_units=nal_units,
            is_keyframe=is_keyframe,
            total_bytes=total_bytes,
            encode_ms=encode_ms,
            codec_name=self.codec_name,
        )

    def _codec_candidates(self) -> list[str]:
        if self.config.codec_candidates:
            return [c for c in self.config.codec_candidates if c]

        system_name = platform.system().lower()
        if not self.config.prefer_hardware:
            return ["libx264", "h264"]

        if system_name == "darwin":
            return ["h264_videotoolbox", "h264_nvenc", "libx264", "h264"]
        return ["h264_nvenc", "libx264", "h264"]

    def _build_option_candidates(self, codec_name: str) -> list[dict[str, str]]:
        common_low_latency = {
            "bf": "0",
            "bframes": "0",
            "intra-refresh": "1",
            "sliced-threads": "1",
            "repeat-headers": "1",
        }

        if codec_name == "libx264":
            x264_params = (
                "bframes=0:"
                "intra-refresh=1:"
                "sliced-threads=1:"
                "sync-lookahead=0:"
                "rc-lookahead=0:"
                "scenecut=0:"
                "open-gop=0:"
                "repeat-headers=1:"
                "annexb=1"
            )
            base = {
                "preset": "ultrafast",
                "tune": "zerolatency",
                "x264-params": x264_params,
                "crf": str(self._crf),
            }
        elif codec_name == "h264_nvenc":
            base = {
                "preset": "p1",
                "tune": "ull",
                "zerolatency": "1",
                "delay": "0",
                "rc-lookahead": "0",
                "bf": "0",
                "intra-refresh": "1",
                "repeat-headers": "1",
                "forced-idr": "0",
                "cq": str(self._crf),
            }
        elif codec_name == "h264_videotoolbox":
            base = {
                "realtime": "1",
                "allow_sw": "1",
                "bf": "0",
                "intra-refresh": "1",
                "repeat-headers": "1",
            }
        elif codec_name == "h264":
            # Generic ffmpeg "h264" may map to libopenh264 where x264-like
            # options such as "crf" or "tune" are invalid.
            base = {
                "bf": "0",
                "intra-refresh": "1",
                "repeat-headers": "1",
                "sliced-threads": "1",
            }
        else:
            base = {
                "tune": "zerolatency",
                "crf": str(self._crf),
                "annexb": "1",
                **common_low_latency,
            }

        # Try strict low-latency options first, then progressively relax.
        relaxed = {k: v for k, v in base.items() if k not in {"intra-refresh", "sliced-threads"}}
        minimal = {k: v for k, v in relaxed.items() if k not in {"repeat-headers", "delay", "forced-idr"}}

        options_by_priority: list[dict[str, str]] = [base, relaxed, minimal, {}]
        deduped: list[dict[str, str]] = []
        seen: set[tuple[tuple[str, str], ...]] = set()
        for opts in options_by_priority:
            key = tuple(sorted(opts.items()))
            if key in seen:
                continue
            seen.add(key)
            deduped.append(opts)
        return deduped

    def _open_encoder(self) -> None:
        if self._ctx is not None:
            try:
                self._ctx.encode(None)
            except Exception:
                pass
            self._ctx = None

        last_error: Optional[Exception] = None
        for codec_name in self._codec_candidates():
            for options in self._build_option_candidates(codec_name):
                try:
                    ctx = av.CodecContext.create(codec_name, "w")
                    ctx.width = self.config.width
                    ctx.height = self.config.height
                    ctx.pix_fmt = self.config.pix_fmt
                    ctx.time_base = Fraction(1, self.config.fps)
                    ctx.framerate = Fraction(self.config.fps, 1)
                    ctx.bit_rate = self._bitrate_bps
                    if self.config.thread_count > 0:
                        ctx.thread_count = self.config.thread_count
                    try:
                        ctx.thread_type = "SLICE"
                    except Exception:
                        pass
                    try:
                        ctx.max_b_frames = 0
                    except Exception:
                        pass
                    try:
                        ctx.gop_size = 999_999  # PIR-focused operation, avoid frequent IDRs.
                    except Exception:
                        pass

                    ctx.options = options
                    ctx.open()
                    self._ctx = ctx
                    self._active_codec_name = codec_name
                    LOGGER.info("Opened encoder codec=%s options=%s", codec_name, options)
                    return
                except Exception as exc:  # pragma: no cover - depends on local ffmpeg build
                    last_error = exc
                    LOGGER.debug("Failed encoder codec=%s options=%s error=%s", codec_name, options, exc)

        if last_error is None:
            raise RuntimeError("unable to initialize encoder")
        raise RuntimeError(f"unable to initialize encoder: {last_error}") from last_error


class StreamManager:
    """Packetize encoded H.264 NAL units for per-frame QUIC delivery."""

    MAGIC = 0x54
    VERSION = 1
    FLAG_KEYFRAME = 1 << 0
    HEADER_STRUCT = struct.Struct("!BBIHHHHBB")

    def __init__(self, encoder: VideoEncoder, mtu_bytes: int = 1500):
        if mtu_bytes <= self.HEADER_STRUCT.size:
            raise ValueError("mtu_bytes is too small for packet header")
        self.encoder = encoder
        self.mtu_bytes = mtu_bytes

    @property
    def max_payload_bytes(self) -> int:
        return self.mtu_bytes - self.HEADER_STRUCT.size

    def encode_frame_to_quic_packets(self, frame_rgb: np.ndarray, frame_id: int) -> tuple[EncodedFrame, list[bytes]]:
        encoded = self.encoder.encode_frame(frame_rgb, frame_id)
        packets = self.packetize_encoded_frame(encoded)
        return encoded, packets

    def emit_frame(self, frame_rgb: np.ndarray, frame_id: int, send_packet: Callable[[bytes], None]) -> EncodedFrame:
        """Encode and emit packets immediately, one packet at a time."""

        encoded, packets = self.encode_frame_to_quic_packets(frame_rgb, frame_id)
        for packet in packets:
            send_packet(packet)
        return encoded

    def packetize_encoded_frame(self, encoded: EncodedFrame) -> list[bytes]:
        packets: list[bytes] = []
        nal_count = len(encoded.nal_units)
        if nal_count == 0:
            return packets

        flags = self.FLAG_KEYFRAME if encoded.is_keyframe else 0
        max_payload = self.max_payload_bytes

        for nal_index, nal in enumerate(encoded.nal_units):
            if not nal:
                continue
            frag_count = (len(nal) + max_payload - 1) // max_payload
            for frag_index in range(frag_count):
                start = frag_index * max_payload
                end = min(start + max_payload, len(nal))
                frag_payload = nal[start:end]
                header = self.HEADER_STRUCT.pack(
                    self.MAGIC,
                    self.VERSION,
                    encoded.frame_id,
                    nal_index,
                    nal_count,
                    frag_index,
                    frag_count,
                    flags,
                    0,
                )
                packets.append(header + frag_payload)
        return packets

    @classmethod
    def parse_packet(cls, packet: bytes) -> PacketMetadata:
        if len(packet) < cls.HEADER_STRUCT.size:
            raise ValueError("packet too short")
        (
            magic,
            version,
            frame_id,
            nal_index,
            nal_count,
            frag_index,
            frag_count,
            flags,
            _reserved,
        ) = cls.HEADER_STRUCT.unpack(packet[: cls.HEADER_STRUCT.size])

        if magic != cls.MAGIC:
            raise ValueError(f"invalid packet magic: {magic}")
        if version != cls.VERSION:
            raise ValueError(f"unsupported packet version: {version}")
        if nal_count <= 0:
            raise ValueError("invalid nal_count")
        if frag_count <= 0:
            raise ValueError("invalid frag_count")

        payload = packet[cls.HEADER_STRUCT.size :]
        return PacketMetadata(
            frame_id=frame_id,
            nal_index=nal_index,
            nal_count=nal_count,
            frag_index=frag_index,
            frag_count=frag_count,
            flags=flags,
            payload=payload,
        )


class VideoDecoder:
    """Real-time decoder with per-frame NAL reassembly and stale drop policy."""

    def __init__(
        self,
        *,
        frame_timeout_ms: float = 80.0,
        codec_candidates: Optional[Sequence[str]] = None,
        prefer_hardware: bool = True,
    ):
        self.frame_timeout_ms = float(frame_timeout_ms)
        self._assemblies: Dict[int, _FrameAssembly] = {}
        self._latest_decoded_frame_id = -1
        self._decoder_name: Optional[str] = None
        self._decoder_ctx: Optional[av.codec.context.CodecContext] = None
        self._open_decoder(codec_candidates=codec_candidates, prefer_hardware=prefer_hardware)

    @property
    def decoder_name(self) -> str:
        if self._decoder_name is None:
            raise RuntimeError("decoder is not initialized")
        return self._decoder_name

    def close(self) -> None:
        self._decoder_ctx = None

    def ingest_quic_packet(self, packet: bytes) -> Optional[DecodedFrame]:
        meta = StreamManager.parse_packet(packet)
        now_ms = time.monotonic() * 1000.0
        self._drop_stale(now_ms)

        if meta.frame_id <= self._latest_decoded_frame_id:
            return None

        assembly = self._assemblies.get(meta.frame_id)
        if assembly is None:
            assembly = _FrameAssembly(
                frame_id=meta.frame_id,
                nal_count=meta.nal_count,
                is_keyframe=bool(meta.flags & StreamManager.FLAG_KEYFRAME),
                created_at_ms=now_ms,
                updated_at_ms=now_ms,
            )
            self._assemblies[meta.frame_id] = assembly

        assembly.add_fragment(
            nal_index=meta.nal_index,
            frag_index=meta.frag_index,
            frag_count=meta.frag_count,
            payload=meta.payload,
            now_ms=now_ms,
        )

        if not assembly.is_complete():
            return None

        access_unit = assembly.to_annexb()
        del self._assemblies[meta.frame_id]
        decoded = self._decode_access_unit(frame_id=meta.frame_id, access_unit=access_unit)
        if decoded is not None:
            self._latest_decoded_frame_id = max(self._latest_decoded_frame_id, decoded.frame_id)
        return decoded

    def ingest_quic_packets(self, packets: Iterable[bytes]) -> list[DecodedFrame]:
        decoded_frames: list[DecodedFrame] = []
        for packet in packets:
            decoded = self.ingest_quic_packet(packet)
            if decoded is not None:
                decoded_frames.append(decoded)
        return decoded_frames

    def _decode_access_unit(self, *, frame_id: int, access_unit: bytes) -> Optional[DecodedFrame]:
        if self._decoder_ctx is None:
            raise RuntimeError("decoder context is not initialized")
        if not access_unit:
            return None

        started = time.perf_counter()
        try:
            packet = av.Packet(access_unit)
            frames = self._decoder_ctx.decode(packet)
        except Exception as exc:  # pragma: no cover - depends on decode backend
            LOGGER.debug("Decode failed for frame_id=%s error=%s", frame_id, exc)
            return None

        decode_ms = (time.perf_counter() - started) * 1000.0
        if not frames:
            return None

        frame = frames[-1].to_ndarray(format="rgb24")
        return DecodedFrame(
            frame_id=frame_id,
            frame_rgb=frame,
            decode_ms=decode_ms,
            codec_name=self.decoder_name,
        )

    def _drop_stale(self, now_ms: float) -> None:
        stale_ids = [
            frame_id
            for frame_id, assembly in self._assemblies.items()
            if (now_ms - assembly.updated_at_ms) > self.frame_timeout_ms
        ]
        for frame_id in stale_ids:
            del self._assemblies[frame_id]

    def _default_decoder_candidates(self, prefer_hardware: bool) -> list[str]:
        if not prefer_hardware:
            return ["h264"]
        system_name = platform.system().lower()
        if system_name == "darwin":
            return ["h264_videotoolbox", "h264"]
        if system_name == "linux":
            return ["h264_cuvid", "h264"]
        return ["h264"]

    def _open_decoder(self, *, codec_candidates: Optional[Sequence[str]], prefer_hardware: bool) -> None:
        candidates = list(codec_candidates) if codec_candidates else self._default_decoder_candidates(prefer_hardware)
        last_error: Optional[Exception] = None

        for codec_name in candidates:
            try:
                ctx = av.CodecContext.create(codec_name, "r")
                try:
                    ctx.thread_type = "SLICE"
                except Exception:
                    pass
                ctx.open()
                self._decoder_ctx = ctx
                self._decoder_name = codec_name
                LOGGER.info("Opened decoder codec=%s", codec_name)
                return
            except Exception as exc:  # pragma: no cover - depends on local ffmpeg build
                last_error = exc
                LOGGER.debug("Failed decoder codec=%s error=%s", codec_name, exc)

        if last_error is None:
            raise RuntimeError("unable to initialize decoder")
        raise RuntimeError(f"unable to initialize decoder: {last_error}") from last_error


class LatencyAwareAbrController:
    """ABR controller that adapts H.264 bitrate/CRF for <100ms MTP targets.

    This controller explicitly accounts for render, encode, network, and decode
    timing, then adjusts encoder bitrate and CRF instead of JPEG quality.
    """

    def __init__(
        self,
        *,
        target_mtp_ms: float = 100.0,
        min_bitrate_bps: int = 500_000,
        max_bitrate_bps: int = 15_000_000,
        min_crf: int = 17,
        max_crf: int = 38,
        initial_bitrate_bps: int = 4_000_000,
        initial_crf: int = 25,
        update_interval_frames: int = 3,
        smoothing: float = 0.2,
        loss_threshold: float = 0.03,
    ):
        self.target_mtp_ms = float(target_mtp_ms)
        self.min_bitrate_bps = int(min_bitrate_bps)
        self.max_bitrate_bps = int(max_bitrate_bps)
        self.min_crf = int(min_crf)
        self.max_crf = int(max_crf)
        self.current_bitrate_bps = int(initial_bitrate_bps)
        self.current_crf = int(initial_crf)
        self.update_interval_frames = max(1, int(update_interval_frames))
        self.smoothing = float(min(max(smoothing, 0.01), 1.0))
        self.loss_threshold = float(max(0.0, loss_threshold))

        self._frame_counter = 0
        self._mtp_ewma_ms: Optional[float] = None
        self._throughput_ewma_bps: Optional[float] = None
        self._loss_ewma: Optional[float] = None

    def observe(self, sample: AbrSample, encoder: Optional[VideoEncoder] = None) -> Optional[AbrDecision]:
        mtp_ms = max(0.0, sample.render_ms + sample.encode_ms + sample.network_ms + sample.decode_ms)
        throughput_bps = (sample.frame_bytes * 8.0) / max(sample.network_ms / 1000.0, 1e-3)
        loss = min(max(sample.packet_loss_ratio, 0.0), 1.0)

        self._mtp_ewma_ms = self._ewma(self._mtp_ewma_ms, mtp_ms)
        self._throughput_ewma_bps = self._ewma(self._throughput_ewma_bps, throughput_bps)
        self._loss_ewma = self._ewma(self._loss_ewma, loss)
        self._frame_counter += 1

        over_budget = self._mtp_ewma_ms is not None and self._mtp_ewma_ms > self.target_mtp_ms
        hard_loss = self._loss_ewma is not None and self._loss_ewma > self.loss_threshold
        should_update = (
            self._frame_counter % self.update_interval_frames == 0
            or over_budget
            or hard_loss
        )
        if not should_update:
            return None

        next_bitrate = self.current_bitrate_bps
        next_crf = self.current_crf
        reason = "stable"

        if hard_loss or over_budget:
            next_bitrate = int(self.current_bitrate_bps * 0.85)
            next_crf = self.current_crf + 1
            reason = "latency/loss pressure"
        elif self._mtp_ewma_ms is not None and self._mtp_ewma_ms < self.target_mtp_ms * 0.75:
            next_bitrate = int(self.current_bitrate_bps * 1.08)
            next_crf = self.current_crf - 1
            reason = "latency headroom"

        if self._throughput_ewma_bps is not None:
            fair_rate = int(self._throughput_ewma_bps * 0.85)
            if hard_loss or over_budget:
                # Under latency pressure, throughput guidance can only cap bitrate
                # downward, never pull it upward.
                next_bitrate = min(next_bitrate, fair_rate)
            else:
                next_bitrate = int(0.7 * next_bitrate + 0.3 * fair_rate)

        next_bitrate = max(self.min_bitrate_bps, min(self.max_bitrate_bps, next_bitrate))
        next_crf = max(self.min_crf, min(self.max_crf, next_crf))

        if next_bitrate == self.current_bitrate_bps and next_crf == self.current_crf:
            return None

        self.current_bitrate_bps = next_bitrate
        self.current_crf = next_crf
        decision = AbrDecision(bitrate_bps=next_bitrate, crf=next_crf, reason=reason)
        if encoder is not None:
            encoder.set_rate_control(bitrate_bps=next_bitrate, crf=next_crf)
        return decision

    def _ewma(self, previous: Optional[float], current: float) -> float:
        if previous is None:
            return current
        return (1.0 - self.smoothing) * previous + self.smoothing * current
