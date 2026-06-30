"""Video frame extraction via ffmpeg subprocess."""

from __future__ import annotations

import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path


class FrameExtractionError(Exception):
    pass


@dataclass(frozen=True)
class Frame:
    """A single extracted video frame."""

    index: int
    timestamp_s: float
    data: bytes  # JPEG-encoded


def extract_frames(
    video_path: Path,
    count: int = 5,
    max_width: int = 720,
) -> list[Frame]:
    """Extract evenly-spaced frames from a video file using ffmpeg.

    Returns up to `count` JPEG-encoded frames resized to max_width.
    Raises FrameExtractionError if ffmpeg fails.
    """
    if not video_path.exists():
        raise FrameExtractionError(f"Video file not found: {video_path}")

    duration = _get_duration(video_path)
    if duration <= 0:
        raise FrameExtractionError(f"Could not determine video duration: {video_path}")

    if count <= 1:
        timestamps = [0.0]
    else:
        step = duration / (count - 1)
        timestamps = [i * step for i in range(count)]
        timestamps[-1] = min(timestamps[-1], max(0, duration - 0.1))

    frames: list[Frame] = []
    with tempfile.TemporaryDirectory() as tmpdir:
        for i, ts in enumerate(timestamps):
            out_path = Path(tmpdir) / f"frame_{i:04d}.jpg"
            cmd = [
                "ffmpeg",
                "-y",
                "-ss",
                f"{ts:.3f}",
                "-i",
                str(video_path),
                "-frames:v",
                "1",
                "-vf",
                f"scale='min({max_width},iw)':-1",
                "-q:v",
                "2",
                str(out_path),
            ]
            result = subprocess.run(
                cmd,
                capture_output=True,
                timeout=30,
            )
            if result.returncode != 0 or not out_path.exists():
                continue

            data = out_path.read_bytes()
            if data:
                frames.append(Frame(index=i, timestamp_s=ts, data=data))

    if not frames:
        raise FrameExtractionError(f"No frames extracted from {video_path}")

    return frames


def _get_duration(video_path: Path) -> float:
    """Get video duration in seconds via ffprobe."""
    cmd = [
        "ffprobe",
        "-v",
        "quiet",
        "-show_entries",
        "format=duration",
        "-of",
        "default=noprint_wrappers=1:nokey=1",
        str(video_path),
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        if result.returncode == 0 and result.stdout.strip():
            return float(result.stdout.strip())
    except (subprocess.TimeoutExpired, ValueError):
        pass
    return 0.0


def check_ffmpeg_available() -> bool:
    """Check if ffmpeg and ffprobe are on PATH."""
    for cmd in ("ffmpeg", "ffprobe"):
        try:
            subprocess.run(
                [cmd, "-version"],
                capture_output=True,
                timeout=5,
            )
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return False
    return True
