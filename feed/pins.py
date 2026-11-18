"""Samachar: turn one GDELT GKG 2.1 article file into a small list of map pins.

Standard library only. GDELT data: The GDELT Project, https://www.gdeltproject.org/ (cited in every file we publish).
Headlines and URLs come from the open web: treat them as untrusted text everywhere they are shown.
"""
from __future__ import annotations

import csv
import html
import io
import sys
import zipfile
from datetime import datetime, timezone

import topics as T

SCHEMA = "hub-news-pins-v1"
CREDIT = "The GDELT Project, https://www.gdeltproject.org/"
PINS_PER_FILE = 400
TITLE_MAX = 300
STALE_AFTER_MIN = 60          # a source file older than this is marked stale
TOPIC_QUOTA = 30              # each topic is guaranteed up to this many of the pins (before the rest are filled by place precision)

csv.field_size_limit(min(sys.maxsize, 2**31 - 1))

# GDELT GKG 2.1: 27 tab-separated columns, no header
GKG = {"id": 0, "date": 1, "source": 3, "url": 4, "themes": 7, "v2themes": 8, "locations": 9, "v2locations": 10,
       "tone": 15, "extras": 26}
GKG_COLS = 27


def stamp_time(stamp: str) -> datetime:
    return datetime.strptime(stamp, "%Y%m%d%H%M%S").replace(tzinfo=timezone.utc)


def parse_lastupdate(text: str) -> dict:
    """Map 'export'/'mentions'/'gkg' -> {size, md5, url, stamp}."""
    out = {}
    for line in text.strip().splitlines():
        parts = line.split()
        if len(parts) != 3:
            continue
        size, md5, url = parts
        name = url.rsplit("/", 1)[-1]
        kind = "gkg" if ".gkg." in name else "mentions" if ".mentions." in name else "export"
        try:
            out[kind] = {"size": int(size), "md5": md5, "url": url, "stamp": name.split(".")[0]}
        except ValueError:
            continue
    return out


def unzip_text(blob: bytes) -> str:
    with zipfile.ZipFile(io.BytesIO(blob)) as z:
        return z.read(z.namelist()[0]).decode("utf-8", errors="replace")


def _rows(text: str):
    return csv.reader(io.StringIO(text), delimiter="\t", quoting=csv.QUOTE_NONE)


def _f(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def first_location(v2loc: str, v1loc: str):
    """Most specific location named in the article: city (type 3/4) before state (2/5) before country (1)."""
    best, best_rank = None, 9
    rank = {"3": 0, "4": 0, "2": 1, "5": 1, "1": 2}
    for blob, v2 in ((v2loc, True), (v1loc, False)):
        for loc in filter(None, (blob or "").split(";")):
            p = loc.split("#")
            if v2 and len(p) >= 8:
                typ, name, cc, lat, lon = p[0], p[1], p[2], _f(p[5]), _f(p[6])
            elif not v2 and len(p) >= 6:
                typ, name, cc, lat, lon = p[0], p[1], p[2], _f(p[4]), _f(p[5])
            else:
                continue
            if lat is None or lon is None or not (-90 <= lat <= 90 and -180 <= lon <= 180):
                continue
            r = rank.get(typ, 3)
            if r < best_rank:
                best, best_rank = {"name": name, "cc": cc, "lat": round(lat, 3), "lon": round(lon, 3), "precision": typ}, r
        if best:
            return best
    return best


def clean_text(s: str, limit: int) -> str:
    """Decode HTML entities (GDELT escapes non-ASCII as &amp;-style), collapse whitespace, then cut."""
    return " ".join(html.unescape(s or "").split())[:limit]


def page_title(extras: str):
    a = (extras or "").find("<PAGE_TITLE>")
    if a < 0:
        return None
    b = extras.find("</PAGE_TITLE>", a)
    return clean_text(extras[a + 12:b if b > 0 else None], TITLE_MAX) or None


def safe_url(u: str):
    """Only plain web links; anything else (javascript:, data:, file:) is dropped."""
    u = (u or "").strip()
    return u if u.lower().startswith(("http://", "https://")) and len(u) <= 500 else None


def parse_gkg(text: str, stamp: str):
    """-> (stats, pins). One pin per distinct headline, most specific place first, topic quotas, capped at PINS_PER_FILE."""
    n = with_loc = with_title = bad = 0
    pool = []
    for r in _rows(text):
        if len(r) != GKG_COLS:
            bad += 1
            continue
        n += 1
        loc = first_location(r[GKG["v2locations"]], r[GKG["locations"]])
        site = clean_text(r[GKG["source"]], 80)
        title = page_title(r[GKG["extras"]])
        if title:
            title = T.strip_site_suffix(title, site) or None
        with_title += title is not None
        if not loc:
            continue
        with_loc += 1
        url = safe_url(r[GKG["url"]])
        if title and url:
            tags = T.tags_for(title, r[GKG["v2themes"]], r[GKG["themes"]], loc["cc"])
            tone = _f((r[GKG["tone"]] or "").split(",")[0])
            pool.append({"t": title, "u": url, "s": site, "topic": T.main_topic(tags), "topics": tags,
                         "tone": round(tone, 1) if tone is not None else None, **loc})
    seen, uniq = set(), []
    for p in sorted(pool, key=lambda p: p["precision"] not in ("3", "4")):
        key = T.dedupe_key(p["t"], p["lat"], p["lon"])
        if key in seen:
            continue
        seen.add(key)
        uniq.append(p)
    kept, taken, per_tag = [], set(), {}
    for i, p in enumerate(uniq):          # first pass: make sure no topic is crowded out by the loudest ones
        if len(kept) >= PINS_PER_FILE:
            break
        if any(per_tag.get(t, 0) < TOPIC_QUOTA for t in p["topics"]):
            kept.append(i)
            taken.add(i)
            for t in p["topics"]:
                per_tag[t] = per_tag.get(t, 0) + 1
    for i in range(len(uniq)):            # second pass: fill what is left, most precise places first
        if len(kept) >= PINS_PER_FILE:
            break
        if i not in taken:
            kept.append(i)
    chosen = [uniq[i] for i in sorted(kept)]
    counts: dict[str, int] = {}
    for p in chosen:
        for t in p["topics"] or ["other"]:
            counts[t] = counts.get(t, 0) + 1
    return {"articles": n, "with_location": with_loc, "with_title": with_title, "bad_rows": bad, "topics": counts,
            "pins": len(chosen)}, chosen
