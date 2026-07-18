# The Contract Drifted While the Endpoints Stayed Put

Looki did not ship a new Open API surface in July. The twelve authenticated paths
that already powered looki-mcp — `/me`, moments calendar/list/detail/files/search,
journals feed/calendar/by_date/detail, `/for_you/items`, `/realtime/latest-event` —
were still the whole public developer platform. What *had* moved was the contract
around those paths: nested file metadata, stricter query enums, richer realtime
payloads, and a type vocabulary the models no longer described. The discovery
session of 2026-07-18 turned that gap into a ProjectManager run-pack (**RP-57**),
six `autonomous_safe` OBs, a single ship that made production honest again, and
finally the branch-topology cleanup the June deploy narrative had only flagged.

This is the record of that arc: discovery against skill + live API, the six OB
slices, the batched implement/deploy/close, the push/merge that closed the git
gap, and the end of `master` as a peer of `main`.

## What We Thought We Were Looking For

The ask was parity discovery: use this repo, the latest Looki docs, and the live
endpoints, and report what needed adding to the MCP toolset. The expected answer
was "here are N new endpoints." The actual answer was "the endpoint inventory is
complete; the *wire contract* is lying to the tools."

### Docs surface

There is still **no OpenAPI JSON** on `open.looki.ai`. Probes of
`/openapi.json`, `/docs`, and `/swagger` returned 404. The canonical public
contract remains the agent skill:

- `https://web.looki.ai/agent/looki-memory/SKILL.md`
- Skill sha256 (2026-07-18): `4c5c991cb1165b91…` (prefix used as baseline later)
- ClawHub mirror: same twelve paths, no extras

The web SPA (`web.looki.ai`) is a different animal. Its runtime config points
`apiBaseUrl` at the private app host and `developerPlatformApi` at
`https://open.looki.ai/api/v1`. Mining the frontend bundle surfaced app routes
(`/moments/by-cursor`, `/moments/monthly-calendar`, `/albums`, `/loom/*`,
`/users/info`, …). Those **404** on the Open platform with an `X-API-Key`. They
are not MCP parity targets.

### Live Open API inventory

Against `LOOKI_BASE_URL` + key, ~100 speculative paths were probed. Only the
known skill surface returned 200 with envelope `code=0`:

| Path | Live |
|---|---|
| `GET /me` | 200 |
| `GET /moments`, `/moments/calendar`, `/moments/search`, `/moments/{id}`, `/moments/{id}/files` | 200 |
| `GET /journals`, `/journals/calendar`, `/journals/by_date`, `/journals/{id}` | 200 |
| `GET /for_you/items` | 200 |
| `GET /realtime/latest-event` | 200 |

Many "interesting" 422s under `/moments/*` and `/journals/*` were **false
positives**: FastAPI path-param capture. Example:

```json
{
  "code": 100,
  "detail": "Invalid request parameters",
  "data": {
    "errors": [{
      "loc": ["path", "moment_id"],
      "msg": "Value error, Invalid format",
      "input": "by-cursor"
    }]
  }
}
```

`/moments/by-cursor` is not a new route. It is `/moments/{moment_id}` with
`moment_id="by-cursor"`. Same pattern for `/journals/search`,
`/moments/monthly-calendar`, and friends.

**No new MCP tools were required for endpoint parity.** The twelve routes already
had tool mirrors (plus composites). The work was contract fidelity.

## What Actually Broke

### 1. FileModel nested `metadata` (breaking for video)

**Old (models + skill sketch):**
```json
{ "temporary_url": "...", "media_type": "VIDEO", "size": 123, "duration_ms": 5012 }
```

**Live 2026-07:**
```json
{
  "temporary_url": "https://devo-user-file.looki.ai/...",
  "media_type": "VIDEO",
  "metadata": { "width": 1600, "height": 1200, "duration_ms": 5046 }
}
```

Top-level `size` / `duration_ms` are gone on current moments/files. Host moved to
`devo-user-file.looki.ai`. JWT expiry still ~10 minutes.

`extract_video_frames` did:

```python
duration_s = float(file_obj.get("duration_ms", 0) or 0) / 1000.0
```

That always produced `0` on live payloads, so `_sample_timestamps` fell into the
`duration_s <= 0` branch and used `range(max_frames)` instead of real spacing.

### 2. Highlights `group` enum (hard 422)

Skill + live reject anything outside `all | vlog | other`. MCP accepted
`comic` and `present`. Live error:

```
Input should be 'all', 'vlog' or 'other'
```

Comic-like content still exists as **item `type`s** under `group=other`
(observed: `MOMENT_POST`, `IMAGE_POST`, `IMAGE_POST_WEEKLY_LIFE_COLORS`,
`USER_EVENT_ANALYSIS`, `DAILY_VLOG`, `USER_VLOG`). The group filter is not a type
filter.

### 3. Journals `sort_order` case (hard 422)

Skill text still says `ASC`/`DESC`. Live enum is **lowercase only**:
`asc | desc`. Uppercase returns code 100. MCP validated and (when non-default)
sent uppercase. Default path omitted the param when `DESC`, so newest-first still
worked — oldest-first did not.

### 4. Docs and type vocabulary lag

Realtime live shape included `latest_file`, `start_time`, `end_time`, `tz`,
`location` — models still had `timestamp` / `detected_at`. Journal types expanded
with `COMIC_PAGE`, `WEEKLY_JOURNAL`, `SYSTEM_POST` (and STORYBOARD/DAILY_ROUTINE
were rare or absent in the July sample). Location fields were often **JSON
strings** of address parts, not `{lat, lng}` objects — bad for geo clustering.

## From Report to Run-Pack (RP-57)

The discovery closed as a recommended priority table. The operator asked to file
each item as OBs under a linked project for ProjectWorker. That produced:

| Field | Value |
|---|---|
| Track | `looki-mcp-api-contract-parity` |
| Display | **RP-57** |
| Kind | `repo_project` |
| UUID | `4d4f9d95-4f4e-474b-adcc-2041ea805956` |

| Pri | OB | Title |
|---|---|---|
| P0 | **OB-52625** | `extract_video_frames` duration under `metadata` |
| P0 | **OB-52626** | highlights `group` → `all\|vlog\|other` |
| P0 | **OB-52627** | journals `sort_order` → lowercase wire |
| P1 | **OB-52628** | models.py + findings refresh |
| P2 | **OB-52629** | geo JSON location normalize |
| P3 | **OB-52630** | skill-hash / live re-probe harness |

Each OB body carried a full agent implementation brief (problem, root cause,
repro, files, steps, tests, acceptance, deploy, blast radius). All six tagged
`autonomous_safe`, status `triaged`, linked with relationship `advances`. Repo +
skill URL linked as evidence.

## Implementation (batched ship)

Suggested drain order was six independent PRs. In practice the fixes were small,
non-conflicting, and production was already behind on mainline insight work, so
they shipped as **one pack** with six separate verified closes:

### Code

| Change | Where |
|---|---|
| `file_duration_ms` / `file_dimensions` | new `looki_mcp/file_helpers.py` — metadata first, top-level fallback |
| `extract_video_frames` | uses helpers; frames inherit width/height when present |
| `VALID_GROUPS` / `validate_highlights_group` | `looki_mcp/tools/highlights.py` |
| `normalize_sort_order` | `looki_mcp/tools/journals.py` — accepts ASC/DESC aliases, wires `asc`/`desc`, omits param for default desc |
| models + findings | `looki_mcp/models.py`, `journals_api_findings.md` dated 2026-07-18 |
| geo | `normalize_location` / `parse_location_display` parse address JSON → locality keys |
| harness | `scripts/api_contract_probe.py` (`--skill-only` or full live) |

### Tests (standalone scripts, no pytest)

- `scripts/test_video_duration.py`
- `scripts/test_highlights_group.py`
- `scripts/test_journals_sort_order.py`
- `scripts/test_geo.py` (JSON Quincy fixture)
- Live: `api_contract_probe.py` — all known paths OK; comic/ASC rejected; FileModel `metadata_present=True`

### Production

Prod still lived at `/services/looki-mcp` (systemd), historically on **`master`**,
while the projects tree had moved through insight PR1 on **`main`**. The pack was
applied onto the prod checkout first so the running MCP would fix without waiting
for a full PR2 stack (prod tool count stayed **24** — journals era, not the 27
insight tools sitting on an unmerged PR2 branch).

- Prod commit after rebase onto `origin/master`: **`5969890`**
  `fix(api-contract): RP-57 Looki Open API parity (OB-52625–52630)`
- `sudo systemctl restart looki-mcp`
- Health: `GET http://127.0.0.1:7861/health` →
  `{"status":"ok","server":"looki-mcp","version":"1.0.0","tools":24}`
- All six OBs closed via `nexus_ob_close_verified` with tests/smoke/deploy evidence

Projects-side branch `fix/rp57-api-contract-parity` @ **`3a2cb42`** carried the
same pack on top of the unmerged PR2 insight tools tip — a parallel lineage, not
what prod ran.

## Closing the Git Gap

After deploy, the honest status was: **live and tested, not fully git-hygienic**.
Feature branch had no upstream; prod `master` was ahead of `origin/master` until
rebase + push.

### Push and merge

1. Pushed `fix/rp57-api-contract-parity` → origin.
2. Rebased prod's RP-57 commit onto `origin/master` (which had one docs commit
   `074b933` prod lacked) → **`5969890`**, then `git push origin master`.
3. Merged `origin/master` into `main` (main already carried insight-magic PR1;
   merge was clean on `insight/__init__.py`) → **`4f4bd2a`**
   `Merge master: RP-57 Looki Open API contract parity`, pushed to `origin/main`.
4. Confirmed `origin/master` is an ancestor of `origin/main`.

### Branch cleanup and the end of master

Operator policy here is **main only**. June's shipping narrative had left the
default-branch quirk flagged; this session killed it.

| Action | Result |
|---|---|
| GitHub default branch | **`main`** (`gh api -X PATCH … default_branch=main`) |
| Delete `origin/master` | done |
| Prod checkout | `/services/looki-mcp` → **`main` @ `4f4bd2a`**, tracks `origin/main` |
| Projects checkout | **`main` only** |
| Remote feature branches | deleted (`fix/rp57…`, `feat/insight-magic-tools`) |
| Unmerged PR2 tip | **not** forced onto main; tagged `archive/feat-insight-tools-pr2` and `archive/fix-rp57-api-contract-parity` for recovery |

PR2 (commitment_harvester / the_unwritten / places_of_my_life — tool count 24→27)
remains recoverable:

```bash
git checkout -b feat/insight-tools-pr2 archive/feat-insight-tools-pr2
```

It was deliberately **not** deployed in this arc: prod stayed at 24 tools; the
contract fixes did not depend on the composite insight tools.

### Final topology (2026-07-18 evening)

| Surface | Branch | SHA | Notes |
|---|---|---|---|
| GitHub default | `main` | `4f4bd2a` | only remote branch |
| Projects | `main` | `4f4bd2a` | tracks `origin/main` |
| Prod `/services/looki-mcp` | `main` | `4f4bd2a` | systemd WorkingDirectory |
| Service | active | — | `:7861`, origin-secret on, tools:24 |

Worktrees: only the projects tree and the services tree. No orphan feature
worktrees.

## What the Probe Harness Is For

`scripts/api_contract_probe.py` exists so the next drift is not a full discovery
session. Modes:

```bash
.venv/bin/python scripts/api_contract_probe.py --skill-only   # hash + path list
set -a; source .env; set +a
.venv/bin/python scripts/api_contract_probe.py                # live matrix + enums
```

It pins baseline skill prefix `4c5c991cb1165b91`, prints a known-path matrix,
asserts invalid `group=comic` and `sort_order=ASC` still fail, and samples one
moments file for `metadata` presence. Rate-limit friendly (serial GETs). Never
prints the API key.

## Alternatives Rejected

| Idea | Why not |
|---|---|
| Add MCP tools for SPA `/loom`, `/albums`, … | Private app API; 404 on Open platform |
| Treat 422 path segments as new endpoints | Path-param UUID validation, not routes |
| Ship PR2 insight tools with RP-57 | Separate product arc; prod was journals/24-tool baseline |
| Keep dual `main`/`master` default | Operator: "we only use main here" |
| Six separate PRs / worktrees | Low conflict surface; batched with per-OB close evidence |

## Numbers Worth Keeping

| Observation | Value |
|---|---|
| Open API authenticated routes (skill + live) | **12** |
| New routes needing tools | **0** |
| OBs in RP-57 | **6** (52625–52630), all `done` |
| Prod tool count after ship | **24** (unchanged) |
| Skill sha256 prefix | `4c5c991cb1165b91` |
| Sample video duration from metadata | `5046` ms |
| Live invalid enum checks | comic → code 100; ASC → code 100 |
| Final main SHA | `4f4bd2a` |
| RP-57 on master lineage (pre-delete) | `5969890` |

## What Is Unblocked / Still Pending

**Unblocked**

- Video frame sampling uses real durations again.
- Agents cannot send invalid highlight groups or uppercase journal sort orders.
- Models and findings match live shapes enough for the next implementer.
- Geo clustering can key Quincy from a JSON address string, not the raw blob.
- A one-command re-probe exists when Looki ships skill changes.
- Git topology matches policy: **main only**, prod on main, default branch main.

**Pending (out of this arc)**

- Land PR2 insight tools from `archive/feat-insight-tools-pr2` when ready (24→27).
- Optionally close RP-57 project track in Nexus (OBs done; track may stay active).
- Re-run live probe after any skill hash prefix change.

See `CHANGES.md` entry **2026-07-18 — Open API contract parity (RP-57)** for the
chronological pointer.
