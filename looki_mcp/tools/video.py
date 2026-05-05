from __future__ import annotations

import asyncio
import json
import os
import tempfile
from pathlib import Path
import shutil
from typing import Any

import httpx
from fastmcp import FastMCP

from looki_mcp.client import format_error, get_client, unwrap


def _first_video_file(payload: Any) -> dict[str, Any] | None:
    items = payload.get("items") if isinstance(payload, dict) else None
    if not isinstance(items, list):
        return None
    for item in items:
        if not isinstance(item, dict):
            continue
        file_obj = item.get("file")
        if isinstance(file_obj, dict) and str(file_obj.get("media_type", "")).upper() == "VIDEO":
            return item
    return None


async def _download(url: str, target: Path) -> None:
    async with httpx.AsyncClient(timeout=60.0, follow_redirects=True) as client:
        response = await client.get(url)
        response.raise_for_status()
        target.write_bytes(response.content)


async def _run_ffmpeg(video_path: Path, output_pattern: Path, timestamps: list[float]) -> None:
    ffmpeg = os.environ.get("FFMPEG_BIN", "ffmpeg")
    if not shutil.which(ffmpeg):
        raise RuntimeError("ffmpeg missing")
    args = [ffmpeg, "-hide_banner", "-loglevel", "error", "-i", str(video_path)]
    filters = "+".join(f"eq(t\\,{ts})" for ts in timestamps)
    args.extend(["-vf", f"select='{filters}'", "-vsync", "0", str(output_pattern)])
    proc = await asyncio.create_subprocess_exec(*args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    _stdout, stderr = await proc.communicate()
    if proc.returncode != 0:
        raise RuntimeError(stderr.decode("utf-8", "ignore").strip() or "ffmpeg failed")


def _sample_timestamps(duration_s: float, max_frames: int) -> list[float]:
    if max_frames <= 1:
        return [0.0]
    if duration_s <= 0:
        return [float(i) for i in range(max_frames)]
    step = duration_s / max_frames
    return [round(step * i, 3) for i in range(max_frames)]


def register_video_tools(mcp: FastMCP) -> None:
    @mcp.tool
    async def extract_video_frames(moment_id: str, max_frames: int = 5) -> str:
        """
        For a moment that contains a video file, sample evenly spaced frames and
        return a Looki-shaped frame set.
        """
        if max_frames < 1 or max_frames > 12:
            return "Error: max_frames must be between 1 and 12."
        try:
            async with get_client() as client:
                response = await client.get(f"/moments/{moment_id}/files", params={"limit": 100})
                payload = unwrap(response)
            video_item = _first_video_file(payload)
            if not video_item:
                return json.dumps({"moment_id": moment_id, "frames": [], "frame_count": 0, "max_frames": max_frames, "truncated": False, "reason": "no_video_file"}, indent=2)
            file_obj = video_item.get("file", {})
            url = file_obj.get("temporary_url")
            if not isinstance(url, str) or not url:
                return json.dumps({"moment_id": moment_id, "frames": [], "frame_count": 0, "max_frames": max_frames, "truncated": False, "reason": "video_url_missing"}, indent=2)
            duration_s = float(file_obj.get("duration_ms", 0) or 0) / 1000.0
            timestamps = _sample_timestamps(duration_s, max_frames)
            tmp_path = Path(tempfile.mkdtemp(prefix="looki-video-frames-"))
            video_path = tmp_path / "source.mp4"
            await _download(url, video_path)
            output_pattern = tmp_path / "frame-%03d.jpg"
            if not shutil.which(os.environ.get("FFMPEG_BIN", "ffmpeg")):
                return "Error: ffmpeg missing"
            await _run_ffmpeg(video_path, output_pattern, timestamps)
            frames = []
            for index, frame_path in enumerate(sorted(tmp_path.glob("frame-*.jpg"))):
                frames.append({
                    "t_s": timestamps[index] if index < len(timestamps) else None,
                    "url": frame_path.as_uri(),
                    "width": None,
                    "height": None,
                })
            return json.dumps({
                "moment_id": moment_id,
                "file_id": video_item.get("id"),
                "duration_s": duration_s,
                "frames": frames,
                "frame_count": len(frames),
                "max_frames": max_frames,
                "truncated": False,
            }, indent=2)
        except Exception as exc:
            return f"Error: {format_error(exc)}"
