"""Standard 3DGS PLY loader tests."""

import struct

from tigas.renderer.supersplat_loader import load_any_3dgs_ply, load_standard_3dgs_ply


def test_load_standard_3dgs_ply(tmp_path) -> None:
    ply_path = tmp_path / "mini_standard.ply"
    header = "\n".join(
        [
            "ply",
            "format binary_little_endian 1.0",
            "element vertex 2",
            "property float x",
            "property float y",
            "property float z",
            "property float nx",
            "property float ny",
            "property float nz",
            "property float f_dc_0",
            "property float f_dc_1",
            "property float f_dc_2",
            "property float opacity",
            "property float scale_0",
            "property float scale_1",
            "property float scale_2",
            "property float rot_0",
            "property float rot_1",
            "property float rot_2",
            "property float rot_3",
            "end_header",
            "",
        ]
    ).encode("ascii")

    vertex_a = struct.pack(
        "<17f",
        0.0,
        0.0,
        0.0,
        0.0,
        0.0,
        1.0,
        0.0,
        0.0,
        0.0,
        0.0,
        -3.0,
        -3.0,
        -3.0,
        1.0,
        0.0,
        0.0,
        0.0,
    )
    vertex_b = struct.pack(
        "<17f",
        1.0,
        2.0,
        3.0,
        0.0,
        0.0,
        1.0,
        1.0,
        -1.0,
        0.5,
        2.0,
        -2.0,
        -2.0,
        -2.0,
        1.0,
        0.0,
        0.0,
        0.0,
    )
    ply_path.write_bytes(header + vertex_a + vertex_b)

    cloud = load_standard_3dgs_ply(str(ply_path))
    assert cloud.encoding == "standard_3dgs"
    assert cloud.point_count == 2
    assert cloud.xyz.shape == (2, 3)
    assert cloud.scale_xyz.shape == (2, 3)
    assert cloud.rgb.shape == (2, 3)
    assert cloud.opacity.shape == (2,)

    cloud_any = load_any_3dgs_ply(str(ply_path))
    assert cloud_any.encoding == "standard_3dgs"
    assert cloud_any.point_count == 2
