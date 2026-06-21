"""Pydantic v2 models documenting the Looki API response shapes.

These models are reference documentation for the response payloads our tools
work with — they are NOT currently enforced as runtime validators. Tools call
`unwrap()` on the raw httpx response and pass through the resulting JSON
unmodified, so model drift never breaks tool behavior; it only affects how
accurately the docs match reality.

All shapes below have been verified against the live Looki API as of 2026-04-29
(moments / highlights / profile / realtime) and 2026-06-20 (journals).
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


class JournalMediaFile(BaseModel):
    """The image (or other media) behind a journal media item. AI-generated; only
    `IMAGE` observed in journals so far (VIDEO/AUDIO permitted but unseen)."""

    temporary_url: str  # Presigned URL; short-lived JWT (~10 min observed, shorter than moments' ~1h)
    media_type: str  # "IMAGE" per live API
    size: int | None = None
    duration_ms: int | None = None


class JournalMediaItem(BaseModel):
    """One media attachment on a journal entry. The `source.temporary_url` path
    encodes provenance: /processed/{user_event_diary_image|dietary_image|
    storyboard_image|meeting_analysis_cover_image|daily_routine_image}/..."""

    source: JournalMediaFile
    thumbnail: JournalMediaFile | None = None


class JournalEntryModel(BaseModel):
    """A single journal entry. Returned both embedded in JournalDayBucketModel.journals
    and bare from GET /journals/{id}. Six observed `type` values, each with a different
    text/media profile (see journals_api_findings.md):
    YESTERDAY_RECAP (long recap, no title/media), DIETARY & AUDIO_SUMMARY (titled, long
    content, 1 image), DIARY (short vignette, ~0.6 images), STORYBOARD & DAILY_ROUTINE
    (titled, description-only, multi-day, 1 image)."""

    id: str  # UUID — use with /journals/{id}
    type: str  # YESTERDAY_RECAP | DIETARY | AUDIO_SUMMARY | DIARY | STORYBOARD | DAILY_ROUTINE
    title: str | None = None  # null on DIARY / YESTERDAY_RECAP
    description: str
    content: str | None = None  # null on STORYBOARD / DAILY_ROUTINE
    media_items: list[JournalMediaItem] = []
    date: str  # YYYY-MM-DD
    start_date: str | None = None  # range start for multi-day types
    tz: str  # UTC offset, e.g. "-04:00"
    recorded_at: str
    created_at: str


class JournalDayBucketModel(BaseModel):
    """One day-grouping in the journals feed / by_date response. NOTE: a single
    calendar date can yield MULTIPLE buckets (e.g. a multi-day STORYBOARD plus the
    regular single-day bucket)."""

    date: str
    start_date: str | None = None  # set on buckets that hold a multi-day entry
    journals: list[JournalEntryModel]


class JournalCalendarDayModel(BaseModel):
    """One day in the /journals/calendar response. The endpoint returns a bare list
    of these (just dates that have entries) — there's no surrounding object."""

    date: str


class JournalsFeedResponse(BaseModel):
    """GET /journals. `next_cursor_id` is a DATE string (not an opaque id) — pass it
    back as the `cursor_date` query param to page into older history."""

    items: list[JournalDayBucketModel]
    next_cursor_id: str | None = None
    has_more: bool | None = None


# /journals            returns: JournalsFeedResponse  (params: cursor_date, max_days≤31, sort_order)
# /journals/calendar   returns: list[JournalCalendarDayModel]  (params: start_date, end_date)
# /journals/by_date    returns: list[JournalDayBucketModel]    (params: on_date)
# /journals/{id}       returns: JournalEntryModel


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
