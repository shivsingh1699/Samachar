# Samachar

A small public repository that builds the **World News pins** for a personal dashboard.
Every 15 minutes a scheduled GitHub Actions job takes GDELT's newest article file, keeps up to 400 headlines that have a place on the map,
and uploads one small JSON file to a Cloudflare Worker. The dashboard reads that file from the Worker.

News data: **The GDELT Project, https://www.gdeltproject.org/**. Locations are machine-coded from article text and can be wrong.

This repository holds no personal or financial data and must never hold any. The only secrets are two GitHub Actions secrets (below).

## Layout

| Path | What it is |
|---|---|
| `feed/pins.py` | Reads GDELT's GKG article file and builds the pins (standard library only) |
| `feed/run.py` | The job: download, build, upload. `--dry-run` sends nothing |
| `worker/index.js` | The Cloudflare Worker: `GET /pins.json` serves the file, `PUT /pins` stores it (passphrase needed) |
| `.github/workflows/feed.yml` | The 15-minute schedule (`:07 :22 :37 :52`), manual run, and a once-a-day status commit |
| `tests/`, `worker/index.test.js` | `python3 -m pytest tests` and `cd worker && node --test` |

## What the dashboard receives

`GET https://<worker>/pins.json` returns `hub-news-pins-v1`:

```
{ "schema", "credit", "source", "stamp", "source_time", "fetched_at", "source_age_min", "stale", "count",
  "pins": [ { "t": headline, "u": link, "s": site, "topic", "topics", "tone", "name", "cc", "lat", "lon", "precision" } ] }
```

Rules for whoever displays it:
- **Headlines, links and site names are untrusted text from the open web.** Show them with `textContent`, never `innerHTML`. Open links only if they start with `http://` or `https://`.
- Show the data's time (`source_time`) on the map and the credit line. Show a warning if `stale` is true **or** if `fetched_at` is more than 3 hours old (the job itself may have stopped). GitHub's schedule delivers about one run an hour, not every 15 minutes; keep the 3 hours as one named setting.
- `cc` is a FIPS 10-4 country code, not ISO (`CH` is China). India is `IN` in both.
- `source_age_min` can be slightly negative: GDELT's file stamps have run a few minutes ahead of the clock in testing. It is recorded, not relied on.
- If the job fails, nothing is uploaded and the Worker keeps serving the last good file.

## One-time setup

1. **Worker.** In the Cloudflare dashboard create a Worker named `samachar`, paste in `worker/index.js`, and deploy. In its settings add a KV binding named `PINS` pointing at the `samachar-pins` namespace.
2. **Passphrase.** Generate one on your own computer without displaying it (Mac): `openssl rand -hex 32 | pbcopy`. Paste it twice, and nowhere else (not in chat, not in a file):
   - Cloudflare: Worker > Settings > Variables and Secrets > add a **Secret** named `PUSH_TOKEN`.
   - GitHub: this repo > Settings > Secrets and variables > Actions > New repository secret named `PUSH_TOKEN`.
3. **Address.** Add a second GitHub Actions secret `PUSH_URL` = `https://samachar.<your-subdomain>.workers.dev/pins`.
4. **Try it.** Actions > feed > Run workflow with *dry run* ticked. The log should show about 300 to 400 pins. Run it again with dry run off, then open `https://samachar.<your-subdomain>.workers.dev/pins.json`.
5. Leave the schedule on. Check the Actions tab after an hour: runs should appear roughly every 15 minutes. GitHub can delay scheduled runs; that is normal.

## Limits to keep in mind (free plans)

- GitHub: public repositories have free Actions minutes; scheduled runs can be delayed under load; schedules switch off after 60 days without repository activity (the daily status commit exists for this).
- Cloudflare Workers: 100,000 requests a day and 10 ms CPU per request, so the Worker never parses the JSON. KV: 1,000 writes a day (this job uses about 96).
- The passphrase can only replace this one stored file. If it leaks, change it in both places.

## Topics

Each pin has `topics` (every topic the headline is about, possibly empty) and `topic` (the main one, or `other`).
Values: `festivals`, `conflict`, `disasters`, `protests`, `health`, `economy`, `policy`, `politics`, `science_tech`,
`lifestyle`, plus the cross-cutting `india` (set when the headline names India or the place is in India; never the main topic).

- The **headline decides**. GDELT's theme tags come from the whole web page, so they pick up menus and related links; a
  first live check filed travel guides under conflict. Theme codes only add a tag when the same topic's codes appear at
  least `THEME_MIN` times in the page (a cautious guess; tune it on real data).
- English headlines only. Other languages usually get no tag, never a wrong one.
- Each topic is guaranteed up to `TOPIC_QUOTA` of the 400 pins, so quiet topics are not crowded out.
- One pin per headline: the same story from many local sites is shown once, with the outlet name (`| The Rural`) removed.
- Readers must not assume every pin has a topic: `topics` can be `[]` and `topic` is then `other`.
- Edit the word lists in `feed/topics.py`; `tests/test_topics.py` shows what each rule must and must not match.
