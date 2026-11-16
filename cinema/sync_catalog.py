#!/usr/bin/env python3
"""BRO CINEMA: metadata-only catalog updater.

Authorized, keyless sources:
* TVmaze public TV + episode metadata API (https://www.tvmaze.com/api)
* Wikimedia public MediaWiki categorymembers API (Korean and English film/TV categories)

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

from sync_tvwiki_kor import sync_kr_movies
from sync_tvwiki_recent import sync_recent_boards
from sync_tvwiki_episodes import sync_drama_episodes

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
    dates = [today + dt.timedelta(days=n) for n in (-2, -1, 0, 1, 2, 7, 14)]
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


def mediawiki_categories(today):
    """Track Korean originals as well as international releases and upcoming-year titles."""
    # Catalog new releases from the current year only. A future year alone
    # does not establish that a title has been released.
    for year in [today.year]:
        yield "영화", "ko", year, f"분류:{year}년 영화"
        yield "영화", "en", year, f"Category:{year} films"
        yield "드라마", "ko", year, f"분류:{year}년 대한민국의 텔레비전 드라마"
        yield "드라마", "en", year, f"Category:{year} South Korean television series"


def read_recent_works(today):
    """Discover movie + series pages via publicly documented MediaWiki categories.

    Category timestamps denote when an article joined the category, NOT the
    release date. Keep them for incremental comparison, never as release dates.
    """
    records, succeeded, sources = [], 0, {}
    for category, language, year, group in mediawiki_categories(today):
        query = urllib.parse.urlencode({
            "action": "query", "format": "json", "list": "categorymembers",
            "cmtitle": group, "cmnamespace": "0",
            "cmlimit": "100", "cmprop": "ids|title|timestamp",
            "cmsort": "timestamp", "cmdir": "desc",
        })
        try:
            endpoint = f"https://{language}.wikipedia.org/w/api.php?" + query
            doc = request_json(endpoint)
            if not isinstance(doc, dict) or doc.get("error"):
                LOG.warning("MediaWiki category failed: %s (%s)", group, (doc or {}).get("error") if isinstance(doc, dict) else "invalid")
                continue
            succeeded += 1
            source_key = f"{language}|{category}|{year}"
            sources[source_key] = len((doc.get("query") or {}).get("categorymembers") or [])
            for page in (doc.get("query") or {}).get("categorymembers", []):
                if page.get("ns", 0) != 0:
                    continue
                title = strip_markup(page.get("title"))[:180]
                pageid = page.get("pageid")
                if not title or not isinstance(pageid, int):
                    continue
                if re.search(r"\\b(list of|filmography|awards|category|template)\\b", title, re.I):
                    continue
                records.append({
                    "sourceIndexedAt": str(page.get("timestamp") or ""),
                    "id": f"auto-wiki-{language}-{category}-{pageid}",
                    "category": category, "title": title, "year": year,
                    "description": "Wikimedia 공개 작품 정보 · 영상 연결 별도",
                    "sourceUrl": f"https://{language}.wikipedia.org/wiki/" + urllib.parse.quote(title.replace(" ", "_")),
                    "sourceProvider": f"Wikimedia ({language})",
                })
        except RuntimeError as e:
            LOG.warning("Category %s unavailable: %s", group, e)
        time.sleep(0.2)
    return records, succeeded, sources

def read_tvmaze_akas(show_id):
    """Official localized alternate names, used ONLY for matching existing titles."""
    values = request_json(TVMAZE + "/shows/" + str(show_id) + "/akas")
    if not isinstance(values, list):
        return []
    names = []
    for v in values[:40]:
        if not isinstance(v, dict):
            continue
        name = strip_markup(v.get("name"))[:180]
        if name and name not in names:
            names.append(name)
    return names


def new_tvmaze_item(show, preferred_title=None):
    show_id = show["id"]
    image = show.get("image") or {}
    if not isinstance(image, dict):
        image = {}
    title = strip_markup(preferred_title or show.get("name"))[:180]
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
    """Hourly, entirely source-driven catalog sync. No title/episode hand entries.

    TVWiki is the single source for movies, Korean movies, drama, and
    episode page links. Source failures never delete verified links.
    """
    items = catalog.get("items")
    if not isinstance(items, list):
        raise ValueError("Missing items array")
    # Earlier experiments attached broadcaster viewing links; those are not
    # part of the TVWiki catalog policy.
    for item in items:
        if isinstance(item, dict):
            item.pop("officialLinks", None)

    stamp = utc_now().isoformat(timespec="seconds")
    kr = sync_kr_movies(catalog, timestamp=stamp)
    boards = sync_recent_boards(catalog)
    episodes = sync_drama_episodes(catalog, timestamp=stamp)
    new_titles = {
        "영화": int(boards.get("영화", {}).get("newTitles") or 0),
        "한국영화": int(kr.get("newTitles") or 0),
        "드라마": int(boards.get("드라마", {}).get("newTitles") or 0),
    }
    unavailable = (kr.get("status") == "source_unavailable"
                   and all(boards.get(cat, {}).get("status") != "ok"
                           for cat in ("영화", "드라마"))
                   and episodes.get("status") in ("blocked", "partial"))
    summary = {
        "status": "source_unavailable" if unavailable else "partial" if (
            kr.get("status") != "ok"
            or any(boards.get(cat, {}).get("status") != "ok" for cat in ("영화", "드라마"))
            or episodes.get("status") != "ok"
        ) else "ok",
        "checkedAt": stamp,
        "source": ["TVWiki public movie list", "TVWiki public Korean-film list",
                   "TVWiki public drama list", "TVWiki public drama episode index"],
        "newTitles": new_titles,
        "newEpisodes": episodes.get("newEpisodes", 0),
        "newEpisodeMetadata": 0,
        "tvwikiKoreanMovieSync": {
            "status": kr.get("status"), "totalPages": kr.get("totalPages"),
            "pagesFetched": kr.get("pagesFetched"), "newTitles": kr.get("newTitles"),
            "tvwikiLinked": kr.get("tvwikiLinked")
        },
        "tvwikiRecentBoards": boards,
        "tvwikiEpisodeSync": episodes,
        "tvwikiLinked": sum(1 for it in items if isinstance(it, dict)
                            and (it.get("tvwikiPage") or any(
                                ep.get("pageUrl") for ep in it.get("episodes", [])
                                if isinstance(ep, dict)))),
        "totalTitles": len(items),
        "note": "Titles and episode buttons update only from current TVWiki public list links; failures are surfaced. No media downloads, invented episode URLs, or manual catalog entries.",
    }
    history = catalog.get("autoSyncHistory")
    if not isinstance(history, list):
        history = []
    catalog["autoSyncHistory"] = [summary] + history[:23]
    catalog["autoSync"] = summary
    catalog["updatedAt"] = stamp
    LOG.info("New titles %s, TVWiki episodes +%s, episode detail pages %s, status %s",
             new_titles, summary["newEpisodes"],
             episodes.get("detailPagesChecked"), summary["status"])
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
    LOG.info("Synchronized TVWiki titles %s, episodes +%s, status %s",
             report["newTitles"], report["newEpisodes"], report["status"])
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
