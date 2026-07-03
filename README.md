# Emirates DXB ⇄ DEL Fare Watch — fully automated

Runs on GitHub's free scheduled-Actions runner (Mon/Wed/Fri by default).
No manual entry, no laptop needs to stay on. It calls Claude with web search
enabled to check real fares, writes the result to `fare_log.json`, emails
you only when something's actually notable, and the dashboard reads that
same log directly — so the whole loop is hands-off.

## Two scripts are included

- **`check_fares_ai.py`** (recommended, primary) — uses the Anthropic API
  with web search to check Google Flights / Emirates.com / deal chatter,
  and can actually tell you whether **Saver** is showing. This is what
  the dashboard is built to read.
- **`check_fares.py`** (optional, free tier) — uses the Amadeus flight
  price API instead. No AI cost, but it only tracks raw price movement,
  not fare-family names or sale chatter. Use this if you'd rather not
  spend anything on API calls and don't need the Saver-specific signal.

You don't need both — pick one and disable the other's schedule in
`.github/workflows/fare-check.yml` (or keep just the file for the one
you're using).

## One-time setup (~15 minutes) — AI-driven version

1. **Create a GitHub repo**, keep it **public** — the dashboard fetches
   `fare_log.json` straight from `raw.githubusercontent.com`, which only
   works without extra auth if the repo is public. (The data in it is
   just flight prices and dates — nothing sensitive.) Upload all the files
   here, keeping the folder structure intact.

2. **Get an Anthropic API key**
   - Sign up / log in at https://console.anthropic.com
   - Create a key under API Keys
   - This is a real, paid API key (separate from your claude.ai account) —
     each run costs roughly a few cents given the prompt size and a
     handful of searches. Running Mon/Wed/Fri, that's well under a coffee
     a month.

3. **Get a Gmail app password**
   - Turn on 2-Step Verification: https://myaccount.google.com/security
   - Create an app password: https://myaccount.google.com/apppasswords

4. **Add secrets to the GitHub repo**
   Repo → Settings → Secrets and variables → Actions → New repository secret:
   - `ANTHROPIC_API_KEY`
   - `GMAIL_ADDRESS`
   - `GMAIL_APP_PASSWORD`
   - (optional) `ALERT_TO` if alerts should go to a different inbox

5. **Enable Actions** on the repo (Actions tab → "I understand, enable").
   Trigger a first run manually from the Actions tab ("Run workflow") to
   confirm it works before waiting for the schedule.

6. **Point the dashboard at your repo**: open `emirates-fare-watch.html`,
   paste your raw log URL into the "Data source" field — it looks like
   `https://raw.githubusercontent.com/<you>/<repo>/main/fare_log.json` —
   and hit Refresh. It'll remember this for next time.

## What "smart, not wasteful" means here

- Each run asks for the single cheapest date per leg, not a day-by-day
  scan — a handful of searches per run, not dozens.
- The schedule is Mon/Wed/Fri, not continuous — matches how fast fares
  actually move and keeps API spend low.
- Emails only fire on an actual change (new low, Saver newly available,
  live sale) — not a "nothing changed" ping every run.

## Editing your travel windows

Edit **`windows.json`** — no code change needed. Each entry is
`{"route": "DEL-DXB", "window": "4-11 Nov 2026", "note": "..."}`. It ships with
the BITS Pilani Dubai 2026-27 academic calendar plus one example extra window:
- DEL→DXB, 18–25 Aug 2026 (First Semester begins 21 Aug, classwork 25 Aug)
- DXB→DEL, 20–26 Dec 2026 (Compre ends 24 Dec)
- DEL→DXB, 15–22 Jan 2027 (Second Semester begins 22 Jan, Recess 11–21 Jan)
- DXB→DEL, 4–11 Nov 2026 (example Diwali-area window — delete if unused)

If `windows.json` is missing or unreadable, the script falls back to the
`DEFAULT_LEGS` list baked into `check_fares_ai.py`.

## One-off checks and trip history (manual runs)

From the Actions tab → **Run workflow**, you can:
- **Check an unexpected date once** without editing anything — fill in
  `extra_route` (e.g. `DEL-DXB`) and `extra_window` (e.g. `4-11 Nov 2026`).
  That leg is checked for this run only and logged to `fare_log.json`.
- **Log a trip you booked** — fill in `log_trip` as `route|date|price|note`
  (e.g. `DEL-DXB|2026-08-19|15500|booked on Emirates.com`). It appends to
  `trips.json`, your personal booking history (separate from the price log).

## Where the price data comes from (and free alternatives)

This tool pays the Anthropic API to **web-search** fares (Google Flights,
Emirates.com, Reddit/deal chatter) and reason about them — it is *not* a direct
Emirates connection. The Saver-fare and sale-chatter signals come from that
reasoning; no free flight API exposes them. See
[`docs/data-sources.md`](docs/data-sources.md) for the full survey of
alternative APIs (Amadeus, Skyscanner/RapidAPI, ExpertFlyer) and why the AI
route is the one that keeps every feature.

## Honest limitations

- Web-search-derived prices are a strong signal, not a guaranteed bookable
  fare — always confirm on Emirates.com before paying.
- If Claude's response doesn't parse as clean JSON on a given run (rare,
  but possible), that run is skipped rather than logging bad data — check
  the Actions tab logs if you notice a gap.
- Islamic-holiday-adjacent price effects (Eid dates) aren't hardcoded
  anywhere since exact 2026/27 dates depend on moon sighting — the AI
  check will still catch the resulting price moves even without the date
  being named in advance.
