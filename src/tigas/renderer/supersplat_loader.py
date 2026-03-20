"""SuperSplat compressed PLY loader.

The target dataset for headless experiments stores splats in a chunked and
packed representation (`element chunk`, `packed_position`, `packed_color`).
This loader decodes enough geometry and color information for deterministic
offline rendering and evaluation.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path

import numpy as np

_SH_C0 = 0.28209479177387814

_CHUNK_DTYPE = np.dtype(
    [
        ("min_x", "<f4"),
        ("min_y", "<f4"),
        ("min_z", "<f4"),
        ("max_x", "<f4"),
        ("max_y", "<f4"),
        ("max_z", "<f4"),
        ("min_scale_x", "<f4"),
        ("min_scale_y", "<f4"),
        ("min_scale_z", "<f4"),
        ("max_scale_x", "<f4"),
        ("max_scale_y", "<f4"),
        ("max_scale_z", "<f4"),
        ("min_r", "<f4"),
        ("min_g", "<f4"),
        ("min_b", "<f4"),
        ("max_r", "<f4"),
        ("max_g", "<f4"),
        ("max_b", "<f4"),
    ]
)

_VERTEX_DTYPE = np.dtype(
    [
        ("packed_position", "<u4"),
        ("packed_rotation", "<u4"),
        ("packed_scale", "<u4"),
        ("packed_color", "<u4"),
    ]
)


@dataclass(slots=True)
class DecodedPointCloud:
    """Decoded subset used by the headless CPU backend."""

    xyz: np.ndarray
    rgb: np.ndarray
    opacity: np.ndarray
    center: np.ndarray
    radius: float
    point_count: int
    chunk_count: int
    source_path: str


def _read_header(handle) -> tuple[int, int, int, list[str]]:
    """Return chunk count, vertex count, byte offset, and raw header lines."""
    header_lines: list[str] = []
    while True:
        line = handle.readline()
        if not line:
            break
        decoded = line.decode("ascii", errors="ignore").rstrip("\n")
        header_lines.append(decoded)
        if line.strip() == b"end_header":
            break

    chunk_count = 0
    vertex_count = 0
    for header_line in header_lines:
        if header_line.startswith("element chunk "):
            chunk_count = int(header_line.split()[-1])
        elif header_line.startswith("element vertex "):
            vertex_count = int(header_line.split()[-1])

    byte_offset = sum(len((line + "\n").encode("ascii")) for line in header_lines)
    return chunk_count, vertex_count, byte_offset, header_lines


def load_supersplat_compressed_ply(
    file_path: str,
    max_points: int | None = None,
) -> DecodedPointCloud:
    """Decode SuperSplat compressed PLY into CPU-renderable arrays.

    The decoder intentionally focuses on packed position and packed color fields
    which are sufficient for headless quality and performance experiments.
    """
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"Point cloud file not found: {file_path}")

    with path.open("rb") as handle:
        chunk_count, vertex_count, data_offset, header_lines = _read_header(handle)
        if chunk_count <= 0:
            raise ValueError(
                "Compressed SuperSplat file is required. Missing `element chunk` in header."
            )
        if vertex_count <= 0:
            raise ValueError("Invalid PLY header: `element vertex` count is zero.")
        if not any("packed_position" in line for line in header_lines):
            raise ValueError("PLY file is missing `packed_position` property.")

        handle.seek(data_offset)
        chunks = np.fromfile(handle, dtype=_CHUNK_DTYPE, count=chunk_count)
        vertices = np.fromfile(handle, dtype=_VERTEX_DTYPE, count=vertex_count)

    if chunks.shape[0] != chunk_count:
        raise ValueError(
            f"Could not read all chunk records (expected {chunk_count}, got {chunks.shape[0]})."
        )
    if vertices.shape[0] != vertex_count:
        raise ValueError(
            f"Could not read all vertex records (expected {vertex_count}, got {vertices.shape[0]})."
        )

    chunk_stride = max(1, int(math.ceil(vertex_count / chunk_count)))
    vertex_indices = np.arange(vertex_count, dtype=np.int64)
    chunk_indices = np.minimum(vertex_indices // chunk_stride, chunk_count - 1)

    packed_position = vertices["packed_position"]
    qx = (packed_position & 0x3FF).astype(np.float32)
    qy = ((packed_position >> 10) & 0x3FF).astype(np.float32)
    qz = ((packed_position >> 20) & 0x3FF).astype(np.float32)

    min_x = chunks["min_x"][chunk_indices]
    max_x = chunks["max_x"][chunk_indices]
    min_y = chunks["min_y"][chunk_indices]
    max_y = chunks["max_y"][chunk_indices]
    min_z = chunks["min_z"][chunk_indices]
    max_z = chunks["max_z"][chunk_indices]

    x = min_x + (max_x - min_x) * (qx / 1023.0)
    y = min_y + (max_y - min_y) * (qy / 1023.0)
    z = min_z + (max_z - min_z) * (qz / 1023.0)
    xyz = np.stack((x, y, z), axis=1).astype(np.float32)

    packed_color = vertices["packed_color"]
    q_r = (packed_color & 0xFF).astype(np.float32)
    q_g = ((packed_color >> 8) & 0xFF).astype(np.float32)
    q_b = ((packed_color >> 16) & 0xFF).astype(np.float32)
    q_a = ((packed_color >> 24) & 0xFF).astype(np.float32)

    coeff_r = chunks["min_r"][chunk_indices] + (
        (chunks["max_r"][chunk_indices] - chunks["min_r"][chunk_indices]) * (q_r / 255.0)
    )
    coeff_g = chunks["min_g"][chunk_indices] + (
        (chunks["max_g"][chunk_indices] - chunks["min_g"][chunk_indices]) * (q_g / 255.0)
    )
    coeff_b = chunks["min_b"][chunk_indices] + (
        (chunks["max_b"][chunk_indices] - chunks["min_b"][chunk_indices]) * (q_b / 255.0)
    )

    rgb_float = np.stack(
        (
            np.clip(0.5 + _SH_C0 * coeff_r, 0.0, 1.0),
            np.clip(0.5 + _SH_C0 * coeff_g, 0.0, 1.0),
            np.clip(0.5 + _SH_C0 * coeff_b, 0.0, 1.0),
        ),
        axis=1,
    )

    opacity = np.clip(q_a / 255.0, 0.0, 1.0).astype(np.float32)
    rgb = np.round(rgb_float * opacity[:, None] * 255.0).astype(np.uint8)

    if max_points is not None and max_points > 0 and xyz.shape[0] > max_points:
        sample_indices = np.linspace(0, xyz.shape[0] - 1, max_points, dtype=np.int64)
        xyz = xyz[sample_indices]
        rgb = rgb[sample_indices]
        opacity = opacity[sample_indices]

    center = xyz.mean(axis=0, dtype=np.float64).astype(np.float32)
    radius = float(np.linalg.norm(xyz - center[None, :], axis=1).max())

    return DecodedPointCloud(
        xyz=xyz,
        rgb=rgb,
        opacity=opacity,
        center=center,
        radius=radius,
        point_count=int(xyz.shape[0]),
        chunk_count=chunk_count,
        source_path=str(path),
    )
