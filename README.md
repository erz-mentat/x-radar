# x-radar

Minimal X (Twitter) CLI. Pulls tweets, shows metrics, estimates API cost.

## Requirements

- Python 3.7+
- X API bearer token (free tier works)

## Setup

**Linux / macOS:**
```bash
export X_BEARER_TOKEN=your_token_here
```

**Windows:**
```cmd
set X_BEARER_TOKEN=your_token_here
```

## Usage

```bash
# From repo root (x-radar):
python skill/scripts/x_search.py user-tweets --username "garrytan" --sort recent --limit 10
python skill/scripts/x_search.py search --query "from:garrytan" --sort likes --min-likes 5 --limit 5
python skill/scripts/x_search.py tweet --id 2021586493215519140
```

If you are inside `x-radar/skill`, drop the `skill/` prefix:

```bash
python scripts/x_search.py user-tweets --username "garrytan" --sort recent --limit 10
```

## Output

JSON with tweet text, public metrics (likes / replies / retweets / impressions), and a cost estimate.

## Cache

Stored at `%LOCALAPPDATA%\x-radar\cache` (Windows) or `~/.cache/x-radar/cache`.
Override with `X_RADAR_CACHE_DIR`.
Fallback env var: `X_SCOUT_CACHE_DIR`.

## Reliability

- Structured JSON errors for invalid arguments and API/network failures.
- Cost numbers are estimates only.
- Pricing assumptions in code were last reviewed on `2026-02-13`.

## Tests

```bash
python -m unittest -v tests/smoke_test.py
```

## Notes

- Read-only. Does not post.
- No external dependencies - stdlib only.
- Never commit your token.

## License

MIT
