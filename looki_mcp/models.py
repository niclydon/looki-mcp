"""Pydantic v2 models for Looki API responses.

Field names sourced from the official Looki documentation at
https://clawhub.ai/haibo-looki/looki-memory
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel


class ProfileResponse(BaseModel):
    id: str
    email: str
    first_name: str
    last_name: str
    tz: str
    gender: str | None = None
    birthday: str | None = None
    region: str | None = None


class FileModel(BaseModel):
    temporary_url: str
    media_type: Literal["photo", "video"]
    size: int | None = None
    duration_ms: int | None = None


class LocationModel(BaseModel):
    latitude: float
    longitude: float
    address: str | None = None


class MomentModel(BaseModel):
    id: str
    title: str
    description: str | None = None
    media_types: list[str] | None = None
    cover_file: FileModel | None = None
    date: str | None = None
    tz: str | None = None
    start_time: str
    end_time: str


class CalendarDayModel(BaseModel):
    date: str
    has_moment: bool
    moment_count: int | None = None
    highlight_moment: MomentModel | None = None


class CalendarResponse(BaseModel):
    days: list[CalendarDayModel]


class MomentsListResponse(BaseModel):
    moments: list[MomentModel]


class MomentFileModel(BaseModel):
    id: str
    file: FileModel
    thumbnail: FileModel | None = None
    location: LocationModel | None = None
    created_at: str | None = None
    tz: str | None = None


class MomentFilesResponse(BaseModel):
    files: list[MomentFileModel]
    cursor_id: str | None = None
    has_more: bool | None = None


class SearchMomentsResponse(BaseModel):
    moments: list[MomentModel]
    page: int
    page_size: int
    total: int | None = None


class ForYouItemModel(BaseModel):
    id: str
    type: Literal["comic", "vlog", "present", "other"]
    title: str | None = None
    description: str | None = None
    content: str | None = None
    cover: FileModel | None = None
    file: FileModel | None = None
    created_at: str
    recorded_at: str


class HighlightsResponse(BaseModel):
    items: list[ForYouItemModel]
    cursor_id: str | None = None
    has_more: bool | None = None


class RealtimeEventModel(BaseModel):
    event_type: str | None = None
    description: str | None = None
    timestamp: str | None = None
    detected_at: str | None = None


class RealtimeEventResponse(BaseModel):
    event: RealtimeEventModel | None = None
    available: bool


class VerifyResponse(BaseModel):
    valid: bool
    message: str | None = None
