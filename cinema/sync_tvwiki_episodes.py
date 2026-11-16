#!/usr/bin/env python3
"""Refresh TVWiki drama episode *index links*, never download video media.

Only publicly visible list links from #other_list are accepted. Stops on
access refusal/rate limits and keeps all previously validated episode links.
Newly updated or unscanned dramas are processed first; older series rotate.
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

LOG = logging.getLogger("cinema.tvwiki.episodes")
DOMAIN = "tvwiki60.net"
URL_RE = re.compile(r"^https://tvwiki60\.net/drama/(\d+)(?:/(\d+))?$")
LIST_RE = re.compile(r'<div\s+id=["\']other_list["\'][^>]*>[\s\S]*?<ul[^>]*>([\s\S]*?)</ul>', re.I)
ANCHOR_RE = re.compile(
    r'<a\b[^>]*href=["\']([^"\']+)["\'][^>]*class=["\'][^"\']*\btitle\b[^"\']*\bep-link\b[^"\']*["\'][^>]*>([\s\S]*?)</a>',
    re.I,
)
NUMBER_RE = re.compile(r"(?<!\d)(\d{1,4})\s*(?:화|회)(?!\d)")
MAX_EPISODES = 250
MAX_SCANS = 110
MIN_GAP_SECONDS = 0.65
RECENT_CHECK_HOURS = 3
OLDER_CHECK_HOURS = 24


class SourceBlocked(Exception):
    pass


def valid_work_url(url):
    try:
        parts = urllib.parse.urlsplit(str(url or ""))
        if parts.scheme != "https" or parts.hostname != DOMAIN:
            return ""
        clean = urllib.parse.urlunsplit(("https", DOMAIN, parts.path.rstrip("/"), "", ""))
        return clean if URL_RE.fullmatch(clean) else ""
    except ValueError:
        return ""


def fetch_page(url):
    if not valid_work_url(url):
        raise ValueError("Not a TVWiki drama page URL")
    request = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 (compatible; BRO-CINEMA-IndexSync/1.0)",
        "Accept": "text/html,application/xhtml+xml",
        "Accept-Language": "ko-KR,ko;q=0.9",
    })
    try:
        with urllib.request.urlopen(request, timeout=20) as res:
            final = urllib.parse.urlsplit(res.geturl())
            if final.scheme != "https" or final.hostname != DOMAIN:
                raise ValueError("Unexpected off-host redirect")
            buf = res.read(1_200_001)
            if len(buf) > 1_200_000:
                raise ValueError("Detail page exceeds HTML limit")
            return buf.decode(res.headers.get_content_charset() or "utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        if exc.code in (401, 403, 429):
            raise SourceBlocked("Original website refused requests: " + str(exc.code)) from exc
        raise


def parse_episodes(source, work_id):
    """Return exact public episode links, or None if the source has no episode list."""
    section = LIST_RE.search(source)
    if not section:
        return None
    episodes = {}
    for anchor in ANCHOR_RE.finditer(section.group(1)):
        href = valid_work_url(html.unescape(anchor.group(1)))
        match = URL_RE.fullmatch(href) if href else None
        if not match or match.group(1) != str(work_id) or not match.group(2):
            continue
        label = re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", anchor.group(2)))).strip()
        number_match = NUMBER_RE.search(label)
        if not number_match:
            continue  # Never invent numbers for specials or unnumbered entries.
        number = int(number_match.group(1))
        if not 1 <= number <= 9999:
            continue
        episodes[number] = {"number": number, "label": f"{number}화", "pageUrl": href}
    return [episodes[n] for n in sorted(episodes)][-MAX_EPISODES:]


def _dt_iso(value):
    try:
        return dt.datetime.fromisoformat(str(value or ""))
    except (ValueError, TypeError):
        return None


def sync_drama_episodes(catalog, timestamp=None):
    items = catalog.get("items") or []
    stamp = timestamp or dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    now = _dt_iso(stamp)
    if not now:
        raise ValueError("Invalid episode sync timestamp")
    eligible = []
    for item in items:
        if item.get("category") != "드라마":
            continue
        url = valid_work_url(item.get("tvwikiPage"))
        # Some manual records contain episode links but no tvwikiPage.
        if not url:
            for episode in item.get("episodes") or []:
                url = valid_work_url(episode.get("pageUrl"))
                if url:
                    break
        if not url:
            continue
        work_id = URL_RE.fullmatch(url).group(1)
        is_recent = isinstance(item.get("tvwikiRank"), int) and item["tvwikiRank"] < 90
        last = _dt_iso(item.get("tvwikiEpisodeCheckedAt"))
        diff = (now - last).total_seconds() if last else float("inf")
        new_head = item.get("tvwikiEpisodeLastPage") != url
        need = new_head or diff >= 3600 * (RECENT_CHECK_HOURS if is_recent else OLDER_CHECK_HOURS)
        if need:
            eligible.append((0 if is_recent and new_head else 1 if is_recent else 2,
                             last or dt.datetime(1970, 1, 1, tzinfo=dt.timezone.utc),
                             item, url, work_id))
    eligible.sort(key=lambda x: (x[0], x[1], x[4]))
    inspected = changed = new_count = errors = skipped_unstructured = 0
    refusal = ""
    for _, _, item, url, work_id in eligible[:MAX_SCANS]:
        if inspected:
            time.sleep(MIN_GAP_SECONDS)
        try:
            raw = fetch_page(url)
            current = parse_episodes(raw, work_id)
        except SourceBlocked as exc:
            refusal = str(exc)
            LOG.warning("Stopping TVWiki episode sync after source refusal: %s", refusal)
            break
        except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
            errors += 1
            LOG.warning("TVWiki episode index unavailable for %s: %s", item.get("title"), exc)
            continue
        inspected += 1
        item["tvwikiEpisodeCheckedAt"] = stamp
        item["tvwikiEpisodeLastPage"] = url
        if current is None:
            skipped_unstructured += 1
            continue
        existing = item.get("episodes") if isinstance(item.get("episodes"), list) else []
        combined = {
            int(ep["number"]): ep for ep in existing
            if isinstance(ep, dict) and isinstance(ep.get("number"), int)
            and 0 < ep["number"] < 10000
            and valid_work_url(ep.get("pageUrl"))
        }
        before = set(combined)
        modified = False
        for ep in current:
            old = combined.get(ep["number"])
            if old is None or old.get("pageUrl") != ep["pageUrl"]:
                combined[ep["number"]] = ep
                modified = True
        if modified:
            item["episodes"] = [combined[n] for n in sorted(combined)][-MAX_EPISODES:]
            changed += 1
            new_count += len(set(combined) - before)
            LOG.info("TVWiki drama %s: %s total verified episodes, +%s new",
                     item.get("title"), len(item["episodes"]), len(set(combined) - before))
    result = {
        "status": "blocked" if refusal else "partial" if errors else "ok",
        "checkedAt": stamp, "detailPagesChecked": inspected,
        "titlesWithEpisodeChanges": changed,
        "newEpisodes": new_count,
        "episodeScanQueue": max(0, len(eligible) - inspected),
        "parseWithoutEpisodeList": skipped_unstructured,
        "fetchErrors": errors,
        "reason": refusal,
        "note": "Public TVWiki drama episode links are checked; no media files or DRM bypass."
    }
    catalog["tvwikiEpisodeSync"] = result
    LOG.info("TVWiki drama episode sync: %s pages checked, %s titles updated, +%s episodes, queue %s, errors %s",
             inspected, changed, new_count, result["episodeScanQueue"], errors)
    return result
