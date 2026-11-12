# OB-69849: Moment file pagination follows the live cursor contract

## Problem

The live `GET /moments/{id}/files` contract changed both sides of pagination.
It returns `next_cursor` and expects the next request to send `cursor`. The old
`next_cursor_id` / `cursor_id` pair stopped pagination. A response-only fix
would repeat page one because the old request parameter is silently ignored
upstream.

## Change

`looki_mcp/insight/scan.py::walk_files` now reads `next_cursor` and sends
`cursor`. Its deterministic fixture covers the new response shape, verifies
the second and third requests carry the returned cursor, and keeps checks for
no-more-pages and the existing call budget. The `/journals` walker continues
to use the date-valued `next_cursor_id` contract. Documentation files owned by
sibling OB-69846 are unchanged.

## Verification

Run `.venv/bin/python scripts/test_scan.py`. The test uses a synthetic HTTPX
transport; the live key/parameter observations are recorded in OB-69849's
ProjectInvestigator evidence from 2026-11-09. No credentials or live payloads
are part of the fixture.
