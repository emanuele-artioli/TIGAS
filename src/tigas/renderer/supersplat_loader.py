"""PLY loaders for headless 3DGS rendering.

This module supports both:

1. SuperSplat compressed chunked PLY (`element chunk`, packed uint fields)
2. Standard Graphdeco-style 3DGS PLY (`x,y,z,f_dc_*,opacity,scale_*,rot_*`)
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path

import numpy as np

_SH_C0 = 0.28209479177387814
_PLY_TYPE_TO_NUMPY = {
    "char": np.dtype("i1"),
    "uchar": np.dtype("u1"),
    "short": np.dtype("i2"),
    "ushort": np.dtype("u2"),
    "int": np.dtype("i4"),
    "uint": np.dtype("u4"),
    "float": np.dtype("f4"),
    "double": np.dtype("f8"),
}

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
    scale_xyz: np.ndarray
    rgb: np.ndarray
    opacity: np.ndarray
    center: np.ndarray
    radius: float
    point_count: int
    chunk_count: int
    encoding: str
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


def _parse_vertex_properties(header_lines: list[str]) -> list[tuple[str, str]]:
    """Return vertex properties as (type_name, property_name)."""
    in_vertex_element = False
    properties: list[tuple[str, str]] = []

    for line in header_lines:
        if line.startswith("element "):
            in_vertex_element = line.startswith("element vertex ")
            continue

        if not in_vertex_element:
            continue

        if not line.startswith("property "):
            continue

        parts = line.split()
        if len(parts) != 3:
            raise ValueError(f"Unsupported vertex property declaration: {line}")
        _, type_name, prop_name = parts
        if type_name == "list":
            raise ValueError("List properties are not supported in vertex element decoding.")
        properties.append((type_name, prop_name))

    if not properties:
        raise ValueError("No vertex properties found in PLY header.")
    return properties


def _sample_indices(total_count: int, max_points: int | None) -> np.ndarray:
    if max_points is None or max_points <= 0 or max_points >= total_count:
        return np.arange(total_count, dtype=np.int64)
    return np.linspace(0, total_count - 1, max_points, dtype=np.int64)


def _sigmoid(x: np.ndarray) -> np.ndarray:
    x_clip = np.clip(x, -60.0, 60.0)
    return 1.0 / (1.0 + np.exp(-x_clip))


def _build_decoded_cloud(
    *,
    xyz: np.ndarray,
    scale_xyz: np.ndarray,
    rgb: np.ndarray,
    opacity: np.ndarray,
    chunk_count: int,
    encoding: str,
    source_path: str,
) -> DecodedPointCloud:
    center = xyz.mean(axis=0, dtype=np.float64).astype(np.float32)
    radius = float(np.linalg.norm(xyz - center[None, :], axis=1).max())
    return DecodedPointCloud(
        xyz=xyz.astype(np.float32, copy=False),
        scale_xyz=scale_xyz.astype(np.float32, copy=False),
        rgb=rgb.astype(np.uint8, copy=False),
        opacity=opacity.astype(np.float32, copy=False),
        center=center,
        radius=radius,
        point_count=int(xyz.shape[0]),
        chunk_count=chunk_count,
        encoding=encoding,
        source_path=source_path,
    )


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
    vertex_indices = _sample_indices(vertex_count, max_points)
    chunk_indices = np.minimum(vertex_indices // chunk_stride, chunk_count - 1)

    vertices = vertices[vertex_indices]

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

    packed_scale = vertices["packed_scale"]
    q_sx = (packed_scale & 0x3FF).astype(np.float32)
    q_sy = ((packed_scale >> 10) & 0x3FF).astype(np.float32)
    q_sz = ((packed_scale >> 20) & 0x3FF).astype(np.float32)

    raw_scale_x = chunks["min_scale_x"][chunk_indices] + (
        (chunks["max_scale_x"][chunk_indices] - chunks["min_scale_x"][chunk_indices])
        * (q_sx / 1023.0)
    )
    raw_scale_y = chunks["min_scale_y"][chunk_indices] + (
        (chunks["max_scale_y"][chunk_indices] - chunks["min_scale_y"][chunk_indices])
        * (q_sy / 1023.0)
    )
    raw_scale_z = chunks["min_scale_z"][chunk_indices] + (
        (chunks["max_scale_z"][chunk_indices] - chunks["min_scale_z"][chunk_indices])
        * (q_sz / 1023.0)
    )
    raw_scale = np.stack((raw_scale_x, raw_scale_y, raw_scale_z), axis=1)
    if float(np.nanpercentile(raw_scale, 95)) <= 2.5 and float(np.nanpercentile(raw_scale, 5)) < 0.0:
        scale_xyz = np.exp(np.clip(raw_scale, -12.0, 8.0))
    else:
        scale_xyz = np.clip(raw_scale, 1e-5, None)

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
    rgb = np.round(rgb_float * 255.0).astype(np.uint8)

    return _build_decoded_cloud(
        xyz=xyz,
        scale_xyz=scale_xyz,
        rgb=rgb,
        opacity=opacity,
        chunk_count=chunk_count,
        encoding="supersplat_compressed",
        source_path=str(path),
    )


def load_standard_3dgs_ply(
    file_path: str,
    max_points: int | None = None,
) -> DecodedPointCloud:
    """Decode a standard Graphdeco 3DGS binary PLY file."""
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"Point cloud file not found: {file_path}")

    with path.open("rb") as handle:
        chunk_count, vertex_count, data_offset, header_lines = _read_header(handle)
    if vertex_count <= 0:
        raise ValueError("Invalid PLY header: `element vertex` count is zero.")

    properties = _parse_vertex_properties(header_lines)
    dtype_fields: list[tuple[str, np.dtype]] = []
    for type_name, prop_name in properties:
        base_dtype = _PLY_TYPE_TO_NUMPY.get(type_name)
        if base_dtype is None:
            raise ValueError(f"Unsupported PLY property type: {type_name}")
        dtype_fields.append((prop_name, base_dtype.newbyteorder("<")))
    vertex_dtype = np.dtype(dtype_fields)

    sample_indices = _sample_indices(vertex_count, max_points)
    vertex_memmap = np.memmap(
        path,
        dtype=vertex_dtype,
        mode="r",
        offset=data_offset,
        shape=(vertex_count,),
    )
    vertices = np.asarray(vertex_memmap[sample_indices])
    del vertex_memmap

    xyz = np.stack(
        (
            vertices["x"].astype(np.float32),
            vertices["y"].astype(np.float32),
            vertices["z"].astype(np.float32),
        ),
        axis=1,
    )

    names = set(vertices.dtype.names or ())
    if {"f_dc_0", "f_dc_1", "f_dc_2"}.issubset(names):
        coeff = np.stack(
            (
                vertices["f_dc_0"].astype(np.float32),
                vertices["f_dc_1"].astype(np.float32),
                vertices["f_dc_2"].astype(np.float32),
            ),
            axis=1,
        )
        rgb_float = np.clip(0.5 + _SH_C0 * coeff, 0.0, 1.0)
    elif {"red", "green", "blue"}.issubset(names):
        rgb_float = np.stack(
            (
                vertices["red"].astype(np.float32),
                vertices["green"].astype(np.float32),
                vertices["blue"].astype(np.float32),
            ),
            axis=1,
        )
        if rgb_float.max() > 1.0:
            rgb_float = np.clip(rgb_float / 255.0, 0.0, 1.0)
        else:
            rgb_float = np.clip(rgb_float, 0.0, 1.0)
    else:
        rgb_float = np.ones((xyz.shape[0], 3), dtype=np.float32)
    rgb = np.round(rgb_float * 255.0).astype(np.uint8)

    if "opacity" in names:
        opacity = _sigmoid(vertices["opacity"].astype(np.float32)).astype(np.float32)
    elif "alpha" in names:
        alpha = vertices["alpha"].astype(np.float32)
        opacity = np.clip(alpha / (255.0 if alpha.max() > 1.0 else 1.0), 0.0, 1.0)
    else:
        opacity = np.ones((xyz.shape[0],), dtype=np.float32)

    if {"scale_0", "scale_1", "scale_2"}.issubset(names):
        raw_scale = np.stack(
            (
                vertices["scale_0"].astype(np.float32),
                vertices["scale_1"].astype(np.float32),
                vertices["scale_2"].astype(np.float32),
            ),
            axis=1,
        )
        scale_xyz = np.exp(np.clip(raw_scale, -12.0, 8.0))
    else:
        scale_xyz = np.full((xyz.shape[0], 3), 0.01, dtype=np.float32)

    return _build_decoded_cloud(
        xyz=xyz,
        scale_xyz=scale_xyz,
        rgb=rgb,
        opacity=opacity,
        chunk_count=chunk_count,
        encoding="standard_3dgs",
        source_path=str(path),
    )


def load_any_3dgs_ply(file_path: str, max_points: int | None = None) -> DecodedPointCloud:
    """Load either compressed SuperSplat or standard 3DGS PLY based on header."""
    path = Path(file_path)
    with path.open("rb") as handle:
        chunk_count, _, _, header_lines = _read_header(handle)

    if chunk_count > 0 and any("packed_position" in line for line in header_lines):
        return load_supersplat_compressed_ply(file_path=file_path, max_points=max_points)
    return load_standard_3dgs_ply(file_path=file_path, max_points=max_points)
