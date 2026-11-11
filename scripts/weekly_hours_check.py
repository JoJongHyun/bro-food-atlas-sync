#!/usr/bin/env python3
"""One-place weekly-hours source check, with bounded 429 handling.

This is a diagnostic, not a licensed data feed or a site-data writer.
Do not retry through alternate IPs, headers, proxies, or endpoints.
"""
import datetime as dt
import email.utils
import json
import os
import sys
import time
import urllib.error
import urllib.request

ENDPOINT = "https://pcmap-api.place.naver.com/place/graphql"
QUERY = (
    "query getPlaceDetail($input: PlaceDetailInput!) { placeDetail(input: $input) "
    "{ newBusinessHours { businessStatusDescription { description status } "
    "businessHours { day businessHours { start end } breakHours { start end } } } } }"
)

def summary(message):
    print(message, flush=True)
    summary_path = os.getenv("GITHUB_STEP_SUMMARY")
    if summary_path:
        with open(summary_path, "a", encoding="utf-8") as fp:
            fp.write(message + "\n")

def checkpoint(sid, outcome, **details):
    data = {
        "sid": sid,
        "status": outcome,
        "checkedAt": dt.datetime.now(dt.timezone.utc).isoformat(),
        **details,
    }
    with open("weekly-hours-checkpoint.json", "w", encoding="utf-8") as fp:
        json.dump(data, fp, ensure_ascii=False, indent=2)

def retry_after_seconds(header):
    if not header:
        return None
    try:
        return max(0, int(header))
    except ValueError:
        try:
            deadline = email.utils.parsedate_to_datetime(header)
            if deadline.tzinfo is None:
                deadline = deadline.replace(tzinfo=dt.timezone.utc)
            return max(0, int((deadline - dt.datetime.now(dt.timezone.utc)).total_seconds()) + 1)
        except (ValueError, TypeError, OverflowError):
            return None

def inspect_error(exc):
    summary(f"HTTP {exc.code} from Naver source (no site data changed)")
    for name in ("Date", "Content-Type", "Retry-After", "X-RateLimit-Limit",
                 "X-RateLimit-Remaining", "X-RateLimit-Reset", "X-Request-ID"):
        value = exc.headers.get(name)
        if value:
            print(f"{name}: {value[:200]}")
    try:
        body = exc.read(700).decode("utf-8", "replace")
        print("Error body excerpt:", body[:450])
    except OSError:
        pass

def main():
    sid = os.getenv("TARGET_SID", "1053133212").strip()
    if not sid.isascii() or not sid.isdigit() or not 1 <= len(sid) <= 20:
        summary("Invalid SID; expected a numeric Naver place identifier.")
        return 1

    summary(f"## Weekly hours source check — SID {sid}")
    summary("Provider: Naver undocumented GraphQL; this run does not modify the website.")
    payload = [{
        "operationName": "getPlaceDetail",
        "variables": {"input": {"id": sid}},
        "query": QUERY,
    }]
    request = urllib.request.Request(
        ENDPOINT,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        method="POST",
    )

    # A retry is allowed only when the origin itself supplies a short Retry-After.
    # At most two total attempts; never retry an unqualified 429 or a 403.
    for attempt in range(2):
        try:
            with urllib.request.urlopen(request, timeout=20) as response:
                body = json.load(response)
                summary(f"HTTP {response.status} from Naver source")
        except urllib.error.HTTPError as exc:
            inspect_error(exc)
            delay = retry_after_seconds(exc.headers.get("Retry-After")) if exc.code == 429 else None
            if exc.code == 429 and attempt == 0 and delay is not None and 1 <= delay <= 60:
                summary(f"Server-specified Retry-After: {delay}s; one retry only.")
                time.sleep(delay)
                continue
            reason = "rate_limited" if exc.code == 429 else "http_error"
            checkpoint(sid, reason, httpStatus=exc.code, retryAfter=exc.headers.get("Retry-After"))
            if exc.code == 429:
                summary("PENDING: request restricted; no repeated probes or bypass attempted.")
            else:
                summary("PENDING: source request rejected.")
            return 1
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, ValueError) as exc:
            checkpoint(sid, "source_error", error=type(exc).__name__)
            summary(f"PENDING: source unavailable ({type(exc).__name__}: {str(exc)[:160]}).")
            return 1
        else:
            break

    if isinstance(body, list) and body:
        result = body[0]
    elif isinstance(body, dict):
        result = body
    else:
        result = {}
    detail = (result.get("data") or {}).get("placeDetail") if isinstance(result, dict) else None
    hours = (detail or {}).get("newBusinessHours") if isinstance(detail, dict) else None
    if not isinstance(hours, dict) or not isinstance(hours.get("businessHours"), list):
        checkpoint(sid, "incomplete_source_data", graphqlErrors=result.get("errors") if isinstance(result, dict) else None)
        summary("PENDING: the source returned no complete weekly-hours object.")
        return 1

    days = hours["businessHours"]
    checkpoint(sid, "source_read_success", daysReturned=len(days), hours=hours)
    summary(f"Retrieved {len(days)} day entries. Source read succeeded; site write NOT performed.")
    summary("This is not confirmation that all 7 days or exceptional holidays are verified.")
    return 0

if __name__ == "__main__":
    sys.exit(main())
