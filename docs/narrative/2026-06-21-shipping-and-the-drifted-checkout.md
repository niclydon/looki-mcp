# Shipping Through a Drifted Checkout

The journals work was built, reviewed twice, and verified against live
infrastructure. None of that put it in front of the user. The code sat in the
working tree of `~/projects/looki-mcp`, and the production MCP that claude.ai
actually talks to — a separate systemd service on port 7861 — was still serving
fourteen tools from old code. Shipping the remaining ten tools meant a commit, a
merge, a push, and a redeploy. Each of those four steps turned up something the
repo had been quietly hiding: a remote whose default branch wasn't the one the
local branch was named after, and a production checkout that had been used as a
scratch workspace until it drifted off the mainline entirely.

This is the record of getting 14 → 24 tools from a clean working tree onto a live
service on 2026-06-21, and the two surprises that made a routine deploy a careful
one.

## The Commit, on a Branch

The session was on `main`. Policy and reflex agree on the same move: don't commit
to the mainline directly. So the work went onto a feature branch,
`feat/journals-api-and-media-capture`, as a single commit `87dfeb7` — the eight
journals tools, the two capture tools, `storage.py`, the reference models, three
test scripts, and the docs. Then `main` took the branch back with `git merge
--no-ff`, producing merge commit `45f963c` and matching the repo's existing
history, which already carried `--no-ff` merges like `e65bd19 Merge branch
'fix/tool-docs-tests-sync'`. The local feature branch was deleted after the merge.

Before any of it, a check that costs nothing and saves reputations: grep the
to-be-committed files for real secrets. The earlier probing had pasted journal
JSON into scratch files, and the findings doc and narrative both mention the
string `x-looki-token` by name. The grep confirmed what mattered — the *param
name* appears, but no `eyJ…` JWT value, no `lk-` API key, no MinIO secret, and
`.env` was gitignored. Clean to commit.

## The Push That Landed on the Wrong Branch

`git push origin HEAD` reported `e608fbb..45f963c  HEAD -> main`. Then the status
line contradicted the success: `## main...origin/master [ahead 2]`. The push had
updated `origin/main`, but the local branch's *upstream* was `origin/master`, and
that was still two commits behind.

`git ls-remote --symref origin HEAD` settled it:

```
ref: refs/heads/master	HEAD
```

The remote's default branch is **`master`**. The local branch is named `main` and
tracks `origin/master` — a leftover from some past rename that never fully took.
So the first push had updated a stale mirror (`origin/main`) and left the actual
default (`origin/master`, still at `e608fbb`) untouched. Anything that reads the
repo's default — GitHub's UI, a fresh clone, a deploy that pulls `master` — would
have seen none of the work.

The fix was a second push to the branch that mattered. `e051150` — no, the merge
commit `45f963c` — fast-forwarded cleanly because `origin/master`'s `e608fbb` was
its ancestor: `git push origin main:master` →  `e608fbb..45f963c  main -> master`.
Both `origin/main` and `origin/master` now point at `45f963c`, so whichever name
a tool reaches for, it finds the work. The naming quirk was left in place — it
wasn't the operator's ask to rename a default branch — but flagged for later
tidy-up.

## The Deploy That Found a Diverged Production

The production service is described by `/etc/systemd/system/looki-mcp.service`:
`User=niclydon`, `WorkingDirectory=/services/looki-mcp`,
`EnvironmentFile=/services/looki-mcp/.env`,
`ExecStart=/services/looki-mcp/.venv/bin/python main.py`, with a restart-policy
drop-in added 2026-05-18 (`Restart=always`, after a SIGTERM-treated-as-clean-exit
incident left several MCPs dead for 9.5 hours). A plain redeploy should have been
`git pull`, install the new dep, restart.

`git status` in `/services/looki-mcp` refused to be that simple:

```
On master, HEAD e051150
 M looki_mcp/server.py
 M looki_mcp/tools/realtime.py
 M main.py
 M README.md
 M systemd/looki-mcp.service
 M .gitignore
?? LICENSE
?? looki_mcp/tools/video.py
```

The checkout was on `master` at `e051150` — not the `e608fbb` tip the rest of the
repo had reached — with a dirty working tree. This is the anti-pattern the
workspace policy names explicitly: the canonical/deploy checkout treated as a
scratchpad. Production had been deployed at some point by editing files in place
rather than pulling commits, and the mainline had moved on without it. `git pull`
into that would either conflict or silently clobber whichever side lost.

So the deploy stopped being a `pull` and became a reconciliation. The question
that decided everything: were those uncommitted edits *prod-unique* (something
that existed nowhere in history and had to survive), or merely *superseded* (older
hand-applied versions of features that were later committed upstream)?

The evidence pointed at superseded. `git merge-base --is-ancestor HEAD
origin/master` returned true — `e051150` was an ancestor of the new tip, so a
fast-forward was geometrically possible. The dirty files — `realtime.py`,
`server.py`, `video.py`, `README.md` — all named features that the upstream
history already carried in fuller, reviewed form (the realtime Forge tracing, the
14-tool server, `extract_video_frames`, the docs). And critically, the one thing
that *is* prod-unique — the real credentials — lives in `.env`, which is
gitignored and therefore outside the entire question.

## Reconciling Without Losing Anything

The reconciliation was built to be reversible at every step.

First, capture a baseline and a backup. `curl localhost:7861/health` confirmed the
service was serving `"tools":14` before the deploy. A full tarball of the working
tree (minus `.venv`) went to `/tmp/looki_prod_backup_predeploy.tar.gz`, and the
old HEAD `e051150` was recorded.

Then preserve the drift instead of discarding it. `git stash push -u` saved the
six modified files plus the two untracked ones as
`stash@{0}: prod-drift-pre-journals-deploy-e051150`. Because `.env` is gitignored,
`stash -u` left it untouched — verified immediately afterward by re-reading its
keys. Inspecting the stash showed exactly what was expected: 125 insertions across
`realtime.py`, `README.md`, `server.py`, `main.py`, the systemd template, and a
`.gitignore` that added `tmp/`, `.claude/`, `.remember/`. All superseded code,
nothing prod-unique. (The systemd file in the repo is a *template* anyway; the
live unit is the separate file under `/etc/systemd/system/`, so editing the repo
copy never touched the running service.)

With the tree clean at `e051150`, `git merge --ff-only origin/master` fast-forwarded
production to `45f963c` — no conflicts, by construction. `TOOL_COUNT = 24`,
`storage.py` and `tools/journals.py` present, working tree clean.

The config and dependency steps followed. The crucible MinIO credentials were
appended to `/services/looki-mcp/.env` as `MINIO_ENDPOINT` /
`MINIO_ACCESS_KEY` / `MINIO_SECRET_KEY` / `MINIO_BUCKET=looki-journal-media`,
sourced from `~/.mc/config.json` and never printed; the six existing
`LOOKI_*`/`ORIGIN_*` keys were preserved. `boto3 1.43.34` went into the prod
venv. A `py_compile` over the three changed modules passed.

Then `sudo systemctl restart looki-mcp` (passwordless sudo was available;
restarting a system unit needs it even when the unit runs as `niclydon`). Health
came back in four seconds: `"tools":24`. `NRestarts: 0` — no crash loop. The
journal showed a clean Uvicorn start on `http://0.0.0.0:7861/mcp`, the
origin-secret guard enabled, and the public URL `https://looki-mcp.niclydon.io/mcp`.

## Proving It Through the Guard

A health check proves the process started. It does not prove the tools work, and
it especially does not prove that MinIO capture — which depends on the prod `.env`
being parsed correctly by both systemd's `EnvironmentFile` and the app's dotenv
load — actually functions in the production envelope.

Production runs with the origin-secret guard *enabled*, so every `/mcp` call must
carry an `x-origin-secret` header; only `/health` and `/logo.ico` are exempt. The
verification read `ORIGIN_SHARED_SECRET` straight out of the prod `.env` into the
process environment (never echoed), built a `StreamableHttpTransport` with that
header, and drove the real production MCP:

- 24 tools listed; `capture_journal_media` and `get_recent_journals` among them.
- `get_journals` returned data — 22 entries with media in the recent window.
- `capture_journal_media` came back **not** `disabled`, which is the single fact
  that proves prod loaded `MINIO_*` from its `.env`. Bucket `looki-journal-media`,
  zero failures.

The capture reported `already_captured=1` rather than a fresh `captured`. That is
not a failure — it is the idempotency working across environments. The same image
had been stored during the dev-instance testing earlier in the session; the
deterministic key (`journals/<date>/<journal_id>/<idx>_source.jpg`) meant
production recognized it was already there and skipped the download. Thirteen
objects sit in the bucket. The service stayed `active`, `NRestarts: 0`.

## What This Cost, and What It Taught

The deploy itself was minutes. The care was the point. Two latent repo conditions
— a remote default branch that didn't match the local branch name, and a
production checkout that had drifted off the mainline by being edited in place —
each had a clean failure mode (work pushed to a mirror nobody reads; a `git pull`
clobbering live state) that only surfaced because the steps were checked rather
than assumed.

The `current-policy.md` workspace doctrine had already written the lesson down,
from a 2026-05-29 incident where an interactive session treating a canonical
checkout as a workspace clobbered a merged helper, and a deploy-side `git stash`
once wiped another session's uncommitted narrative docs. `/services/looki-mcp` is
exactly that hazard in standing form: a deploy checkout carrying uncommitted WIP.
This deploy survived it only because the WIP was superseded and the real config
was gitignored — luck the policy would rather not depend on. The durable fix,
recorded in project memory, is to stop deploying by editing in place: pull commits,
keep the deploy checkout clean, and let `.env` be the only thing that differs
between the repo and the running service.

The operator drove the commit/merge/push directly, which the policy permits — the
operator is the serialization point. The 24 tools, including durable journal-image
capture to crucible, are live in the connected Looki MCP.

See `CHANGES.md` for the chronological per-phase summary, and
`docs/narrative/2026-06-21-journals-api-and-media-capture.md` for the build that
preceded this ship.
