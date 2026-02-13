---
name: x-radar
description: "Scout current X (Twitter) posts and accounts for networking and engagement. Provides: (1) up-to-date post links, (2) quick summaries + public metrics, (3) copy-paste reply suggestions in David's short, declarative style (no em-dash), (4) a lightweight engagement tracker workflow, and (5) optional X API v2 querying via bearer token (no secrets in repo)."
---

# X Radar

Workflow: **Find current posts -> write high-signal replies -> track -> warm DM later**.

## 0) Style constraints (Replies)
- short, declarative
- lowercase ok
- 1 mechanism > 1 compliment
- max 1 question
- no em-dash

## 1) Get current posts (fast)
### Option A: Browser Relay
- Open target profile on X
- Pick a fresh post (hours, not days)
- Copy the post URL

### Option B: X API v2 (script)
Use when you have `X_BEARER_TOKEN` set.

Default: use `--quick` for cheap tests.

Run from this skill directory (`x-radar/skill`):
```powershell
python scripts/x_search.py user-tweets --username "samuelrdt" --sort recent --limit 10
python scripts/x_search.py search --query "from:contrary" --quick --sort likes --min-likes 5 --limit 5
```

Run from repo root (`x-radar`):
```powershell
python skill/scripts/x_search.py user-tweets --username "samuelrdt" --sort recent --limit 10
python skill/scripts/x_search.py search --query "from:contrary" --quick --sort likes --min-likes 5 --limit 5
```

Caching:
- automatic file cache (outside the skill folder)
- default dir: `%LOCALAPPDATA%\x-radar\cache` (Windows)
- override with env var: `X_RADAR_CACHE_DIR` (fallback: `X_SCOUT_CACHE_DIR`)
- TTL: 15 min (search), 1h in `--quick`
- cache hits report estimated cost = 0

Never commit tokens. Use env vars.

## 2) Write replies (David style)
Reply templates:
- frame correction: `X is the wrong frame. Y.`
- moat statement: `ui is the easy win. infra is the moat.`
- mechanism: `schema + tests + traceability > vibes`

## 3) Track engagement
Use the included template: `skill/engagement-tracker.md`

Fields: target, post URL, your reply, date, status, next move.

Rule: wait 24-48h. If they reply/like, do 1 follow-up. Then warm DM/email.
