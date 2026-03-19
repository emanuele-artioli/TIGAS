# TIGAS web-splat frame renderer

This folder contains a simple script that renders a hardcoded list of camera poses using the `WebSplatGenerator` wrapper from `/home/itec/emanuele/web-splat` and saves the outputs as JPG frames.

The camera JSON is hardcoded directly in the script as 6DoF tuples:

- position: `x, y, z`
- orientation: `roll_deg, pitch_deg, yaw_deg`

These tuples were validated against the dataset so the output frames show the 3DGS model (not black).

## Files

- `render_websplat_frames.py`: hardcoded PLY path, scene path, and JSON 6DoF pose list.
- `requirements.txt`: Python dependencies for the script.

## Hardcoded paths in script

- PLY: `/home/itec/emanuele/Datasets/3DGS/garden/point_cloud/iteration_30000/point_cloud.ply`
- Scene: `/home/itec/emanuele/Datasets/3DGS/garden/cameras.json`
- Output JPGs: `/home/itec/emanuele/TIGAS/outputs/websplat_jpg_frames`

## Setup

```bash
cd /home/itec/emanuele/TIGAS && conda activate tigas
pip install -r requirements.txt
```

## Run

```bash
cd /home/itec/emanuele/TIGAS && conda activate tigas
python render_websplat_frames.py
```

The script will render each hardcoded pose and write `frame_0000.jpg`, `frame_0001.jpg`, ... into the output directory.
