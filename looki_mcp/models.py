"""Pydantic v2 models documenting the Looki API response shapes.

These models are reference documentation for the response payloads our tools
work with — they are NOT currently enforced as runtime validators. Tools call
`unwrap()` on the raw httpx response and pass through the resulting JSON
unmodified, so model drift never breaks tool behavior; it only affects how
accurately the docs match reality.

All shapes below have been verified against the live Looki API as of 2026-04-29.
The Looki API wraps every response in `{code, detail, data}`; our `unwrap()`
helper strips that envelope, so the models below describe the *unwrapped* `data`
field, not the raw HTTP body.

Field names sourced from observed responses + the Looki ClaWHub documentation:
https://clawhub.ai/haibo-looki/looki-memory
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel


class ProfileResponse(BaseModel):
    """Returned by GET /me. Note: the actual data lives at `envelope.data.user`.
    Our get_profile tool surfaces the inner `user` object directly."""

    id: str
    first_name: str
    last_name: str
    tz: str  # UTC offset in HH:MM form, e.g. "-04:00", NOT an IANA name
    email: str | None = None
    gender: int | None = None  # Integer code (e.g. 1, 2), not a string
    birthday: str | None = None  # YYYY-MM-DD
    region: str | None = None
    kind: int | None = None


class FileModel(BaseModel):
    """Underlying media file. Lives inside MomentFileModel.file."""

    temporary_url: str  # Presigned URL, valid ~1 hour
    media_type: str  # "IMAGE" | "VIDEO" (uppercase per live API)
    size: int | None = None
    duration_ms: int | None = None


class LocationModel(BaseModel):
    latitude: float
    longitude: float
    address: str | None = None


class MomentFileModel(BaseModel):
    """A single photo or video attached to a moment. Note `id` is a Mongo
    ObjectId-style hex string, not a UUID."""

    id: str
    file: FileModel
    thumbnail: FileModel | None = None
    location: LocationModel | None = None
    created_at: str | None = None
    tz: str | None = None


class MomentModel(BaseModel):
    """A captured memory. Returned by /moments, /moments/{id}, /moments/search items.

    `cover_file` is structurally a MomentFileModel (wraps a FileModel under .file),
    not a bare FileModel."""

    id: str  # UUID
    title: str
    description: str | None = None
    media_types: list[str] | None = None  # e.g. ["IMAGE", "VIDEO"]
    cover_file: MomentFileModel | None = None
    date: str | None = None
    tz: str | None = None
    start_time: str
    end_time: str


class CalendarDayModel(BaseModel):
    """One day in the /moments/calendar response. The endpoint returns a bare
    list of these — there's no surrounding object."""

    date: str
    highlight_moment: MomentModel | None = None


# /moments/calendar returns: list[CalendarDayModel]
# /moments?on_date=...   returns: list[MomentModel]
# /moments/{id}/files    returns: {"items": list[MomentFileModel], maybe cursor_id, has_more}
# /moments/search        returns: {"items": list[MomentModel], maybe cursor_id, has_more}
# /for_you/items         returns: {"items": list[ForYouItemModel], maybe cursor_id, has_more}


class PaginatedItems(BaseModel):
    """Generic shape used by /moments/{id}/files, /moments/search, /for_you/items.

    The `items` field's element type varies by endpoint — see the specific
    XxxItemsResponse aliases below for precise typing."""

    items: list  # type-varying; see specific subclasses
    cursor_id: str | None = None
    has_more: bool | None = None


class MomentFilesResponse(BaseModel):
    items: list[MomentFileModel]
    cursor_id: str | None = None
    has_more: bool | None = None


class SearchMomentsResponse(BaseModel):
    items: list[MomentModel]
    cursor_id: str | None = None
    has_more: bool | None = None
    # No page / page_size / total in the live response — pagination is cursor-based.


class ForYouItemModel(BaseModel):
    """AI-generated highlight content. The `type` field uses uppercase API codes
    (e.g. "DAILY_VLOG"). Our get_highlights tool exposes friendlier values to
    callers (`vlog`, `comic`, etc.) but Looki's vocabulary is the source of truth
    for what gets returned here."""

    id: str
    type: str  # e.g. "DAILY_VLOG", "COMIC", etc. — uppercase per live API
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


class RealtimeEventResponse(BaseModel):
    """Returned by /realtime/latest-event. Beta endpoint; requires Proactive Mode."""

    id: str | None = None
    description: str | None = None
    timestamp: str | None = None
    detected_at: str | None = None


class VerifyResponse(BaseModel):
    """Returned by GET https://open.looki.ai/api/v1/verify?endpoint=...
    NOT wrapped in the standard envelope — this endpoint returns {"status": "ok"}
    on success or HTTP 4xx with {"code": N, "detail": ...} on failure."""

    status: Literal["ok"]


# Documenting the response envelope itself for future readers.
class LookiResponseEnvelope(BaseModel):
    """Every authenticated Looki API call (i.e. base_url + /me, /moments, etc.)
    wraps its payload in this envelope. `client.unwrap()` strips this layer
    automatically so tools see only the inner `data` value."""

    code: int  # 0 == success, non-zero == error
    detail: str  # "OK" on success, error description otherwise
    data: object  # Type varies by endpoint; see models above
