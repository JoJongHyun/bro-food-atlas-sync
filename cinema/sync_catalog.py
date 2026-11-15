#!/usr/bin/env python3
"""BRO CINEMA: metadata-only catalog updater.

Authorized, keyless sources:
* TVmaze public TV + episode metadata API (https://www.tvmaze.com/api)
* Wikimedia public MediaWiki categorymembers API

This does not crawl TVWiki, resolve protected video URLs or alter manually
verified playback and episode links. Unknown values stay empty.
"""
from __future__ import annotations

import argparse
import datetime as dt
import html
import json
import logging
import os
from pathlib import Path
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

LOG = logging.getLogger("cinema.sync")
UA = "BRO-CINEMA-MetadataSync/1.0 (public TVmaze and Wikimedia API)"
MAX_NEW_PER_CATEGORY = 25
MAX_OFFICIAL_EPISODES = 200
TVMAZE = "https://api.tvmaze.com"
WIKI = "https://en.wikipedia.org/w/api.php"


def utc_now():
    return dt.datetime.now(dt.timezone.utc)


def request_json(url: str) -> dict | list:
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme != "https" or parsed.hostname not in {"api.tvmaze.com", "en.wikipedia.org", "ko.wikipedia.org"}:
        raise ValueError("Source host is not allowlisted")
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    last = None
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=17) as resp:
                body = resp.read(3_000_001)
                if len(body) > 3_000_000:
                    raise ValueError("Source API response exceeds cap")
                result = json.loads(body.decode("utf-8"))
                if not isinstance(result, (dict, list)):
                    raise ValueError("Unexpected API response")
                return result
        except (urllib.error.URLError, TimeoutError, ValueError, json.JSONDecodeError) as exc:
            last = exc
            LOG.warning("Source temporarily unavailable: %s (%s)", parsed.path, type(exc).__name__)
            if attempt < 2:
                time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"Source API failure: {parsed.hostname}{parsed.path}: {last}")


def strip_markup(value):
    text = re.sub(r"<[^>]+>", " ", str(value or ""))
    return re.sub(r"\s+", " ", html.unescape(text)).strip()


def norm_name(name):
    return re.sub(r"[\W_]+", "", str(name or "").casefold(), flags=re.UNICODE)


def item_key(item):
    return str(item.get("category", "")) + "|" + norm_name(item.get("title", ""))


def item_source_id(item):
    link = item.get("tvwikiPage", "")
    m = re.search(r"/(movie|kor_movie|drama|old_drama)/(\d+)(?:/|$)", link)
    if m:
        route = "드라마" if m[1] in ("drama", "old_drama") else ("한국영화" if m[1] == "kor_movie" else "영화")
        return route + "|" + m[2]
    return None


def is_airdate_passed(value, today):
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        return False
    return value <= today.isoformat()


def read_tvmaze(today):
    """Official schedules: yesterday, today, tomorrow; Korean-language scripted only."""
    results = {}
    succeeded = 0
    dates = [today + dt.timedelta(days=n) for n in (-1, 0, 1)]
    urls = []
    for day in dates:
        q = urllib.parse.urlencode({"country": "KR", "date": day.isoformat()})
        urls.append(TVMAZE + "/schedule?" + q)
        # Include locally or globally hosted OTT releases, filtered by Korean language.
        urls.append(TVMAZE + "/schedule/web?" + urllib.parse.urlencode({"date": day.isoformat()}))
    for url in urls:
        try:
            episodes = request_json(url)
            succeeded += 1
            if not isinstance(episodes, list):
                continue
            for ep in episodes:
                if not isinstance(ep, dict):
                    continue
                show = ep.get("show") or ep.get("_embedded", {}).get("show") or {}
                if not isinstance(show, dict):
                    continue
                if show.get("language") != "Korean" or show.get("type") != "Scripted":
                    continue
                year_text = str(show.get("premiered") or "")[:4]
                if not year_text.isdigit() or int(year_text) < today.year - 1:
                    continue
                show_id = show.get("id")
                if not isinstance(show_id, int) or show_id <= 0 or not show.get("name"):
                    continue
                results[show_id] = show
        except RuntimeError as e:
            LOG.warning("%s", e)
        time.sleep(0.4)
    return list(results.values()), succeeded


def read_recent_films(today):
    """Wikimedia licensed metadata only. No film streams or provider page scraping."""
    categories = [
        ("한국영화", "Category:" + str(today.year) + " South Korean films"),
        ("영화", "Category:" + str(today.year) + " films"),
    ]
    records = []
    success = 0
    for category, title in categories:
        query = urllib.parse.urlencode({
            "action": "query", "format": "json", "list": "categorymembers",
            "cmtitle": title, "cmnamespace": "0", "cmtype": "page",
            "cmlimit": "50", "cmprop": "ids|title|timestamp",
            "cmsort": "timestamp", "cmdir": "desc",
        })
        try:
            doc = request_json(WIKI + "?" + query)
            success += 1
            for page in (doc.get("query") or {}).get("categorymembers", []):
                name = str(page.get("title", "")).strip()
                if not name or not isinstance(page.get("pageid"), int):
                    continue
                if re.search(r"\b(list of|filmography|awards|category|template)\b", name, re.I):
                    continue
                records.append({
                    "id": f"auto-wiki-{category}-{page['pageid']}",
                    "category": category, "title": name, "year": today.year,
                    "description": "Wikimedia 공개 영화 작품 정보 · 영상 재생 별도",
                    "sourceUrl": "https://en.wikipedia.org/wiki/" + urllib.parse.quote(name.replace(" ", "_")),
                    "sourceProvider": "Wikimedia",
                })
        except RuntimeError as e:
            LOG.warning("%s", e)
        time.sleep(0.4)
    return records, success


def new_tvmaze_item(show):
    show_id = show["id"]
    image = show.get("image") or {}
    if not isinstance(image, dict):
        image = {}
    title = strip_markup(show.get("name"))[:180]
    premiered = str(show.get("premiered") or "")
    premiered = premiered if re.fullmatch(r"\d{4}-\d{2}-\d{2}", premiered) else ""
    return {
        "id": f"auto-tvmaze-{show_id}", "category": "드라마",
        "title": title, "year": int(premiered[:4]) if premiered else "",
        "releaseDate": premiered,
        "description": strip_markup(show.get("summary"))[:260] or "TVmaze 드라마 작품 정보 · 영상 재생 별도",
        "poster": image.get("medium") if str(image.get("medium", "")).startswith("https://") else "",
        "sourceUrl": show.get("url") if str(show.get("url", "")).startswith("https://www.tvmaze.com/") else "",
        "tvmazeId": show_id, "sourceProvider": "TVmaze",
        "officialEpisodes": [],
    }


def read_tvmaze_episodes(show_id, today):
    endpoint = TVMAZE + "/shows/" + str(show_id) + "/episodes"
    payload = request_json(endpoint)
    if not isinstance(payload, list):
        raise ValueError("Invalid TVmaze episode list")
    result = []
    seen = set()
    for ep in payload:
        if not isinstance(ep, dict) or not is_airdate_passed(ep.get("airdate"), today):
            continue
        season, number = ep.get("season"), ep.get("number")
        if not isinstance(season, int) or not isinstance(number, int) or season < 1 or number < 1:
            continue
        key = (season, number)
        if key in seen:
            continue
        seen.add(key)
        url = str(ep.get("url") or "")
        if not url.startswith("https://www.tvmaze.com/episodes/"):
            continue
        result.append({
            "season": season, "number": number,
            "label": f"시즌 {season} · {number}화" if season > 1 else f"{number}화",
            "airdate": ep.get("airdate"), "title": str(ep.get("name") or "")[:120],
            "url": url,
        })
    return sorted(result, key=lambda x: (x["season"], x["number"]))[-MAX_OFFICIAL_EPISODES:]


def sync(catalog, today):
    items = catalog.get("items")
    if not isinstance(items, list):
        raise ValueError("Missing items array")
    # Preserve all user-maintained fields, poster references, verified episode URLs.
    by_key = {item_key(x): x for x in items}
    by_tvmaze = {x["tvmazeId"]: x for x in items if isinstance(x.get("tvmazeId"), int)}
    source_ids = {item_source_id(x) for x in items if item_source_id(x)}
    added = {"영화": [], "한국영화": [], "드라마": []}
    updated_episodes = []
    api_success = 0

    tvshows, ok = read_tvmaze(today)
    api_success += ok
    for show in tvshows:
        cat = "드라마"
        name = strip_markup(show.get("name"))[:180]
        key = cat + "|" + norm_name(name)
        show_id = show["id"]
        existing = by_tvmaze.get(show_id) or by_key.get(key)
        if existing:
            if existing.get("tvmazeId") in (None, ""):
                existing["tvmazeId"] = show_id
            by_tvmaze[show_id] = existing
        elif len(added[cat]) < MAX_NEW_PER_CATEGORY:
            existing = new_tvmaze_item(show)
            items.append(existing)
            by_key[key] = existing
            by_tvmaze[show_id] = existing
            added[cat].append(name)

    movies, ok = read_recent_films(today)
    api_success += ok
    for incoming in movies:
        cat = incoming["category"]
        key = item_key(incoming)
        if key in by_key or len(added[cat]) >= MAX_NEW_PER_CATEGORY:
            continue
        # Avoid near-exact language variant duplicates only; never infer a release date.
        items.append(incoming)
        by_key[key] = incoming
        added[cat].append(incoming["title"])

    # Query official episode metadata for all items with a known TVmaze ID.
    # Hard cap requests so large catalogs do not overwhelm the public API.
    for item in list(by_tvmaze.values())[:40]:
        show_id = item.get("tvmazeId")
        if not isinstance(show_id, int):
            continue
        try:
            new = read_tvmaze_episodes(show_id, today)
            api_success += 1
            old = item.get("officialEpisodes") or []
            if not isinstance(old, list):
                old = []
            if new != old:
                item["officialEpisodes"] = new
                diff = len({(e["season"], e["number"]) for e in new} -
                           {(e.get("season"), e.get("number")) for e in old})
                if diff:
                    updated_episodes.append({"title": item["title"], "newCount": diff, "total": len(new)})
            time.sleep(0.45)
        except (RuntimeError, ValueError) as e:
            LOG.warning("Episodes unavailable for %s: %s", item.get("title"), e)

    if api_success == 0:
        raise RuntimeError("Every official metadata API failed; unchanged catalog retained")

    when = utc_now().isoformat(timespec="seconds")
    summary = {
        "status": "ok", "checkedAt": when,
        "source": ["TVmaze public API", "Wikimedia MediaWiki API"],
        "newTitles": {k: len(v) for k, v in added.items()},
        "newEpisodeMetadata": sum(x["newCount"] for x in updated_episodes),
        "titlesAdded": [{"category": k, "title": title} for k, vals in added.items() for title in vals],
        "episodeChanges": updated_episodes[:40],
        "sourceRequestsSucceeded": api_success,
        "note": "Official broadcast episode metadata does not imply playable video. Existing TVWiki links are unchanged.",
    }
    history = catalog.get("autoSyncHistory") or []
    history.insert(0, summary)
    catalog["autoSyncHistory"] = history[:12]
    catalog["autoSync"] = summary
    catalog["updatedAt"] = when
    return summary


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--catalog", default="cinema/catalog.json")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    file = Path(args.catalog)
    original = json.loads(file.read_text(encoding="utf-8"))
    report = sync(original, utc_now().date())
    LOG.info("New titles %s, new official episodes %s, API responses %s",
             report["newTitles"], report["newEpisodeMetadata"], report["sourceRequestsSucceeded"])
    if not args.dry_run:
        # Atomic write, and never discard preexisting fields.
        tmp = file.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(original, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        os.replace(tmp, file)
    else:
        print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    try:
        main()
    except Exception as err:
        LOG.exception("Catalog not modified: %s", err)
        sys.exit(1)
