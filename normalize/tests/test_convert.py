"""Tests for the fisheye → perspective conversion module."""

from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np
import pytest

from eunomia_normalize.convert import (
    build_perspective_map,
    circle_geometry,
    detect_layout,
    fisheye_to_perspective,
    load_intrinsics,
    normalize_video,
)


class TestCircleGeometry:
    def test_right_half(self) -> None:
        cx, cy, r = circle_geometry(2944, 1472, "right")
        assert r == 736.0
        assert cy == 736.0
        assert cx == 2944 - 736.0

    def test_left_half(self) -> None:
        cx, cy, r = circle_geometry(2944, 1472, "left")
        assert r == 736.0
        assert cy == 736.0
        assert cx == 736.0

    def test_square_frame(self) -> None:
        cx, cy, r = circle_geometry(1000, 500, "right")
        assert r == 250.0
        assert cy == 250.0
        assert cx == 750.0


class TestBuildPerspectiveMap:
    def test_output_shape(self) -> None:
        map_x, map_y = build_perspective_map(
            src_w=2944,
            src_h=1472,
            out_w=960,
            out_h=720,
            fov_h_deg=120.0,
            fov_v_deg=90.0,
            yaw_deg=0.0,
            pitch_deg=0.0,
            cx_fish=2208.0,
            cy_fish=736.0,
            r_max=736.0,
        )
        assert map_x.shape == (720, 960)
        assert map_y.shape == (720, 960)
        assert map_x.dtype == np.float32
        assert map_y.dtype == np.float32

    def test_center_pixel_maps_to_optical_axis(self) -> None:
        cx_fish, cy_fish, r_max = 2208.0, 736.0, 736.0
        map_x, map_y = build_perspective_map(
            src_w=2944,
            src_h=1472,
            out_w=960,
            out_h=720,
            fov_h_deg=120.0,
            fov_v_deg=90.0,
            yaw_deg=0.0,
            pitch_deg=0.0,
            cx_fish=cx_fish,
            cy_fish=cy_fish,
            r_max=r_max,
        )
        center_y, center_x = 360, 480
        assert abs(map_x[center_y, center_x] - cx_fish) < 0.5
        assert abs(map_y[center_y, center_x] - cy_fish) < 0.5

    def test_nonzero_pitch_shifts_center(self) -> None:
        cx_fish, cy_fish, r_max = 2208.0, 736.0, 736.0
        map_x_0, map_y_0 = build_perspective_map(
            src_w=2944,
            src_h=1472,
            out_w=960,
            out_h=720,
            fov_h_deg=120.0,
            fov_v_deg=90.0,
            yaw_deg=0.0,
            pitch_deg=0.0,
            cx_fish=cx_fish,
            cy_fish=cy_fish,
            r_max=r_max,
        )
        map_x_30, map_y_30 = build_perspective_map(
            src_w=2944,
            src_h=1472,
            out_w=960,
            out_h=720,
            fov_h_deg=120.0,
            fov_v_deg=90.0,
            yaw_deg=0.0,
            pitch_deg=-30.0,
            cx_fish=cx_fish,
            cy_fish=cy_fish,
            r_max=r_max,
        )
        assert not np.allclose(map_y_0, map_y_30)


class TestDetectLayout:
    def test_sbs_layout(self, tmp_path: Path) -> None:
        video = tmp_path / "test.mp4"
        _write_solid_video(video, width=2944, height=1472, frames=2)
        layout, w, h = detect_layout(video)
        assert layout == "sbs"
        assert w == 2944
        assert h == 1472

    def test_single_layout(self, tmp_path: Path) -> None:
        video = tmp_path / "test.mp4"
        _write_solid_video(video, width=2880, height=2880, frames=2)
        layout, w, h = detect_layout(video)
        assert layout == "single"

    def test_unopenable_raises(self, tmp_path: Path) -> None:
        with pytest.raises(RuntimeError, match="Cannot open"):
            detect_layout(tmp_path / "nonexistent.mp4")


class TestFisheyeToPerspective:
    def test_converts_sbs_video(self, tmp_path: Path) -> None:
        insv = tmp_path / "input.mp4"
        _write_solid_video(insv, width=2944, height=1472, frames=5)

        out = tmp_path / "workspace.mp4"
        result = fisheye_to_perspective(insv, out, out_w=320, out_h=240)

        assert result == out
        assert out.exists()
        cap = cv2.VideoCapture(str(out))
        assert int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)) == 320
        assert int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)) == 240
        assert int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) == 5
        cap.release()

    def test_rejects_non_sbs(self, tmp_path: Path) -> None:
        insv = tmp_path / "legacy.mp4"
        _write_solid_video(insv, width=2880, height=2880, frames=2)

        out = tmp_path / "workspace.mp4"
        with pytest.raises(RuntimeError, match="not SBS"):
            fisheye_to_perspective(insv, out)


class TestNormalizeVideo:
    def test_creates_output_in_subdir(self, tmp_path: Path) -> None:
        insv = tmp_path / "VID_20260624_101000_00_043.mp4"
        _write_solid_video(insv, width=2944, height=1472, frames=3)

        output_dir = tmp_path / "normalized"
        result = normalize_video(insv, output_dir)

        assert result == output_dir / "VID_20260624_101000_043_workspace.mp4"
        assert result.exists()


class TestLoadIntrinsics:
    def test_shipped_default(self) -> None:
        intrinsics = load_intrinsics()
        assert intrinsics["camera_name"] == "insta360_x3"
        assert intrinsics["sbs_workspace_half"] == "right"
        assert intrinsics["perspective_crop"]["output_width"] == 960

    def test_custom_path(self, tmp_path: Path) -> None:
        custom = tmp_path / "custom.json"
        custom.write_text('{"camera_name": "test", "perspective_crop": {}}')
        intrinsics = load_intrinsics(custom)
        assert intrinsics["camera_name"] == "test"


def _write_solid_video(
    path: Path, *, width: int, height: int, frames: int, fps: float = 30.0
) -> None:
    """Write a minimal solid-color video for testing."""
    fourcc = cv2.VideoWriter.fourcc(*"mp4v")
    writer = cv2.VideoWriter(str(path), fourcc, fps, (width, height))
    frame = np.zeros((height, width, 3), dtype=np.uint8)
    frame[:] = (128, 64, 32)
    for _ in range(frames):
        writer.write(frame)
    writer.release()
