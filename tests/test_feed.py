import io
import json
import sys
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "feed"))
import pins as P  # noqa: E402
import run as R  # noqa: E402

STAMP = "20261117090000"
NOW = datetime(2026, 11, 17, 9, 12, tzinfo=timezone.utc)


def gkg_row(i, themes="PROTEST;", v2loc="4#New Delhi, Delhi, India#IN#IN07#17923#28.6#77.2#-2106102#120",
            title="Farmers march in Delhi", url=None, source="example.com"):
    r = [""] * 27
    r[0], r[1], r[3], r[4], r[8], r[10], r[15] = f"id{i}", STAMP, source, url or f"https://example.com/{i}", themes, v2loc, "-3.2,1,4"
    r[26] = f"<PAGE_TITLE>{title}</PAGE_TITLE>" if title else ""
    return "\t".join(r)


def zipped(text, name="x.gkg.csv"):
    b = io.BytesIO()
    with zipfile.ZipFile(b, "w") as z:
        z.writestr(name, text)
    return b.getvalue()


def test_lastupdate_gives_the_article_file():
    t = ("1 a http://data.gdeltproject.org/gdeltv2/20261117090000.export.CSV.zip\n"
         "2 b http://data.gdeltproject.org/gdeltv2/20261117090000.mentions.CSV.zip\n"
         "3 c http://data.gdeltproject.org/gdeltv2/20261117090000.gkg.csv.zip\n")
    f = P.parse_lastupdate(t)
    assert f["gkg"]["stamp"] == STAMP and f["gkg"]["url"].endswith("gkg.csv.zip")


def test_pins_dedupe_topics_and_precision():
    rows = [gkg_row(1), gkg_row(2), gkg_row(3, themes="ECON_INFLATION;", v2loc="1#India#IN#IN##20#77#IN#5", title="Inflation eases"),
            gkg_row(4, v2loc="", title="No place"), gkg_row(5, title=None)]
    stats, pins = P.parse_gkg("\n".join(rows), STAMP)
    assert stats["articles"] == 5 and stats["with_location"] == 4 and stats["with_title"] == 4
    assert len(pins) == 2 and pins[0]["precision"] == "4" and pins[1]["topic"] == "economy"


def test_headlines_are_decoded_cleaned_and_cut():
    _, pins = P.parse_gkg(gkg_row(1, title="Tom &amp; Jerry&#39;s  &#10;  caf&eacute; " + "x" * 400), STAMP)
    t = pins[0]["t"]
    assert t.startswith("Tom & Jerry's café ") and len(t) == P.TITLE_MAX and "\n" not in t and "&amp;" not in t


def test_only_web_links_survive():
    rows = [gkg_row(1, url="javascript:alert(1)"), gkg_row(2, url="data:text/html,hi", title="B"),
            gkg_row(3, url="https://ok.example/a", title="C"), gkg_row(4, url="http://ok.example/b", title="D")]
    _, pins = P.parse_gkg("\n".join(rows), STAMP)
    assert sorted(p["u"] for p in pins) == ["http://ok.example/b", "https://ok.example/a"]


def test_impossible_coordinates_are_dropped():
    _, pins = P.parse_gkg(gkg_row(1, v2loc="4#Nowhere#XX#XX00#1#95.0#200.0#x#1"), STAMP)
    assert pins == []


def test_pins_are_capped():
    rows = [gkg_row(i, title=f"Headline {i}", v2loc=f"4#P{i}#IN#IN07#1#{10 + i / 1000:.3f}#77.2#x#1") for i in range(P.PINS_PER_FILE + 50)]
    stats, pins = P.parse_gkg("\n".join(rows), STAMP)
    assert len(pins) == P.PINS_PER_FILE == stats["pins"]


def test_payload_shape_and_staleness():
    pin = {"t": "x", "u": "https://e.x", "lat": 1, "lon": 2}
    payload, body = R.build_payload(STAMP, [pin], NOW)
    assert body.startswith(b'{"schema":"hub-news-pins-v1"')           # the Worker checks this prefix
    assert payload["stale"] is False and payload["fetched_at"].startswith("2026-11-17T09:12")
    assert "gdeltproject.org" in payload["credit"]
    old, _ = R.build_payload(STAMP, [pin], NOW + timedelta(minutes=120))
    assert old["stale"] is True
    ahead, _ = R.build_payload("20261117093000", [pin], NOW)           # stamp ahead of the clock: not stale
    assert ahead["stale"] is False and ahead["source_age_min"] < 0


def test_big_payload_is_trimmed_to_fit():
    pin = {"t": "é" * 300, "u": "https://e.x/" + "a" * 400, "s": "s" * 80, "lat": 1.0, "lon": 2.0}
    payload, body = R.build_payload(STAMP, [dict(pin) for _ in range(900)], NOW)
    assert len(body) <= R.MAX_BYTES and 0 < payload["count"] < 900


def fake_network(monkeypatch, gkg_text, lastupdate=None):
    lu = lastupdate or f"9 a http://data.gdeltproject.org/gdeltv2/{STAMP}.gkg.csv.zip\n"
    def fetch(url, timeout=60):
        return lu.encode() if url == R.LASTUPDATE else zipped(gkg_text)
    monkeypatch.setattr(R, "fetch", fetch)
    monkeypatch.setattr(R, "now_utc", lambda: NOW)


def test_dry_run_sends_nothing(monkeypatch, tmp_path, capsys):
    fake_network(monkeypatch, gkg_row(1))
    monkeypatch.setattr(R, "push", lambda *a, **k: pytest.fail("dry run must not upload"))
    out = tmp_path / "p.json"
    assert R.main(["--dry-run", "--out", str(out)]) == 0
    assert json.loads(out.read_text())["count"] == 1 and "nothing sent" in capsys.readouterr().out


def test_upload_uses_the_secret_but_never_prints_it(monkeypatch, capsys):
    fake_network(monkeypatch, gkg_row(1))
    seen = {}
    monkeypatch.setattr(R, "push", lambda url, token, body: seen.update(url=url, token=token, n=len(body)) or 200)
    monkeypatch.setenv("PUSH_URL", "https://w.example/pins")
    monkeypatch.setenv("PUSH_TOKEN", "SECRET-" + "z" * 30)
    assert R.main([]) == 0
    cap = capsys.readouterr()
    assert seen["token"].startswith("SECRET-") and "SECRET-" not in cap.out + cap.err


def test_empty_or_broken_files_never_overwrite_good_data(monkeypatch, capsys):
    monkeypatch.setattr(R, "push", lambda *a, **k: pytest.fail("must not upload"))
    monkeypatch.setenv("PUSH_URL", "https://w.example/pins")
    monkeypatch.setenv("PUSH_TOKEN", "t" * 40)
    fake_network(monkeypatch, "")                                       # no articles
    assert R.main([]) == 1
    fake_network(monkeypatch, gkg_row(1, v2loc=""))                     # articles but no pins
    assert R.main([]) == 1
    fake_network(monkeypatch, gkg_row(1), lastupdate="garbage\n")       # no article file listed
    assert R.main([]) == 1


def test_missing_settings_stop_early(monkeypatch):
    monkeypatch.delenv("PUSH_URL", raising=False)
    monkeypatch.delenv("PUSH_TOKEN", raising=False)
    assert R.main([]) == 2


def test_push_refuses_plain_http():
    with pytest.raises(ValueError):
        R.push("http://w.example/pins", "t" * 40, b"{}")


def test_retries_then_gives_up(monkeypatch):
    monkeypatch.setattr(R.time, "sleep", lambda s: None)
    calls = []
    def boom():
        calls.append(1)
        raise OSError("down")
    with pytest.raises(RuntimeError):
        R._retry(boom, "x")
    assert len(calls) == 3


class _Resp:
    status = 200
    def __enter__(self): return self
    def __exit__(self, *a): return False


def test_push_sends_a_put_with_bearer_and_json(monkeypatch):
    seen = {}
    def fake_urlopen(req, timeout=0):
        seen.update(method=req.get_method(), auth=req.get_header("Authorization"), ctype=req.get_header("Content-type"), body=req.data)
        return _Resp()
    monkeypatch.setattr(R.urllib.request, "urlopen", fake_urlopen)
    assert R.push("https://w.example/pins", "tok" * 10, b'{"schema":"x"}') == 200
    assert seen == {"method": "PUT", "auth": "Bearer " + "tok" * 10, "ctype": "application/json", "body": b'{"schema":"x"}'}


def test_a_refused_upload_stops_without_retrying(monkeypatch):
    import urllib.error
    calls = []
    def fake_urlopen(req, timeout=0):
        calls.append(1)
        raise urllib.error.HTTPError(req.full_url, 401, "no", {}, None)
    monkeypatch.setattr(R.urllib.request, "urlopen", fake_urlopen)
    with pytest.raises(SystemExit) as e:
        R.push("https://w.example/pins", "t" * 40, b"{}")
    assert "401" in str(e.value) and len(calls) == 1 and "t" * 40 not in str(e.value)


def test_pasted_secrets_with_newlines_are_trimmed(monkeypatch):
    fake_network(monkeypatch, gkg_row(1))
    seen = {}
    monkeypatch.setattr(R, "push", lambda url, token, body: seen.update(url=url, token=token) or 200)
    monkeypatch.setenv("PUSH_URL", "https://w.example/pins\n")
    monkeypatch.setenv("PUSH_TOKEN", " " + "k" * 40 + "\n")
    assert R.main([]) == 0
    assert seen == {"url": "https://w.example/pins", "token": "k" * 40}


def test_unavailable_newest_file_falls_back_to_the_previous_one(monkeypatch, capsys):
    prev = "20261117084500"
    asked = []
    def fetch(url, timeout=60):
        asked.append(url.rsplit("/", 1)[-1])
        if url == R.LASTUPDATE:
            return f"9 a http://data.gdeltproject.org/gdeltv2/{STAMP}.gkg.csv.zip\n".encode()
        if STAMP in url:
            raise R.FileNotFound("404")
        return zipped(gkg_row(1))
    monkeypatch.setattr(R, "fetch", fetch)
    monkeypatch.setattr(R, "now_utc", lambda: NOW)
    sent = {}
    monkeypatch.setattr(R, "push", lambda url, token, body: sent.update(body=body) or 200)
    monkeypatch.setenv("PUSH_URL", "https://w.example/pins")
    monkeypatch.setenv("PUSH_TOKEN", "t" * 40)
    assert R.main([]) == 0
    assert asked[-1] == f"{prev}.gkg.csv.zip" and json.loads(sent["body"])["stamp"] == prev
    assert "not available yet" in capsys.readouterr().err


def test_only_a_404_triggers_the_fallback(monkeypatch):
    import urllib.error
    monkeypatch.setattr(R.time, "sleep", lambda s: None)
    def boom(req, timeout=0):
        raise urllib.error.HTTPError(req.full_url, 500, "x", {}, None)
    monkeypatch.setattr(R.urllib.request, "urlopen", boom)
    with pytest.raises(RuntimeError) as e:
        R.fetch("http://data.gdeltproject.org/gdeltv2/20261117090000.gkg.csv.zip")
    assert not isinstance(e.value, R.FileNotFound)
    def nf(req, timeout=0):
        raise urllib.error.HTTPError(req.full_url, 404, "x", {}, None)
    monkeypatch.setattr(R.urllib.request, "urlopen", nf)
    with pytest.raises(R.FileNotFound):
        R.fetch("http://data.gdeltproject.org/gdeltv2/20261117090000.gkg.csv.zip")


def test_fingerprint_is_printed_but_never_the_secret(monkeypatch, capsys):
    import hashlib
    fake_network(monkeypatch, gkg_row(1))
    monkeypatch.setattr(R, "push", lambda *a, **k: 200)
    secret = "abcdef0123456789" * 4
    monkeypatch.setenv("PUSH_URL", "https://w.example/pins")
    monkeypatch.setenv("PUSH_TOKEN", secret + "\n")                  # a stray newline must not change the fingerprint
    assert R.main([]) == 0
    out = capsys.readouterr()
    want = hashlib.sha256(secret.encode()).hexdigest()[:8]
    assert f"token fingerprint {want}  length 64" in out.out
    assert secret not in out.out + out.err
