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

SCHEMA = "hub-news-pins-v1"
CREDIT = "The GDELT Project, https://www.gdeltproject.org/"
PINS_PER_FILE = 400
TITLE_MAX = 300
STALE_AFTER_MIN = 60          # a source file older than this is marked stale

csv.field_size_limit(min(sys.maxsize, 2**31 - 1))

# GDELT GKG 2.1: 27 tab-separated columns, no header
GKG = {"id": 0, "date": 1, "source": 3, "url": 4, "themes": 7, "v2themes": 8, "locations": 9, "v2locations": 10,
       "tone": 15, "extras": 26}
GKG_COLS = 27
# theme prefixes -> topic (first match wins, in this order)
THEME_TOPIC = [
    ("disasters", ("NATURAL_DISASTER", "DISASTER", "TAX_DISEASE_", "MANMADE_DISASTER", "ENV_CLIMATECHANGE")),
    ("conflict", ("ARMEDCONFLICT", "KILL", "TERROR", "MILITARY", "WB_2433_CONFLICT", "CRISISLEX_C07_SAFETY", "SECURITY_SERVICES")),
    ("protests", ("PROTEST", "STRIKE", "UNREST_")),
    ("health", ("HEALTH", "MEDICAL", "WB_621_HEALTH", "TAX_DISEASE", "EPIDEMIC", "VACCIN")),
    ("economy", ("ECON_", "WB_1104_MACROECONOMIC", "TAX_ECON_PRICE", "WB_442_INFLATION", "FUELPRICES", "STOCK", "CENTRAL_BANK", "TRADE")),
    ("science_tech", ("CYBER_ATTACK", "WB_133_INFORMATION_AND_COMMUNICATION", "SCIENCE", "TECHNOLOGY", "AI_", "SPACE")),
    ("politics", ("ELECTION", "LEGISLATION", "GENERAL_GOVERNMENT", "LEADER", "DIPLOMACY", "SANCTION", "TAX_FNCACT_PRESIDENT")),
]


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


def topic_of(themes: str) -> str:
    for topic, prefixes in THEME_TOPIC:
        if any(p in themes for p in prefixes):
            return topic
    return "other"


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
    """-> (stats, pins). Pins: one per place+headline, most specific place first, capped."""
    n = with_loc = with_title = bad = 0
    topics: dict[str, int] = {}
    pins = []
    for r in _rows(text):
        if len(r) != GKG_COLS:
            bad += 1
            continue
        n += 1
        loc = first_location(r[GKG["v2locations"]], r[GKG["locations"]])
        title = page_title(r[GKG["extras"]])
        with_title += title is not None
        topic = topic_of(r[GKG["v2themes"]] or r[GKG["themes"]])
        topics[topic] = topics.get(topic, 0) + 1
        if not loc:
            continue
        with_loc += 1
        url = safe_url(r[GKG["url"]])
        if title and url:
            tone = _f((r[GKG["tone"]] or "").split(",")[0])
            pins.append({"t": title, "u": url, "s": clean_text(r[GKG["source"]], 80), "topic": topic,
                         "tone": round(tone, 1) if tone is not None else None, **loc})
    seen, kept = set(), []
    for p in sorted(pins, key=lambda p: p["precision"] not in ("3", "4")):
        key = (p["t"].lower()[:80], p["lat"], p["lon"])
        if key in seen:
            continue
        seen.add(key)
        kept.append(p)
        if len(kept) >= PINS_PER_FILE:
            break
    return {"articles": n, "with_location": with_loc, "with_title": with_title, "bad_rows": bad, "topics": topics,
            "pins": len(kept)}, kept
