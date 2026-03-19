#!/usr/bin/env python3
"""Render hardcoded web-splat camera poses and save JPG frames."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from PIL import Image

WEBSPLAT_PROJECT_ROOT = Path("/home/itec/emanuele/web-splat")
if str(WEBSPLAT_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(WEBSPLAT_PROJECT_ROOT))

from websplat_generator import WebSplatGenerator

PLY_PATH = Path(
    "/home/itec/emanuele/Datasets/3DGS/garden/point_cloud/iteration_30000/point_cloud.ply"
)
SCENE_PATH = Path("/home/itec/emanuele/Datasets/3DGS/garden/cameras.json")
OUTPUT_DIR = Path("/home/itec/emanuele/TIGAS/outputs/websplat_jpg_frames")

CAMERA_POSES_JSON = """
[
    {
        "x": -3.30326227674897,
        "y": 1.1459637860858836,
        "z": -0.799459662873427,
        "roll_deg": 49.84636687,
        "pitch_deg": 38.02498847,
        "yaw_deg": 55.47224673
    },
    {
        "x": -3.747014766310446,
        "y": 1.023277531795199,
        "z": 0.46018699117578293,
        "roll_deg": 77.2295525,
        "pitch_deg": 69.0727607,
        "yaw_deg": 61.42464165
    },
    {
        "x": 0.9254777855307261,
        "y": 2.9276458372690697,
        "z": -3.282922615677503,
        "roll_deg": -3.98431288,
        "pitch_deg": 20.49735464,
        "yaw_deg": -4.79945193
    },
    {
        "x": 3.031529505653127,
        "y": -0.0537913821049901,
        "z": -1.18015447121763,
        "roll_deg": -46.6605102,
        "pitch_deg": 12.85115286,
        "yaw_deg": -50.80019678
    },
    {
        "x": -3.4166628460181556,
        "y": 1.7659905606502877,
        "z": -0.9752561451985035,
        "roll_deg": 40.2668318,
        "pitch_deg": 37.78713117,
        "yaw_deg": 51.81521852
    }
]
"""


def parse_camera_poses(pose_json: str) -> list[tuple[float, float, float, float, float, float]]:
    """Parse hardcoded JSON camera poses into 6DoF tuples."""
    raw_poses = json.loads(pose_json)
    poses: list[tuple[float, float, float, float, float, float]] = []

    for idx, pose in enumerate(raw_poses):
        required = ("x", "y", "z", "roll_deg", "pitch_deg", "yaw_deg")
        missing = [k for k in required if k not in pose]
        if missing:
            raise ValueError(f"Pose index {idx} is missing keys: {missing}")

        poses.append(
            (
                float(pose["x"]),
                float(pose["y"]),
                float(pose["z"]),
                float(pose["roll_deg"]),
                float(pose["pitch_deg"]),
                float(pose["yaw_deg"]),
            )
        )

    if not poses:
        raise ValueError("No camera poses found in CAMERA_POSES_JSON")

    return poses


def save_frame_as_jpg(frame_rgba, output_path: Path) -> None:
    """Save RGBA uint8 numpy frame as JPEG (RGB)."""
    image = Image.fromarray(frame_rgba[:, :, :3], mode="RGB")
    image.save(output_path, format="JPEG", quality=95, optimize=True)


def render_all_poses() -> None:
    if not PLY_PATH.exists():
        raise FileNotFoundError(f"PLY file not found: {PLY_PATH}")
    if not SCENE_PATH.exists():
        raise FileNotFoundError(f"Scene file not found: {SCENE_PATH}")

    poses = parse_camera_poses(CAMERA_POSES_JSON)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    with WebSplatGenerator(
        point_cloud_path=PLY_PATH,
        scene_path=SCENE_PATH,
        project_root=WEBSPLAT_PROJECT_ROOT,
        release=True,
    ) as renderer:
        for idx, frame in enumerate(renderer.render_many(poses)):
            jpg_path = OUTPUT_DIR / f"frame_{idx:04d}.jpg"
            save_frame_as_jpg(frame, jpg_path)
            print(f"Saved {jpg_path}")


if __name__ == "__main__":
    render_all_poses()
