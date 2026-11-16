#!/usr/bin/env python3
"""Recent broadcast order metadata for TVWiki movie/drama boards.

Reads public list pages (no stream extraction); TVWiki controls availability.
One run reads only three pages each for movies, dramas and variety shows; never requests video files.
"""
import html
import logging
import re
import time
import urllib.error
import urllib.parse
import urllib.request

LOG = logging.getLogger("cinema.tvwiki.recent")
HOST = "tvwiki60.net"
CATEGORIES = (("영화", "movie"), ("드라마", "drama"), ("예능", "ent"))
MAX_RECENT_PAGES = 3
MAX_ENT_PAGES = 110  # full variety-program archive used only by weekly importer
CARD_RE = re.compile(r'<div\s+class="box"\s*>(.*?)</div>', re.I | re.S)
TITLE_RE = re.compile(r'<a\s+href="([^"]+)"\s+class="title2"[^>]*>(.*?)</a>', re.I | re.S)
POSTER_RE = re.compile(r'<img\s+src="([^"]+)"', re.I)


def get_page(route, page):
    if route not in {"movie", "drama", "ent"} or not 1 <= page <= (MAX_ENT_PAGES if route == "ent" else MAX_RECENT_PAGES):
        raise ValueError("Unrecognized source route or page")
    url = "https://" + HOST + "/" + route + "?" + urllib.parse.urlencode(
        {"sst": "subidx", "page": page}
    )
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 (compatible; BRO-CINEMA-IndexSync/1.0)",
        "Accept": "text/html,application/xhtml+xml",
        "Accept-Language": "ko-KR,ko;q=0.9",
    })
    with urllib.request.urlopen(req, timeout=20) as response:
        final = urllib.parse.urlsplit(response.geturl())
        if final.hostname != HOST or final.path != "/" + route:
            raise ValueError("Unexpected source redirect")
        blob = response.read(1_200_001)
        if len(blob) > 1_200_000:
            raise ValueError("HTML source size exceeded")
        return blob.decode(response.headers.get_content_charset() or "utf-8", errors="replace")


def parse_page(body, category, route):
    section = re.search(r'<div\s+id="list_type"[^>]*>(.*?)</ul>', body, re.I | re.S)
    if section is None:
        raise ValueError("No source list found")
    found = []
    seen = set()
    pattern = re.compile(
        r"^https://tvwiki60\.net/" + re.escape(route) + r"/(\d+)(?:/(\d+))?$"
    )
    for card in CARD_RE.findall(section.group(1)):
        link = TITLE_RE.search(card)
        if not link:
            continue
        url = html.unescape(link.group(1)).split("?", 1)[0].rstrip("/")
        m = pattern.fullmatch(url)
        if not m or m.group(1) in seen:
            continue
        name = re.sub(r"\s+", " ", html.unescape(
            re.sub(r"<[^>]*>", " ", link.group(2))
        )).strip()
        if not name or len(name) > 180:
            continue
        seen.add(m.group(1))
        poster_match = POSTER_RE.search(card)
        poster = html.unescape(poster_match.group(1)) if poster_match else ""
        parsed = urllib.parse.urlsplit(poster)
        if parsed.scheme != "https" or parsed.hostname not in (HOST, "image.tmdb.org") or poster.endswith("/no3.png"):
            poster = ""
        found.append({
            "id": "tvwiki-" + route + "-" + m.group(1),
            "category": category, "title": name,
            "tvwikiPage": url, "sourceUrl": url,
            "sourceProvider": "TVWiki recent broadcast listing",
            "poster": poster, "tvwikiPageStatus": "episode" if m.group(2) else "listing",
        })
    return found


def sync_recent_boards(catalog):
    items = catalog["items"]
    report = {}
    for category, route in CATEGORIES:
        discovered = []
        try:
            for page in range(1, MAX_RECENT_PAGES + 1):
                if page > 1:
                    time.sleep(0.7)
                listings = parse_page(get_page(route, page), category, route)
                if len(listings) < 10:
                    raise ValueError("Unexpectedly few records in " + route)
                discovered.extend(listings)
        except (urllib.error.URLError, OSError, ValueError, TimeoutError) as exc:
            LOG.warning("TVWiki %s recent list unavailable; keep catalog: %s", route, exc)
            report[category] = {"status": "source_unavailable", "detail": str(exc)[:120]}
            continue

        # Preserve week-long full-archive ranks for entertainment titles.
        # Movie/drama ranks cover only the recent 3-page window.
        if category != "예능":
            for old_item in items:
                if old_item.get("category") == category:
                    old_item.pop("tvwikiRank", None)
        # Keep existing TVWiki episode/media fields, deduplicate by stable work ID.
        known = {}
        for item in items:
            if item.get("category") != category:
                continue
            m = re.search(r"/" + re.escape(route) + r"/(\d+)(?:/|$)",
                          str(item.get("tvwikiPage") or ""))
            if m and m.group(1) not in known:
                known[m.group(1)] = item
        new_count = 0
        for rank, fresh in enumerate(discovered):
            work_id = fresh["id"].rsplit("-", 1)[1]
            existing = known.get(work_id)
            if existing is None:
                fresh["tvwikiRank"] = rank
                items.append(fresh)
                known[work_id] = fresh
                new_count += 1
            else:
                existing.update({
                    "title": fresh["title"],
                    "tvwikiPage": fresh["tvwikiPage"],
                    "tvwikiRank": rank,
                    "sourceUrl": fresh["sourceUrl"],
                    "sourceProvider": fresh["sourceProvider"],
                    "tvwikiPageStatus": fresh["tvwikiPageStatus"],
                })
                if fresh["poster"]:
                    existing["poster"] = fresh["poster"]
        # Older linked works stay in the catalog. Non-TVWiki metadata items
        # stay as fallback, but never claim to have verified video links.
        report[category] = {"status": "ok", "sort": "recent_broadcast",
                            "pagesFetched": MAX_RECENT_PAGES,
                            "itemsIndexed": len(discovered),
                            "newTitles": new_count}
        LOG.info("TVWiki %s recent-air list: %s records, +%s new", category,
                 len(discovered), new_count)
    catalog["tvwikiRecentSync"] = report
    return report
