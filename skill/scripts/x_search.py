"""x_search.py

X (Twitter) v2 scouting CLI (x-radar).

Goals:
- find current posts fast
- sort/filter by engagement or recency
- show cost transparency (estimates)

Stdlib only (urllib). Requires env var: X_BEARER_TOKEN.

Examples:
  python scripts/x_search.py search --query "civic tech" --quick --sort likes --min-likes 10 --limit 10
  python scripts/x_search.py user-tweets --username "samuelrdt" --sort recent --limit 10
  python scripts/x_search.py tweet --id 2021125408075415667

Notes:
- Read-only. Never posts.
- Do NOT commit tokens.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.parse
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

API = "https://api.x.com/2"


def _default_cache_dir() -> Path:
    # Keep runtime cache OUTSIDE the skill folder so packaging/commits stay clean.
    # Windows: %LOCALAPPDATA%\x-radar\cache
    # Others:  ~/.cache/x-radar/cache
    lad = os.getenv("LOCALAPPDATA")
    if lad:
        return Path(lad) / "x-radar" / "cache"
    return Path.home() / ".cache" / "x-radar" / "cache"


CACHE_DIR = Path(
    os.getenv("X_RADAR_CACHE_DIR")
    or os.getenv("X_SCOUT_CACHE_DIR")
    or _default_cache_dir()
)

# Rough pricing model (estimate)
# Source: user-provided pricing notes / typical X API v2 pay-per-use figures.
COST_POST_READ_USD = 0.005
COST_USER_LOOKUP_USD = 0.010
# Last reviewed on 2026-02-13. Update these assumptions when your X API plan changes.
PRICING_LAST_REVIEWED_UTC = "2026-02-13"


class XRadarError(RuntimeError):
    """User-facing runtime error for predictable CLI failures."""


def _bearer() -> str:
    token = os.getenv("X_BEARER_TOKEN") or os.getenv("TWITTER_BEARER_TOKEN")
    if not token:
        raise XRadarError("Missing X_BEARER_TOKEN env var")
    return token


def _cache_key(url: str) -> str:
    # Stable file name for a request URL
    import hashlib

    return hashlib.sha256(url.encode("utf-8")).hexdigest()


def _cache_path(url: str) -> Path:
    return CACHE_DIR / f"{_cache_key(url)}.json"


def _read_cache(url: str, ttl_seconds: int) -> Optional[Dict[str, Any]]:
    try:
        p = _cache_path(url)
        if not p.exists():
            return None
        age = (datetime.now(timezone.utc) - datetime.fromtimestamp(p.stat().st_mtime, tz=timezone.utc)).total_seconds()
        if age > ttl_seconds:
            return None
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None


def _write_cache(url: str, obj: Dict[str, Any]) -> None:
    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        _cache_path(url).write_text(json.dumps(obj, ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass


def _get(url: str, *, cache_ttl_seconds: int = 900, no_cache: bool = False) -> Tuple[Dict[str, Any], bool]:
    if not no_cache and cache_ttl_seconds > 0:
        cached = _read_cache(url, cache_ttl_seconds)
        if cached is not None:
            return cached, True

    req = urllib.request.Request(url)
    req.add_header("Authorization", f"Bearer {_bearer()}")
    req.add_header("User-Agent", "x-radar/0.3")
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            data = resp.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        detail = "no additional details"
        try:
            body = exc.read().decode("utf-8", errors="replace")
            if body:
                try:
                    err_obj = json.loads(body)
                    if isinstance(err_obj, dict):
                        errors = err_obj.get("errors")
                        if isinstance(errors, list) and errors and isinstance(errors[0], dict):
                            detail = str(errors[0].get("message") or errors[0].get("detail") or errors[0].get("title") or detail)
                        else:
                            detail = str(err_obj.get("detail") or err_obj.get("title") or err_obj.get("error") or detail)
                except Exception:
                    compact = " ".join(body.split())
                    if compact:
                        detail = compact[:160]
        except Exception:
            pass
        raise XRadarError(f"X API request failed ({exc.code} {exc.reason}): {detail}") from None
    except urllib.error.URLError as exc:
        raise XRadarError(f"Network error while calling X API: {exc.reason}") from None
    except TimeoutError:
        raise XRadarError("Request to X API timed out") from None

    try:
        obj = json.loads(data)
    except json.JSONDecodeError:
        raise XRadarError("X API returned invalid JSON response") from None

    if not no_cache and cache_ttl_seconds > 0:
        _write_cache(url, obj)

    return obj, False


def _parse_since(value: str) -> timedelta:
    raw = value.strip().lower()
    if raw.endswith("h"):
        return timedelta(hours=float(raw[:-1]))
    if raw.endswith("d"):
        return timedelta(days=float(raw[:-1]))
    raise ValueError("--since must be like 1h, 3h, 12h, 1d, 7d")


def _to_iso_utc(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _metric(tweet: Dict[str, Any], key: str) -> int:
    metrics = tweet.get("public_metrics") or {}
    val = metrics.get(key)
    try:
        return int(val or 0)
    except (TypeError, ValueError):
        return 0


def _created_at(tweet: Dict[str, Any]) -> str:
    # ISO 8601 string; lexicographic works for UTC timestamps.
    return str(tweet.get("created_at") or "")


def _sort_key(tweet: Dict[str, Any], sort: str) -> Tuple:
    s = sort.lower()
    if s == "likes":
        return (_metric(tweet, "like_count"), _metric(tweet, "reply_count"), _created_at(tweet))
    if s == "replies":
        return (_metric(tweet, "reply_count"), _metric(tweet, "like_count"), _created_at(tweet))
    if s == "retweets":
        return (_metric(tweet, "retweet_count"), _metric(tweet, "like_count"), _created_at(tweet))
    # default: recent
    return (_created_at(tweet),)


def _filter_tweets(
    tweets: List[Dict[str, Any]],
    *,
    min_likes: int = 0,
    min_replies: int = 0,
    min_retweets: int = 0,
) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for t in tweets:
        if _metric(t, "like_count") < min_likes:
            continue
        if _metric(t, "reply_count") < min_replies:
            continue
        if _metric(t, "retweet_count") < min_retweets:
            continue
        out.append(t)
    return out


@dataclass
class CostEstimate:
    requests: int
    post_reads: int
    user_lookups: int

    @property
    def usd(self) -> float:
        return self.post_reads * COST_POST_READ_USD + self.user_lookups * COST_USER_LOOKUP_USD

    def as_dict(self) -> Dict[str, Any]:
        return {
            "requests": self.requests,
            "post_reads": self.post_reads,
            "user_lookups": self.user_lookups,
            "estimated_usd": round(self.usd, 3),
            "assumptions": {
                "post_read_usd": COST_POST_READ_USD,
                "user_lookup_usd": COST_USER_LOOKUP_USD,
                "pricing_last_reviewed_utc": PRICING_LAST_REVIEWED_UTC,
                "note": "Estimate only. Actual X billing may differ by tier/resource.",
            },
        }


def search_recent(
    query: str,
    *,
    limit: int = 15,
    sort: str = "likes",
    since: Optional[str] = None,
    min_likes: int = 0,
    min_replies: int = 0,
    min_retweets: int = 0,
    quick: bool = False,
) -> Dict[str, Any]:
    q = query

    # quick mode: cheap pulse check
    if quick:
        # Default noise filters unless the user explicitly asked for replies/retweets.
        ql = q.lower()
        if "is:retweet" not in ql and "-is:retweet" not in ql:
            q += " -is:retweet"
        if "is:reply" not in ql and "-is:reply" not in ql:
            q += " -is:reply"
        if not since:
            since = "24h"

    if since:
        delta = _parse_since(since)
        start_time = _to_iso_utc(datetime.now(timezone.utc) - delta)
    else:
        start_time = None

    # Fetch results; in quick mode we request fewer items.
    max_results = 10 if quick else 100
    qp = {
        "query": q,
        "max_results": str(max_results),
        "tweet.fields": "created_at,public_metrics,author_id,conversation_id",
        "expansions": "author_id",
        "user.fields": "username,name,verified",
    }
    if start_time:
        qp["start_time"] = start_time

    url = f"{API}/tweets/search/recent?{urllib.parse.urlencode(qp)}"
    ttl = 3600 if quick else 900
    raw, cache_hit = _get(url, cache_ttl_seconds=ttl)

    tweets = list(raw.get("data") or [])
    tweets = _filter_tweets(tweets, min_likes=min_likes, min_replies=min_replies, min_retweets=min_retweets)
    tweets.sort(key=lambda t: _sort_key(t, sort), reverse=True)
    tweets = tweets[: max(1, int(limit))]

    cost = CostEstimate(requests=0 if cache_hit else 1, post_reads=0 if cache_hit else len(raw.get("data") or []), user_lookups=0)

    return {
        "x_radar": {
            "mode": "search",
            "query": q,
            "since": since,
            "sort": sort,
            "quick": bool(quick),
            "filters": {"min_likes": min_likes, "min_replies": min_replies, "min_retweets": min_retweets},
            "returned": len(tweets),
            "cost": cost.as_dict(),
        },
        "data": tweets,
        "includes": raw.get("includes"),
        "meta": raw.get("meta"),
    }


def user_by_username(username: str, *, cache_ttl_seconds: int = 900, no_cache: bool = False) -> Tuple[Dict[str, Any], bool]:
    u = username.lstrip("@")
    url = f"{API}/users/by/username/{urllib.parse.quote(u)}?user.fields=public_metrics,verified,created_at"
    return _get(url, cache_ttl_seconds=cache_ttl_seconds, no_cache=no_cache)


def tweet_by_id(tweet_id: str, *, cache_ttl_seconds: int = 900, no_cache: bool = False) -> Tuple[Dict[str, Any], bool]:
    tid = urllib.parse.quote(str(tweet_id))
    qp = {
        "ids": tid,
        "tweet.fields": "created_at,public_metrics,author_id,conversation_id",
        "expansions": "author_id",
        "user.fields": "username,name,verified",
    }
    url = f"{API}/tweets?{urllib.parse.urlencode(qp)}"
    return _get(url, cache_ttl_seconds=cache_ttl_seconds, no_cache=no_cache)


def user_tweets(
    username: str,
    *,
    limit: int = 10,
    sort: str = "recent",
    min_likes: int = 0,
    min_replies: int = 0,
    min_retweets: int = 0,
) -> Dict[str, Any]:
    user_raw, cache_hit_user = user_by_username(username)
    user_id = user_raw.get("data", {}).get("id")
    if not user_id:
        return {"error": "user not found", "user": user_raw}

    max_results = 100
    url = (
        f"{API}/users/{user_id}/tweets?max_results={max_results}"
        f"&tweet.fields=created_at,public_metrics,conversation_id"
        f"&exclude=replies,retweets"
    )
    raw, cache_hit_tweets = _get(url, cache_ttl_seconds=900)

    tweets = list(raw.get("data") or [])
    tweets = _filter_tweets(tweets, min_likes=min_likes, min_replies=min_replies, min_retweets=min_retweets)
    tweets.sort(key=lambda t: _sort_key(t, sort), reverse=True)
    tweets = tweets[: max(1, int(limit))]

    requests = (0 if cache_hit_user else 1) + (0 if cache_hit_tweets else 1)
    cost = CostEstimate(
        requests=requests,
        post_reads=0 if cache_hit_tweets else len(raw.get("data") or []),
        user_lookups=0 if cache_hit_user else 1,
    )

    return {
        "x_radar": {
            "mode": "user-tweets",
            "username": username,
            "sort": sort,
            "filters": {"min_likes": min_likes, "min_replies": min_replies, "min_retweets": min_retweets},
            "cache": {"user_lookup_hit": bool(cache_hit_user), "tweets_hit": bool(cache_hit_tweets)},
            "returned": len(tweets),
            "cost": cost.as_dict(),
        },
        "user": user_raw.get("data"),
        "data": tweets,
        "meta": raw.get("meta"),
    }


def _positive_int(value: str) -> int:
    try:
        n = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be an integer") from exc
    if n < 1:
        raise argparse.ArgumentTypeError("must be >= 1")
    return n


def _non_negative_int(value: str) -> int:
    try:
        n = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be an integer") from exc
    if n < 0:
        raise argparse.ArgumentTypeError("must be >= 0")
    return n


def _write_json(obj: Dict[str, Any]) -> None:
    # Windows terminals can choke on unicode (cp1252). Force UTF-8 stdout.
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    json.dump(obj, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")


def _error_payload(code: str, message: str) -> Dict[str, Any]:
    return {"error": {"code": code, "message": message}}


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("search", help="Search recent posts")
    s.add_argument("--query", required=True)
    s.add_argument("--limit", type=_positive_int, default=15)
    s.add_argument("--sort", choices=["likes", "replies", "retweets", "recent"], default="likes")
    s.add_argument("--since", help="Time window like 1h, 3h, 12h, 1d, 7d")
    s.add_argument("--min-likes", type=_non_negative_int, default=0)
    s.add_argument("--min-replies", type=_non_negative_int, default=0)
    s.add_argument("--min-retweets", type=_non_negative_int, default=0)
    s.add_argument("--quick", action="store_true", help="Cheap pulse check (defaults: since=24h, -is:reply, -is:retweet, max_results=10)")

    t = sub.add_parser("tweet", help="Fetch a single tweet by id")
    t.add_argument("--id", required=True, help="Tweet id")
    t.add_argument("--no-cache", action="store_true")

    u = sub.add_parser("user-tweets", help="Get recent tweets from a username")
    u.add_argument("--username", required=True)
    u.add_argument("--limit", type=_positive_int, default=10)
    u.add_argument("--sort", choices=["likes", "replies", "retweets", "recent"], default="recent")
    u.add_argument("--min-likes", type=_non_negative_int, default=0)
    u.add_argument("--min-replies", type=_non_negative_int, default=0)
    u.add_argument("--min-retweets", type=_non_negative_int, default=0)

    args = p.parse_args(argv)

    try:
        if args.cmd == "search":
            out = search_recent(
                args.query,
                limit=args.limit,
                sort=args.sort,
                since=args.since,
                min_likes=args.min_likes,
                min_replies=args.min_replies,
                min_retweets=args.min_retweets,
                quick=args.quick,
            )
        elif args.cmd == "tweet":
            raw, cache_hit = tweet_by_id(args.id, cache_ttl_seconds=900, no_cache=args.no_cache)
            # cost estimate: one tweet read if not cached
            out = {
                "x_radar": {
                    "mode": "tweet",
                    "id": str(args.id),
                    "cache_hit": bool(cache_hit),
                    "cost": CostEstimate(requests=0 if cache_hit else 1, post_reads=0 if cache_hit else 1, user_lookups=0).as_dict(),
                },
                "data": (raw.get("data") or []),
                "includes": raw.get("includes"),
                "errors": raw.get("errors"),
            }
        else:
            out = user_tweets(
                args.username,
                limit=args.limit,
                sort=args.sort,
                min_likes=args.min_likes,
                min_replies=args.min_replies,
                min_retweets=args.min_retweets,
            )
    except ValueError as exc:
        _write_json(_error_payload("invalid_arguments", str(exc)))
        return 2
    except XRadarError as exc:
        _write_json(_error_payload("runtime_error", str(exc)))
        return 1
    except Exception as exc:
        _write_json(_error_payload("internal_error", f"{type(exc).__name__}: {exc}"))
        return 1

    _write_json(out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
