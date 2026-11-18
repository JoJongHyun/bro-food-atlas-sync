#!/usr/bin/env python3
"""Resumable, rate-limited import of TVWiki entertainment show INDEX metadata.

Fetches /ent category cards, not media/player. Preserves known program episodes.
A complete scan is done initially and at most once per week; recent changes
are handled by the 3-page 30-minute updater in sync_tvwiki_recent.py.
"""
from __future__ import annotations

import datetime as dt
import html
import logging
import re
import time
import urllib.error
import urllib.parse

from sync_tvwiki_recent import get_page, parse_page, MAX_ENT_PAGES

LOG = logging.getLogger("cinema.tvwiki.ent")
LAST_RE = re.compile(r'<a\s+href="([^"]+)"\s+class="pg_page pg_end"', re.I)
WORK_RE = re.compile(r"^https://tvwiki61\.net/ent/(\d+)(?:/\d+)?$")
MAX_PAGES_PER_RUN = 90
MIN_CARD_COUNT = 8
SCAN_PAUSE = 0.7
SCHEMA_VERSION = 2


def _work_id(url):
    found = WORK_RE.fullmatch(str(url or "").replace("https://tvwiki60.net/", "https://tvwiki61.net/").replace("https://tvwiki59.net/", "https://tvwiki61.net/"))
    return found.group(1) if found else None


def _timestamp(value):
    try:
        return dt.datetime.fromisoformat(str(value))
    except (ValueError, TypeError):
        return None


def sync_ent_catalog(catalog, timestamp):
    items = catalog.get("items")
    if not isinstance(items, list):
        raise ValueError("Missing items array")
    prior = catalog.get("tvwikiEntSync")
    state = dict(prior) if isinstance(prior, dict) else {}
    try:
        first_html = get_page("ent", 1)
        first = parse_page(first_html, "예능", "ent")
        if len(first) < MIN_CARD_COUNT:
            raise ValueError("TVWiki entertainment board returned too few cards")
        match = LAST_RE.search(first_html)
        if not match:
            raise ValueError("TVWiki entertainment category total pages missing")
        query = urllib.parse.parse_qs(urllib.parse.urlsplit(html.unescape(match.group(1))).query)
        total_pages = int(query["page"][0])
        if total_pages < 1 or total_pages > MAX_ENT_PAGES:
            raise ValueError("TVWiki entertainment page total outside safety cap")
    except (urllib.error.URLError, TimeoutError, OSError, ValueError, KeyError) as exc:
        state.update({"status": "source_unavailable", "checkedAt": timestamp,
                      "source": "https://tvwiki61.net/ent", "reason": str(exc)[:180]})
        catalog["tvwikiEntSync"] = state
        LOG.warning("TVWiki entertainment catalog unavailable, retaining previous links: %s", exc)
        return state

    last = _timestamp(state.get("fullIndexedAt"))
    now = _timestamp(timestamp)
    due = (state.get("schemaVersion") != SCHEMA_VERSION or not last
           or not now or (now - last).total_seconds() >= 7 * 86400)
    cursor = max(2, min(total_pages + 1, int(state.get("nextPage") or 2))) if due else 2
    end_page = min(total_pages + 1, cursor + MAX_PAGES_PER_RUN - 1)
    candidates = [(record, rank) for rank, record in enumerate(first)]
    checked = 1
    failed_at = None
    if due:
        for page in range(cursor, end_page):
            time.sleep(SCAN_PAUSE)
            try:
                batch = parse_page(get_page("ent", page), "예능", "ent")
                if len(batch) < MIN_CARD_COUNT and page < total_pages:
                    raise ValueError("Unexpectedly empty entertainment board at page " + str(page))
            except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
                failed_at = page
                LOG.warning("TVWiki variety scan stopped at page %s: %s", page, exc)
                break
            checked += 1
            candidates.extend((entry, (page - 1) * 30 + rank)
                              for rank, entry in enumerate(batch))

    known = {}
    for item in items:
        if item.get("category") != "예능":
            continue
        work = _work_id(item.get("tvwikiPage"))
        if work and work not in known:
            known[work] = item
    added = 0
    updated = 0
    for incoming, rank in candidates:
        work = _work_id(incoming["tvwikiPage"])
        if not work:
            continue
        item = known.get(work)
        if item is None:
            item = dict(incoming)
            item["tvwikiRank"] = rank
            items.append(item)
            known[work] = item
            added += 1
        else:
            old_page = item.get("tvwikiPage")
            item.update({
                "title": incoming["title"],
                "tvwikiPage": incoming["tvwikiPage"],
                "tvwikiRank": rank,
                "sourceUrl": incoming["sourceUrl"],
                "sourceProvider": incoming["sourceProvider"],
                "tvwikiPageStatus": incoming["tvwikiPageStatus"],
            })
            if incoming["poster"]:
                item["poster"] = incoming["poster"]
            updated += int(old_page != item["tvwikiPage"])
    if due:
        next_page = failed_at or end_page
        if next_page > total_pages:
            state["nextPage"] = 2
            state["fullIndexedAt"] = timestamp
            state["schemaVersion"] = SCHEMA_VERSION
        else:
            state["nextPage"] = next_page
    state.update({
        "status": "partial" if failed_at else "ok",
        "checkedAt": timestamp,
        "source": "https://tvwiki61.net/ent",
        "sort": "recent_broadcast",
        "totalPages": total_pages,
        "pagesFetched": checked,
        "nextPage": state.get("nextPage", 2),
        "fullScanComplete": state.get("schemaVersion") == SCHEMA_VERSION,
        "newTitles": added,
        "updatedProgramLinks": updated,
        "totalLinked": len(known),
        "note": "Only publicly listed TVWiki entertainment program links and posters are indexed.",
    })
    catalog["tvwikiEntSync"] = state
    LOG.info("TVWiki entertainment catalog: pages %s/%s, +%s programs, %s linked, %s links refreshed",
             checked, total_pages, added, len(known), updated)
    return state
