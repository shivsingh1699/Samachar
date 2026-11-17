#!/usr/bin/env python3
"""Samachar feed job: newest GDELT article file -> pins JSON -> Cloudflare Worker.

    python3 feed/run.py --dry-run           build the file and print a summary; send nothing
    python3 feed/run.py --out pins.json     also save the file locally
    PUSH_URL=https://.../pins PUSH_TOKEN=... python3 feed/run.py

On any problem it exits non-zero and sends nothing, so the Worker keeps serving the last good file.
It never prints the passphrase.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import pins as P  # noqa: E402

LASTUPDATE = "http://data.gdeltproject.org/gdeltv2/lastupdate.txt"
UA = "Samachar-feed/1.0 (personal, non-commercial; https://github.com/shivsingh1699/Samachar)"
MAX_BYTES = 350_000            # the Worker refuses anything over 400,000 bytes
RETRY_WAITS = (5, 20)          # seconds between the three attempts


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _retry(fn, what: str):
    last = None
    for i in range(len(RETRY_WAITS) + 1):
        try:
            return fn()
        except Exception as e:  # noqa: BLE001 - report and retry any network problem
            last = e
            print(f"{what}: attempt {i + 1} failed: {type(e).__name__}: {str(e)[:150]}", file=sys.stderr)
            if i < len(RETRY_WAITS):
                time.sleep(RETRY_WAITS[i])
    raise RuntimeError(f"{what} failed after {len(RETRY_WAITS) + 1} attempts") from last


class FileNotFound(RuntimeError):
    """The server kept answering 404 for this file (GDELT can list a file a little before it can be downloaded)."""


def fetch(url: str, timeout: float = 60) -> bytes:
    def go():
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read()
    try:
        return _retry(go, f"download {url.rsplit('/', 1)[-1]}")
    except RuntimeError as e:
        c = e.__cause__
        if isinstance(c, urllib.error.HTTPError) and c.code == 404:
            raise FileNotFound(str(e)) from e
        raise


def build_payload(stamp: str, pin_list: list, now: datetime) -> tuple[dict, bytes]:
    """Payload dict + its UTF-8 bytes, trimmed to fit MAX_BYTES. 'schema' must stay the first key (the Worker checks it)."""
    src = P.stamp_time(stamp)
    age_min = round((now - src).total_seconds() / 60, 1)
    keep = list(pin_list)
    while True:
        payload = {"schema": P.SCHEMA, "credit": P.CREDIT, "source": "GDELT GKG 2.1", "stamp": stamp,
                   "source_time": src.isoformat(timespec="seconds"), "fetched_at": now.isoformat(timespec="seconds"),
                   "source_age_min": age_min, "stale": age_min > P.STALE_AFTER_MIN, "count": len(keep), "pins": keep}
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        if len(body) <= MAX_BYTES or not keep:
            return payload, body
        keep = keep[: int(len(keep) * 0.85)]


def push(url: str, token: str, body: bytes) -> int:
    if not url.lower().startswith("https://"):
        raise ValueError("PUSH_URL must start with https:// (the passphrase is never sent in the clear)")

    def go():
        req = urllib.request.Request(url, data=body, method="PUT", headers={
            "Authorization": "Bearer " + token, "Content-Type": "application/json", "User-Agent": UA})
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return r.status
        except urllib.error.HTTPError as e:
            if e.code in (400, 401, 403, 413, 503):     # a retry cannot fix these
                raise SystemExit(f"Worker refused the upload: HTTP {e.code}") from None
            raise
    return _retry(go, "upload")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="build and summarise; send nothing")
    ap.add_argument("--out", help="also write the pins file here")
    a = ap.parse_args(argv)

    # A pasted secret often carries a trailing newline or space; HTTP headers cannot, so trim both.
    url, token = os.environ.get("PUSH_URL", "").strip(), os.environ.get("PUSH_TOKEN", "").strip()
    if not a.dry_run and not (url and token):
        print("PUSH_URL and PUSH_TOKEN must be set (or use --dry-run).", file=sys.stderr)
        return 2
    if token:
        # First 8 hex characters of SHA-256 plus the length: lets you check the GitHub secret equals the one you meant to
        # store without printing it. Not reversible for a long random value such as `openssl rand -hex 32`.
        print(f"token fingerprint {hashlib.sha256(token.encode()).hexdigest()[:8]}  length {len(token)}")

    files = P.parse_lastupdate(fetch(LASTUPDATE, 20).decode("utf-8", errors="replace"))
    if "gkg" not in files:
        print("GDELT's latest-files list has no article file.", file=sys.stderr)
        return 1
    stamp, gkg_url = files["gkg"]["stamp"], files["gkg"]["url"]
    try:
        blob = fetch(gkg_url, 120)
    except FileNotFound:
        # The newest file is listed but not downloadable yet: use the one before it (marked stale if it is old).
        prev = (P.stamp_time(stamp) - timedelta(minutes=15)).strftime("%Y%m%d%H%M%S")
        print(f"{stamp} is listed but not available yet (404); using the previous file {prev}.", file=sys.stderr)
        stamp, gkg_url = prev, gkg_url.replace(stamp, prev)
        blob = fetch(gkg_url, 120)
    stats, pin_list = P.parse_gkg(P.unzip_text(blob), stamp)
    if stats["articles"] == 0 or not pin_list:
        print(f"Parsed {stats['articles']} articles and {len(pin_list)} pins: not publishing, last good file stays.", file=sys.stderr)
        return 1

    payload, body = build_payload(stamp, pin_list, now_utc())
    print(f"file {stamp}  articles {stats['articles']}  with place {stats['with_location']}  pins {payload['count']}  "
          f"{len(body) / 1024:.1f} KB  source age {payload['source_age_min']} min  stale {payload['stale']}")
    if a.out:
        Path(a.out).write_bytes(body)
    if a.dry_run:
        print("dry run: nothing sent")
        return 0
    status = push(url, token, body)
    print(f"uploaded: HTTP {status}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
