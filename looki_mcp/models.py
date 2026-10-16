"""Pydantic v2 models documenting the Looki API response shapes.

These models are reference documentation for the response payloads our tools
work with — they are NOT currently enforced as runtime validators. Tools call
`unwrap()` on the raw httpx response and pass through the resulting JSON
unmodified, so model drift never breaks tool behavior; it only affects how
accurately the docs match reality.

All shapes below have been re-verified against the live Looki Open API as of
**2026-10-16** (moments / profile / realtime / journals / FileModel metadata
nesting; the retired /for_you/items endpoint - see the retired-endpoint note
below). Earlier bulk checks: 2026-04-29 (moments/highlights/profile/
realtime), 2026-06-20 (journals feed), and 2026-07-18 (moments / highlights /
profile / realtime / journals).

Verification basis (2026-10-16): live probes from furnace against the live
API. The upstream agent skill doc
(https://web.looki.ai/agent/looki-memory/SKILL.md) is unchanged since July -
sha256 4c5c991cb1165b910c6cd4d95ff20d4dc1f717678233a6a27a9d30421387f939 -
and still presents /for_you/items as live, which is why this in-repo contract
carries the correction.

The Looki API wraps every response in `{code, detail, data}`; our `unwrap()`
helper strips that envelope, so the models below describe the *unwrapped* `data`
field, not the raw HTTP body.

Canonical docs: https://web.looki.ai/agent/looki-memory/SKILL.md
Also: https://clawhub.ai/haibo-looki/looki-memory
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel


class ProfileResponse(BaseModel):
    """Returned by GET /me. Note: the actual data lives at `envelope.data.user`.
    Our get_profile tool surfaces the inner `user` object directly.

    Observed /me key set (live, 2026-10-16): birthday, first_name, gender,
    id, last_name, tz. email / region / kind were absent on the observed
    payload (they remain optional below)."""

    id: str
    first_name: str
    last_name: str
    tz: str  # UTC offset in HH:MM form, e.g. "-04:00", NOT an IANA name
    email: str | None = None  # often omitted on live account payloads
    gender: int | None = None  # Integer code (e.g. 1, 2), not a string
    birthday: str | None = None  # YYYY-MM-DD
    region: str | None = None
    kind: int | None = None


class FileMetadata(BaseModel):
    """Nested under FileModel.metadata (live 2026-07)."""

    width: int | None = None
    height: int | None = None
    duration_ms: int | None = None  # video/audio; may be null on still images


class FileModel(BaseModel):
    """Underlying media file. Lives inside MomentFileModel.file, journal media,
    and realtime latest_file.

    **2026-07 live shape:** duration and dimensions live under `metadata`.
    Top-level `size` / `duration_ms` are legacy fallbacks (not present on current
    moments/files responses). Presigned URLs often expire ~10 minutes (JWT),
    though skill docs still say ~1 hour generically.
    Host observed: `devo-user-file.looki.ai`.
    """

    temporary_url: str
    media_type: str  # "IMAGE" | "VIDEO" | "AUDIO" (uppercase per live API)
    metadata: FileMetadata | None = None
    # Legacy / optional — prefer metadata.duration_ms
    size: int | None = None
    duration_ms: int | None = None


class LocationModel(BaseModel):
    """Historical structured lat/lng shape. Live payloads more often put a
    **JSON string** of address parts on `location` (see MomentFileModel)."""

    latitude: float
    longitude: float
    address: str | None = None


class MomentFileModel(BaseModel):
    """A single photo or video attached to a moment. Note `id` is a Mongo
    ObjectId-style hex string, not a UUID."""

    id: str
    file: FileModel
    thumbnail: FileModel | None = None
    # Live: usually a JSON-encoded address string, not LocationModel:
    # {"street":"...","locality":"Quincy","administrativeArea":"Massachusetts",...}
    location: str | LocationModel | None = None
    created_at: str | None = None
    tz: str | None = None


class MomentModel(BaseModel):
    """A captured memory. Returned by /moments, /moments/{id}, /moments/search items.

    `cover_file` is structurally a MomentFileModel (wraps a FileModel under .file),
    not a bare FileModel.

    Moment payloads observed live on 2026-10-16 (list, detail, search, and
    calendar highlight) also carry a `search_context` field - see the field
    note below."""

    id: str  # UUID
    title: str
    description: str | None = None
    media_types: list[str] | None = None  # e.g. ["IMAGE", "VIDEO"]
    cover_file: MomentFileModel | None = None
    date: str | None = None
    tz: str | None = None
    start_time: str
    end_time: str
    # Observed live 2026-10-16 on moment list, detail, search, and calendar
    # highlight payloads; absent from this model before the 2026-10-16 audit.
    # Undocumented upstream; shape not yet characterized, so it is documented
    # here as an optional pass-through only (no parsing / validation).
    search_context: object | None = None


class CalendarDayModel(BaseModel):
    """One day in the /moments/calendar response. The endpoint returns a bare
    list of these — there's no surrounding object."""

    date: str
    highlight_moment: MomentModel | None = None


# /moments/calendar returns: list[CalendarDayModel]
# /moments?on_date=...   returns: list[MomentModel]
# /moments/{id}/files    returns: {"items": list[MomentFileModel], next_cursor_id, has_more}
# /moments/search        returns: {"items": list[MomentModel], has_more}  (page-based)
# RETIRED: /for_you/items - do NOT call. Live probe on 2026-10-16 returned
# HTTP 400 with envelope code 105 (deprecated endpoint); the upstream detail
# points to GET /journals instead. ForYouItemModel / HighlightsResponse below
# are kept only as a historical record of the retired payload shape.


class PaginatedItems(BaseModel):
    """Generic shape used by /moments/{id}/files and /moments/search.

    The `items` field's element type varies by endpoint — see the specific
    XxxItemsResponse aliases below for precise typing."""

    items: list  # type-varying; see specific subclasses
    cursor_id: str | None = None
    next_cursor_id: str | None = None
    has_more: bool | None = None


class MomentFilesResponse(BaseModel):
    items: list[MomentFileModel]
    next_cursor_id: str | None = None
    has_more: bool | None = None


class SearchMomentsResponse(BaseModel):
    items: list[MomentModel]
    has_more: bool | None = None
    # Live 2026-07: page/page_size query params; response may omit next_cursor_id.


class ForYouItemModel(BaseModel):
    """HISTORICAL ONLY - payload of the RETIRED GET /for_you/items endpoint.

    Retired: a live probe on 2026-10-16 returned HTTP 400 with envelope
    code 105 (deprecated endpoint), and the upstream detail points to
    GET /journals instead. Do not call /for_you/items. This model is kept
    only as a record of the retired payload shape; highlights are now
    derived client-side from the journals feed.

    AI-generated highlight content. The `type` field used uppercase API codes.

    Observed types (2026-07): DAILY_VLOG, USER_VLOG, MOMENT_POST, IMAGE_POST,
    IMAGE_POST_WEEKLY_LIFE_COLORS, USER_EVENT_ANALYSIS. Note: DAILY_VLOG has
    since migrated from a for_you type to a journal type (observed live as a
    journal type in the 2026-10-16 sample; see JournalEntryModel).

    Query `group` filter (when the endpoint was live): **all | vlog | other**
    only - not comic/present.
    """

    id: str
    type: str
    title: str | None = None
    description: str | None = None
    content: str | None = None
    cover: FileModel | None = None
    file: FileModel | None = None
    created_at: str
    recorded_at: str


class HighlightsResponse(BaseModel):
    """HISTORICAL ONLY - response shape of the retired /for_you/items endpoint
    (retired 2026-10-16; HTTP 400, envelope code 105). See ForYouItemModel."""

    items: list[ForYouItemModel]
    next_cursor_id: str | None = None
    has_more: bool | None = None


class RealtimeEventResponse(BaseModel):
    """Returned by /realtime/latest-event. Beta; requires Proactive Mode.

    Live 2026-07 fields include latest_file (snapshot) and start/end times.
    """

    id: str | None = None
    description: str | None = None
    latest_file: FileModel | None = None
    start_time: str | None = None
    end_time: str | None = None
    tz: str | None = None
    # Often a JSON address string (same shape as moment file location)
    location: str | None = None
    # Legacy aliases (older docs); not seen on 2026-07 live payload
    timestamp: str | None = None
    detected_at: str | None = None


class JournalMediaFile(BaseModel):
    """The image (or other media) behind a journal media item. AI-generated; only
    `IMAGE` observed in journals so far (VIDEO/AUDIO permitted but unseen)."""

    temporary_url: str  # short-lived JWT (~10 min observed)
    media_type: str  # "IMAGE" per live API
    metadata: FileMetadata | None = None
    size: int | None = None  # legacy
    duration_ms: int | None = None  # legacy


class JournalMediaItem(BaseModel):
    """One media attachment on a journal entry. The `source.temporary_url` path
    encodes provenance under /processed/{category}/..."""

    source: JournalMediaFile
    # Serialization nuance (live, 2026-10-16): `thumbnail` was present only on
    # DAILY_VLOG media items in the observed sample; on other journal types
    # the key is omitted entirely rather than sent as null.
    thumbnail: JournalMediaFile | None = None


class JournalEntryModel(BaseModel):
    """A single journal entry. Returned both embedded in JournalDayBucketModel.journals
    and bare from GET /journals/{id}.

    Types observed 2026-07: DIARY, YESTERDAY_RECAP, DIETARY, AUDIO_SUMMARY,
    COMIC_PAGE, WEEKLY_JOURNAL, SYSTEM_POST.
    Earlier observations also included STORYBOARD, DAILY_ROUTINE (may be rare).

    Types added 2026-10-16 (observed live in a 14-day, 119-entry sample):
    DAILY_HEALTH_REPORT, DAILY_VLOG, MANUAL_AUDIO_SUMMARY, PLOG.
    DAILY_VLOG migrated from a for_you type to a journal type.

    Serialization nuance (live, 2026-10-16): the `content` key is present
    and non-null on text types (DIARY, YESTERDAY_RECAP, AUDIO_SUMMARY,
    MANUAL_AUDIO_SUMMARY) and omitted entirely on media types (COMIC_PAGE,
    DAILY_VLOG, DAILY_HEALTH_REPORT, PLOG) - omitted, not null.
    """

    id: str  # UUID — use with /journals/{id}
    type: str
    title: str | None = None  # null on DIARY / YESTERDAY_RECAP
    description: str
    content: str | None = None  # see docstring: omitted entirely on media types
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
    back as the `cursor_date` query param to page into older history.

    Query `sort_order` live enum: **asc | desc** (lowercase only).
    """

    items: list[JournalDayBucketModel]
    next_cursor_id: str | None = None
    has_more: bool | None = None


# /journals            returns: JournalsFeedResponse  (params: cursor_date, max_days≤31, sort_order=asc|desc)
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
    automatically so tools see only the inner `data` value.

    Error-code vocabulary (envelope `code`, verified 2026-10-16):
    0 = success; 100 = invalid params (unchanged); 105 = deprecated
    endpoint (new - returned for the retired /for_you/items, HTTP 400);
    106 = missing auth token (new)."""

    code: int  # 0 == success, non-zero == error
    detail: str  # "OK" on success, error description otherwise
    data: object  # Type varies by endpoint; see models above
