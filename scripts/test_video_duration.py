"""Unit tests for FileModel duration helpers + sample timestamps.

Run: .venv/bin/python scripts/test_video_duration.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from looki_mcp.file_helpers import file_dimensions, file_duration_ms  # noqa: E402
from looki_mcp.tools.video import _sample_timestamps  # noqa: E402


def test_nested_metadata_duration():
    file_obj = {
        "temporary_url": "https://example.test/v.mp4",
        "media_type": "VIDEO",
        "metadata": {"width": 1600, "height": 1200, "duration_ms": 5046},
    }
    assert file_duration_ms(file_obj) == 5046
    duration_s = float(file_duration_ms(file_obj) or 0) / 1000.0
    assert duration_s == 5.046
    assert file_dimensions(file_obj) == (1600, 1200)


def test_legacy_top_level_duration():
    file_obj = {
        "temporary_url": "https://example.test/v.mp4",
        "media_type": "VIDEO",
        "duration_ms": 5046,
    }
    assert file_duration_ms(file_obj) == 5046


def test_nested_preferred_over_legacy():
    file_obj = {
        "duration_ms": 999,
        "metadata": {"duration_ms": 5046},
    }
    assert file_duration_ms(file_obj) == 5046


def test_missing_duration_is_none_and_zero_seconds():
    assert file_duration_ms({"media_type": "IMAGE", "metadata": {"width": 1}}) is None
    assert file_duration_ms({}) is None
    assert file_duration_ms(None) is None
    duration_s = float(file_duration_ms({}) or 0) / 1000.0
    assert duration_s == 0.0
    # sampling still returns max_frames placeholders when duration unknown
    ts = _sample_timestamps(duration_s, 3)
    assert ts == [0.0, 1.0, 2.0]


def test_sample_timestamps_with_real_duration():
    ts = _sample_timestamps(5.046, 5)
    assert len(ts) == 5
    assert ts[0] == 0.0
    assert ts[-1] < 5.046


def main():
    test_nested_metadata_duration()
    test_legacy_top_level_duration()
    test_nested_preferred_over_legacy()
    test_missing_duration_is_none_and_zero_seconds()
    test_sample_timestamps_with_real_duration()
    print("\033[32mPASS\033[0m video_duration")


if __name__ == "__main__":
    main()
