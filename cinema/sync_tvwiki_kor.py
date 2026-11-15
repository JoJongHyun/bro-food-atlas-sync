#!/usr/bin/env python3
"""Import the public TVWiki Korean-film INDEX into BRO CINEMA.

Only list-page metadata (title, poster URL, and linked work URL) is read.
Never fetch media, bypass controls, or synthesize video/episode URLs.
The importer is idempotent, rate limited, and resumes an interrupted scan.
"""
from __future__ import annotations

import datetime as dt
import html
import logging
import re
import time
import urllib.error
import urllib.parse
import urllib.request

LOG = logging.getLogger("cinema.tvwiki.kr")
SOURCE = "https://tvwiki60.net/kor_movie"
HOST = "tvwiki60.net"
WORK_RE = re.compile(r"^https://tvwiki60\.net/kor_movie/(\d+)(?:/(\d+))?$")
CARD_RE = re.compile(r'<div\s+class="box"\s*>(.*?)</div>', re.S | re.I)
TITLE_RE = re.compile(r'<a\s+href="([^"]+)"\s+class="title2"[^>]*>(.*?)</a>', re.S | re.I)
POSTER_RE = re.compile(r'<img\s+src="([^"]+)"', re.I)
LAST_RE = re.compile(r'<a\s+href="([^"]+)"\s+class="pg_page pg_end"', re.I)
MAX_PAGES = 250
MINIMUM_CARDS = 10
REQUEST_DELAY = 0.7
MAX_PER_RUN = 160  # page 1 + up to 159 other pages, enough for current 151-page index
SOURCE_SCHEMA_VERSION = 2  # Include listing-only /kor_movie/<id> records

def now_iso():
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")

def valid_movie_url(url):
    try:
        parsed = urllib.parse.urlsplit(html.unescape(str(url)))
        if parsed.scheme != "https" or parsed.hostname != HOST:
            return ""
        value = urllib.parse.urlunsplit((parsed.scheme, parsed.hostname, parsed.path, "", ""))
        return value if WORK_RE.fullmatch(value) else ""
    except (TypeError, ValueError):
        return ""

def work_id(url):
    found = WORK_RE.fullmatch(str(url or ""))
    return found.group(1) if found else None

def fetch_index(page):
    if not 1 <= page <= MAX_PAGES:
        raise ValueError("Page index exceeds crawler bounds")
    qs = urllib.parse.urlencode({"sst": "wr_datetime", "page": page})
    url = SOURCE + "?" + qs
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 (compatible; BRO-CINEMA-IndexSync/1.0)",
        "Accept": "text/html,application/xhtml+xml",
        "Accept-Language": "ko-KR,ko;q=0.9",
    })
    last = None
    for attempt in range(2):
        try:
            with urllib.request.urlopen(req, timeout=17) as res:
                final = urllib.parse.urlsplit(res.geturl())
                if final.hostname != HOST or final.path != "/kor_movie":
                    raise RuntimeError("Unexpected redirect away from source category")
                body = res.read(1_200_001)
                if len(body) > 1_200_000:
                    raise RuntimeError("Index response exceeded safety limit")
                charset = res.headers.get_content_charset() or "utf-8"
                return body.decode(charset, errors="replace")
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
            last = exc
            if isinstance(exc, urllib.error.HTTPError) and exc.code in (401, 403, 429):
                break  # Respect refusal and rate-limit responses.
            if attempt == 0:
                time.sleep(2)
    raise RuntimeError("Source page unavailable: " + str(last))

def parse_index(text):
    main = re.search(r'<div\s+id="list_type"[^>]*>(.*?)</ul>', text, re.S | re.I)
    if not main:
        raise ValueError("TVWiki category list could not be identified")
    entries = []
    seen = set()
    for card in CARD_RE.findall(main.group(1)):
        title_match = TITLE_RE.search(card)
        if not title_match:
            continue
        url = valid_movie_url(title_match.group(1))
        name = re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", title_match.group(2)))).strip()
        if not url or not name or len(name) > 180:
            continue
        movie_id = work_id(url)
        if movie_id in seen:
            continue
        seen.add(movie_id)
        poster_match = POSTER_RE.search(card)
        poster = html.unescape(poster_match.group(1)) if poster_match else ""
        try:
            pu = urllib.parse.urlsplit(poster)
            if pu.scheme != "https" or pu.hostname not in ("tvwiki60.net", "image.tmdb.org") or pu.path.endswith("/no3.png"):
                poster = ""
        except ValueError:
            poster = ""
        entries.append({"id": "tvwiki-kr-" + movie_id,
                        "category": "한국영화",
                        "title": name,
                        "tvwikiPage": url,
                        "sourceUrl": url,
                        "sourceProvider": "TVWiki Korean movie index",
                        "poster": poster,
                        "tvwikiPageStatus": "episode" if WORK_RE.fullmatch(url).group(2) else "listing"})
    total = 1
    match = LAST_RE.search(text)
    if match:
        qs = urllib.parse.parse_qs(urllib.parse.urlsplit(html.unescape(match.group(1))).query)
        if "page" in qs:
            try:
                total = max(1, min(MAX_PAGES, int(qs["page"][0])))
            except (TypeError, ValueError):
                pass
    return entries, total

def sync_kr_movies(catalog, timestamp=None):
    """Update only category 한국영화; keep old verified URLs if source fails."""
    items = catalog.get("items")
    if not isinstance(items, list):
        raise ValueError("Catalog has no items array")
    stamp = timestamp or now_iso()
    state = catalog.get("tvwikiKorSync") or {}
    old_linked = sum(1 for x in items if x.get("category") == "한국영화" and valid_movie_url(x.get("tvwikiPage")))
    try:
        first, total = parse_index(fetch_index(1))
        if len(first) < MINIMUM_CARDS:
            raise RuntimeError("Too few film cards on source page; previous catalog preserved")
    except (RuntimeError, ValueError) as exc:
        LOG.warning("TVWiki source unavailable: %s", exc)
        state.update({"status": "source_unavailable", "checkedAt": stamp,
                      "source": SOURCE, "tvwikiLinked": old_linked,
                      "note": str(exc)[:180]})
        catalog["tvwikiKorSync"] = state
        return state

    last_full = state.get("fullIndexedAt")
    full_due = state.get("completedSchemaVersion") != SOURCE_SCHEMA_VERSION
    if last_full and not full_due:
        try:
            full_due = (dt.datetime.fromisoformat(stamp) -
                        dt.datetime.fromisoformat(last_full)).days >= 7
        except ValueError:
            full_due = True
    cursor = max(2, min(total + 1, int(state.get("nextPage") or 2))) if full_due else 2
    max_more = MAX_PER_RUN - 1 if full_due else 2
    upper = min(total + 1, cursor + max_more)
    pages = list(range(cursor, upper))
    observed = {work_id(x["tvwikiPage"]): (x, 0) for x in first}
    failed_at = None
    for page in pages:
        time.sleep(REQUEST_DELAY)
        try:
            batch, _ = parse_index(fetch_index(page))
            if len(batch) < MINIMUM_CARDS and page < total:
                raise RuntimeError("Unexpectedly short category page " + str(page))
        except (RuntimeError, ValueError) as exc:
            failed_at = page
            LOG.warning("Stopped after page %s: %s", page - 1, exc)
            break
        for pos, record in enumerate(batch):
            wid = work_id(record["tvwikiPage"])
            if wid not in observed:
                observed[wid] = (record, (page - 1) * 30 + pos)
    by_work = {}
    for item in items:
        if item.get("category") == "한국영화":
            wid = work_id(valid_movie_url(item.get("tvwikiPage")))
            if wid and wid not in by_work:
                by_work[wid] = item
    added = 0
    updated = 0
    for wid, (record, position) in observed.items():
        existing = by_work.get(wid)
        if existing is None:
            record["tvwikiRank"] = position
            items.append(record)
            by_work[wid] = record
            added += 1
        else:
            old_url = existing.get("tvwikiPage")
            existing["tvwikiPage"] = record["tvwikiPage"]
            existing["title"] = record["title"]
            existing["sourceUrl"] = record["tvwikiPage"]
            existing["sourceProvider"] = "TVWiki Korean movie index"
            existing["tvwikiPageStatus"] = record["tvwikiPageStatus"]
            existing["tvwikiRank"] = position
            if record["poster"]:
                existing["poster"] = record["poster"]
            if old_url != record["tvwikiPage"]:
                updated += 1
    # Drop unrelated Korean-film Wikipedia metadata. Preserve every previously
    # verified TVWiki page, even when a partial scan has not reached that page.
    before = len(items)
    items[:] = [x for x in items if x.get("category") != "한국영화"
                or bool(valid_movie_url(x.get("tvwikiPage")))]
    removed_unlinked = before - len(items)
    next_page = failed_at if failed_at else upper
    completed = bool(full_due and next_page > total)
    if completed:
        state["fullIndexedAt"] = stamp
        state["completedSchemaVersion"] = SOURCE_SCHEMA_VERSION
        state["nextPage"] = 2
    elif full_due:
        state["nextPage"] = next_page
    linked_count = sum(1 for x in items if x.get("category") == "한국영화"
                       and valid_movie_url(x.get("tvwikiPage")))
    state.update({
        "status": "ok" if not failed_at else "partial",
        "schemaVersion": SOURCE_SCHEMA_VERSION,
        "source": SOURCE, "checkedAt": stamp, "totalPages": total,
        "pagesFetched": 1 + (failed_at - cursor if failed_at else len(pages)),
        "scanNextPage": state.get("nextPage", 2), "fullScanComplete": state.get("completedSchemaVersion") == SOURCE_SCHEMA_VERSION,
        "newTitles": added, "updatedLinks": updated,
        "removedNonTVWiki": removed_unlinked,
        "tvwikiLinked": linked_count,
        "note": "Only public Korean movie list metadata and page links; no player-stream extraction.",
    })
    catalog["tvwikiKorSync"] = state
    LOG.info("TVWiki Korean movie list: pages %s/%s, +%s titles, %s link updates, %s linked, %s removed unrelated entries",
             state["pagesFetched"], total, added, updated, linked_count, removed_unlinked)
    return state
