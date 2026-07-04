# CLAUDE.md — Emirates DXB⇄DEL fare watch

Context for any Claude Code session working in this repo.

## What this is

An automated Emirates DXB⇄DEL fare tracker. `check_fares_ai.py` calls the
Anthropic API with **web search** enabled to find the cheapest date per travel
window, detect Saver/fare-family and sale chatter, log to `fare_log.json`, and
email alerts on notable changes. A GitHub Actions workflow runs it Mon/Wed/Fri.
The repo is **public** so a dashboard can read `fare_log.json` via
`raw.githubusercontent.com`.

Repo: `AyushGarg17/emirates-fare-watch` (branch `main`).
Raw log: https://raw.githubusercontent.com/AyushGarg17/emirates-fare-watch/main/fare_log.json

## Key files

- `check_fares_ai.py` — primary script (Anthropic API + web search). Uses `MODEL = "claude-sonnet-4-6"`.
- `check_fares.py` — optional non-AI variant (Amadeus API). NOTE: Amadeus Self-Service is being decommissioned 2026-07-17, so this fallback is effectively dead.
- `windows.json` — the legs to track. **Edit this to add/remove dates or windows — no code change.** Falls back to `DEFAULT_LEGS` in the script if missing.
- `trips.json` — personal trip/booking history (separate from the price log).
- `.github/workflows/fare-check.yml` — schedule + manual `workflow_dispatch` inputs.
- `docs/data-sources.md` — survey of alternative flight APIs and why the AI route is the one that keeps every feature.

## Current state (2026-07-04)

- Deployed and public. Workflow + secrets wiring in place.
- **Not live yet:** the owner has Claude Pro but no Anthropic API key, so the three
  repo secrets (`ANTHROPIC_API_KEY`, `GMAIL_ADDRESS`, `GMAIL_APP_PASSWORD`) are **not set**.
- **To go live:** owner sets the secrets themselves (`gh secret set ...`); then trigger
  `gh workflow run "Fare check"`. No code rework needed.
- **Interim ($0):** a Claude session runs the fare check manually via web search and
  commits the result to `fare_log.json` (mirrors what the script's `call_claude` would
  produce; label the `source` as web-search-derived, not exact quotes).

## Manual runs (Actions tab → Run workflow)

- Ad-hoc one-off leg: fill `extra_route` (e.g. `DEL-DXB`) + `extra_window` (e.g. `4-11 Nov 2026`).
- Log a booked trip: `log_trip` as `route|date|price|note`.

## Conventions

- Do NOT change the existing academic-calendar windows without being asked; adding is fine.
- Prices from web search are a strong signal, not guaranteed bookable — always say so.
- Commit messages end with the Co-Authored-By trailer.

## Idea parked (not built)

A free, no-API-key deal-watcher (pure HTTP to Reddit JSON + deal-site RSS, using only
the Gmail secrets, on GitHub cron) for faster published-deal alerts. For sudden per-date
price drops, Google Flights price alerts are the recommended free tool.
