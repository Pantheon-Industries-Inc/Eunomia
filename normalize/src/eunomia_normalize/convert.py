"""Insta360 X3 SBS fisheye → flat perspective conversion.

Ported from data-ingress/scripts/s01_convert_insv.py. SBS (3K/100 mode) only — legacy single-circle
format is not supported (the site runs 3K/100 exclusively; see NORM1 annotations OQ1).

The Insta360 X3 uses equidistant fisheye projection (r = f * theta). ffmpeg's v360 filter uses
equisolid (r = 2f sin(theta/2)) — wrong model, produces geometric distortion. OpenCV cv2.remap()
with pre-computed projection maps is the correct approach.
"""

from __future__ import annotations

import json
import logging
from importlib import resources
from pathlib import Path

import cv2
import numpy as np

log = logging.getLogger(__name__)

SBS_ASPECT_THRESHOLD = 1.8


def load_intrinsics(path: Path | None = None) -> dict:
    """Load camera intrinsics from a JSON file, or the shipped default."""
    if path is not None:
        with open(path) as f:
            return json.load(f)
    ref = resources.files("eunomia_normalize") / "config" / "camera_intrinsics.json"
    return json.loads(ref.read_text(encoding="utf-8"))


def circle_geometry(src_w: int, src_h: int, half: str) -> tuple[float, float, float]:
    """Return (cx, cy, r) of the workspace fisheye circle in an SBS frame.

    An SBS frame packs two H x H circles side-by-side, so each circle has
    radius H/2. ``half`` is "left" or "right".
    """
    r = src_h / 2.0
    cy = src_h / 2.0
    cx = r if half == "left" else (src_w - r)
    return cx, cy, r


def build_perspective_map(
    src_w: int,
    src_h: int,
    out_w: int,
    out_h: int,
    fov_h_deg: float,
    fov_v_deg: float,
    yaw_deg: float,
    pitch_deg: float,
    cx_fish: float,
    cy_fish: float,
    r_max: float,
) -> tuple[np.ndarray, np.ndarray]:
    """Pre-compute remap arrays for equidistant fisheye → perspective.

    The Insta360 X3 single-lens fisheye uses equidistant projection:
    r = f * theta, where theta is the angle from the optical axis.
    ~200 deg FOV → max_theta = 100 deg = 1.745 rad.
    """
    fov_h = np.radians(fov_h_deg)
    fov_v = np.radians(fov_v_deg)
    yaw = np.radians(yaw_deg)
    pitch = np.radians(pitch_deg)

    fx = out_w / (2.0 * np.tan(fov_h / 2.0))
    fy = out_h / (2.0 * np.tan(fov_v / 2.0))
    cx_out, cy_out = out_w / 2.0, out_h / 2.0

    max_theta = np.radians(100.0)
    f_fish = r_max / max_theta

    u_1d = np.arange(out_w, dtype=np.float64)
    v_1d = np.arange(out_h, dtype=np.float64)
    u, v = np.meshgrid(u_1d, v_1d)

    x = (u - cx_out) / fx
    y = (v - cy_out) / fy
    z = np.ones_like(x)

    cp, sp = np.cos(pitch), np.sin(pitch)
    cy_, sy = np.cos(yaw), np.sin(yaw)

    x1 = x
    y1 = y * cp - z * sp
    z1 = y * sp + z * cp

    x2 = x1 * cy_ + z1 * sy
    y2 = y1
    z2 = -x1 * sy + z1 * cy_

    norm_xy = np.sqrt(x2**2 + y2**2)
    theta = np.arctan2(norm_xy, z2)
    phi = np.arctan2(y2, x2)

    r = f_fish * theta
    map_x = (cx_fish + r * np.cos(phi)).astype(np.float32)
    map_y = (cy_fish + r * np.sin(phi)).astype(np.float32)

    return map_x, map_y


def detect_layout(video_path: Path) -> tuple[str, int, int]:
    """Return (layout, width, height). Only "sbs" is supported for NORM1."""
    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        raise RuntimeError(f"Cannot open {video_path}")
    w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    cap.release()
    layout = "sbs" if h and (w / h) >= SBS_ASPECT_THRESHOLD else "single"
    return layout, w, h


def fisheye_to_perspective(
    fisheye_path: Path,
    output_path: Path,
    fov_h_deg: float = 120.0,
    fov_v_deg: float = 90.0,
    yaw_deg: float = 0.0,
    pitch_deg: float = 0.0,
    out_w: int = 960,
    out_h: int = 720,
    workspace_half: str = "right",
) -> Path:
    """Extract a flat perspective crop from an SBS fisheye video."""
    cap = cv2.VideoCapture(str(fisheye_path))
    if not cap.isOpened():
        raise RuntimeError(f"Cannot open {fisheye_path}")

    src_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    src_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0

    if src_h and (src_w / src_h) < SBS_ASPECT_THRESHOLD:
        cap.release()
        raise RuntimeError(
            f"{fisheye_path.name}: not SBS layout ({src_w}x{src_h}). "
            "NORM1 supports SBS (3K/100) only."
        )

    cx_fish, cy_fish, r_max = circle_geometry(src_w, src_h, workspace_half)
    map_x, map_y = build_perspective_map(
        src_w,
        src_h,
        out_w,
        out_h,
        fov_h_deg,
        fov_v_deg,
        yaw_deg,
        pitch_deg,
        cx_fish=cx_fish,
        cy_fish=cy_fish,
        r_max=r_max,
    )

    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    fourcc = cv2.VideoWriter.fourcc(*"mp4v")
    writer = cv2.VideoWriter(str(output_path), fourcc, fps, (out_w, out_h))
    if not writer.isOpened():
        cap.release()
        raise RuntimeError(f"Cannot open video writer for {output_path}")

    written = 0
    for _ in range(total_frames):
        ok, frame = cap.read()
        if not ok:
            break
        crop = cv2.remap(frame, map_x, map_y, cv2.INTER_LINEAR)
        writer.write(crop)
        written += 1

    cap.release()
    writer.release()

    log.info(
        "%s → %s (%d frames, %.1f fps)",
        fisheye_path.name,
        output_path.name,
        written,
        fps,
    )
    return output_path


def normalize_video(
    insv_path: Path,
    output_dir: Path,
    intrinsics: dict | None = None,
) -> Path:
    """Normalize a single .insv file to a workspace perspective MP4.

    Returns the path to the output MP4.
    """
    if intrinsics is None:
        intrinsics = load_intrinsics()

    crop = intrinsics.get("perspective_crop", {})
    workspace_half = intrinsics.get("sbs_workspace_half", "right")

    stem = insv_path.stem.replace("_00_", "_")
    output_path = output_dir / f"{stem}_workspace.mp4"
    output_dir.mkdir(parents=True, exist_ok=True)

    fisheye_to_perspective(
        insv_path,
        output_path,
        fov_h_deg=crop.get("fov_horizontal_deg", 120),
        fov_v_deg=crop.get("fov_vertical_deg", 90),
        yaw_deg=crop.get("center_yaw_deg", 0),
        pitch_deg=crop.get("center_pitch_deg", 0),
        out_w=crop.get("output_width", 960),
        out_h=crop.get("output_height", 720),
        workspace_half=workspace_half,
    )

    return output_path
