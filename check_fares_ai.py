"""
DXB <-> DEL fare watch -- AI-driven mode.

Instead of a fixed price API, this calls the Anthropic API with web search
enabled and the same reasoning a careful human would apply: check Google
Flights / Emirates.com / current deal chatter, find the cheapest date in
each window, identify the fare family (Special/Saver/Flex) where visible,
and compare against the last run. This is what actually answers "is Saver
showing," which a plain price API can't.

Efficiency note: this asks for ONE best date per window per leg, not a
day-by-day scan -- three legs = a handful of searches per run, not dozens.
Keep the cron cadence (Mon/Wed/Fri by default) rather than running this
more often; fares don't move fast enough hour-to-hour to justify it, and
each run costs a small amount of real API spend.

Output: appends a structured record to fare_log.json (read directly by the
dashboard artifact via its raw GitHub URL) and emails you only when
something is actually notable (new low, Saver flips available, live sale).

What you can tune without touching this file:
  - windows.json    persistent list of legs to track (edit to add/remove dates
                    or extra windows). Falls back to DEFAULT_LEGS below if absent.
  - Manual run      the "Run workflow" button accepts an ad-hoc leg for a single
                    run (EXTRA_ROUTE / EXTRA_WINDOW / EXTRA_NOTE), and can log a
                    trip you booked (LOG_TRIP) into trips.json.
  - trips.json      your personal trip/booking history, for reference. Distinct
                    from fare_log.json, which is the price-check history.

Setup: see README.md. Needs ANTHROPIC_API_KEY, GMAIL_ADDRESS,
GMAIL_APP_PASSWORD as GitHub repo secrets.
"""

import os
import json
import smtplib
import requests
from datetime import datetime, timezone
from email.mime.text import MIMEText
from pathlib import Path

ANTHROPIC_API_KEY = os.environ["ANTHROPIC_API_KEY"]
GMAIL_ADDRESS = os.environ["GMAIL_ADDRESS"]
GMAIL_APP_PASSWORD = os.environ["GMAIL_APP_PASSWORD"]
ALERT_TO = os.environ.get("ALERT_TO", GMAIL_ADDRESS)

LOG_FILE = Path(__file__).parent / "fare_log.json"
WINDOWS_FILE = Path(__file__).parent / "windows.json"
TRIPS_FILE = Path(__file__).parent / "trips.json"
MODEL = "claude-sonnet-4-6"  # check https://docs.claude.com for the current model string if this errors

# ---- Default travel windows, from the BITS Pilani Dubai 2026-27 academic calendar ----
# These are the FALLBACK if windows.json is missing or unreadable. To track more
# dates or an extra window persistently, edit windows.json (same shape) -- no code
# change needed. For a one-off check, use the manual-run inputs (see load_legs()).
DEFAULT_LEGS = [
    {"route": "DEL-DXB", "window": "18-25 Aug 2026", "note": "Outbound: First Semester begins 21 Aug, classwork 25 Aug"},
    {"route": "DXB-DEL", "window": "20-26 Dec 2026", "note": "Winter return: Compre ends 24 Dec"},
    {"route": "DEL-DXB", "window": "15-22 Jan 2027", "note": "Back to Dubai: Second Semester begins 22 Jan (Recess 11-21 Jan)"},
]

SYSTEM_PROMPT = """You are tracking Emirates Economy fares on the Dubai (DXB) <-> Delhi (DEL) \
route for a BITS Pilani Dubai student traveling on a student budget.

For each leg given, use web search (Google Flights, Emirates.com, and any current deal/sale \
chatter -- travel deal blogs, r/IndiaTravel, r/dubai) to scan the whole window's price calendar \
(e.g. the Google Flights date grid) and find the SINGLE cheapest date to fly within it. You don't \
need a separate search per date -- one look at the date grid per leg is enough. If another date in \
the window is within ~10% of the cheapest, name it briefly in `note` so a near-miss cheap date isn't lost.

Weigh known price-risk windows: Diwali (6-10 Nov 2026) and Christmas/New Year (25 Dec-1 Jan) \
if they overlap or sit near a leg's window.

The traveler cares about total cost more than Skywards miles -- Saver fare is fine. Only note \
a pricier fare if it earns meaningfully more miles for a small price gap.

Respond with ONLY a JSON object, no preamble, no markdown fences, matching exactly this shape:

{
  "legs": [
    {
      "route": "DEL-DXB",
      "window": "18-25 Aug 2026",
      "best_date": "2026-08-20",
      "price": 950,
      "currency": "INR",
      "fare_family": "Saver",
      "saver_available": true,
      "source": "Google Flights",
      "sale_chatter": "none found",
      "recommendation": "book now",
      "note": "one short sentence, max ~15 words"
    }
  ]
}

recommendation must be exactly one of: "book now", "wait", "not enough data yet".
If you can't determine fare_family, use "unknown". If price cannot be found, omit that leg \
entirely rather than guessing.
"""


def load_legs():
    """Return the legs to check this run.

    Persistent legs come from windows.json (falling back to DEFAULT_LEGS if the
    file is missing or unreadable). A one-off ad-hoc leg can be injected for a
    single run via EXTRA_ROUTE / EXTRA_WINDOW / EXTRA_NOTE -- these are wired to
    the manual "Run workflow" button so you can check an unexpected date without
    editing anything.
    """
    if WINDOWS_FILE.exists():
        try:
            legs = json.loads(WINDOWS_FILE.read_text())
            if not isinstance(legs, list) or not legs:
                raise ValueError("windows.json must be a non-empty JSON list")
        except (json.JSONDecodeError, ValueError) as e:
            print(f"[warn] windows.json unreadable ({e}); using built-in defaults")
            legs = list(DEFAULT_LEGS)
    else:
        legs = list(DEFAULT_LEGS)

    extra_route = os.environ.get("EXTRA_ROUTE", "").strip()
    extra_window = os.environ.get("EXTRA_WINDOW", "").strip()
    if extra_route and extra_window:
        legs.append({
            "route": extra_route,
            "window": extra_window,
            "note": os.environ.get("EXTRA_NOTE", "").strip() or "Ad-hoc leg (manual run)",
        })
        print(f"[info] added ad-hoc leg: {extra_route} ({extra_window})")
    elif extra_route or extra_window:
        print("[warn] an ad-hoc leg needs BOTH EXTRA_ROUTE and EXTRA_WINDOW; ignoring")

    return legs


def log_trip():
    """Append a personal trip/booking record to trips.json, for reference.

    Triggered by the LOG_TRIP env var (manual run). Format:
        route|date|price|note     e.g.  DEL-DXB|2026-08-19|15500|booked on Emirates.com
    Only route and date are required. This is a log of trips YOU take -- kept
    separate from fare_log.json, which is the automated price-check history.
    """
    raw = os.environ.get("LOG_TRIP", "").strip()
    if not raw:
        return
    parts = [p.strip() for p in raw.split("|")]
    route = parts[0] if len(parts) > 0 else ""
    trip_date = parts[1] if len(parts) > 1 else ""
    if not route or not trip_date:
        print("[warn] LOG_TRIP needs at least 'route|date'; skipping")
        return

    price = None
    if len(parts) > 2 and parts[2]:
        try:
            price = float(parts[2])
        except ValueError:
            print(f"[warn] LOG_TRIP price '{parts[2]}' isn't a number; logging without price")

    entry = {
        "logged_at": datetime.now(timezone.utc).isoformat(),
        "route": route,
        "date": trip_date,
        "price": price,
        "currency": "INR",
        "note": parts[3] if len(parts) > 3 else "",
    }

    trips = []
    if TRIPS_FILE.exists():
        try:
            trips = json.loads(TRIPS_FILE.read_text())
            if not isinstance(trips, list):
                trips = []
        except json.JSONDecodeError:
            trips = []
    trips.append(entry)
    TRIPS_FILE.write_text(json.dumps(trips, indent=2) + "\n")
    print(f"[info] logged trip: {route} on {trip_date}")


def call_claude(legs):
    resp = requests.post(
        "https://api.anthropic.com/v1/messages",
        headers={
            "x-api-key": ANTHROPIC_API_KEY,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
        json={
            "model": MODEL,
            "max_tokens": 2000,
            "system": SYSTEM_PROMPT,
            "messages": [
                {"role": "user", "content": "Legs to check:\n" + json.dumps(legs, indent=2)}
            ],
            "tools": [{"type": "web_search_20250305", "name": "web_search"}],
        },
        timeout=120,
    )
    resp.raise_for_status()
    data = resp.json()
    text_blocks = [b["text"] for b in data.get("content", []) if b.get("type") == "text"]
    raw = "\n".join(text_blocks).strip()
    raw = raw.replace("```json", "").replace("```", "").strip()
    return json.loads(raw)


def load_log():
    if not LOG_FILE.exists():
        return []
    with open(LOG_FILE) as f:
        return json.load(f)


def save_log(log):
    with open(LOG_FILE, "w") as f:
        json.dump(log, f, indent=2)


def last_price(log, route, window):
    for record in reversed(log):
        for leg in record.get("legs", []):
            if leg["route"] == route and leg["window"] == window:
                return leg
    return None


def send_email(subject, body):
    msg = MIMEText(body)
    msg["Subject"] = subject
    msg["From"] = GMAIL_ADDRESS
    msg["To"] = ALERT_TO
    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as s:
        s.login(GMAIL_ADDRESS, GMAIL_APP_PASSWORD)
        s.send_message(msg)


def main():
    log_trip()
    legs = load_legs()
    log = load_log()
    result = call_claude(legs)
    checked_at = datetime.now(timezone.utc).isoformat()

    alerts = []
    for leg in result.get("legs", []):
        prev = last_price(log, leg["route"], leg["window"])
        if prev is None:
            alerts.append(f"First check — {leg['route']} ({leg['window']}): {leg['currency']} {leg['price']} on {leg['best_date']}, {leg['fare_family']}.")
        else:
            if leg["price"] < prev["price"]:
                pct = (1 - leg["price"] / prev["price"]) * 100
                alerts.append(f"Price DOWN {pct:.0f}% — {leg['route']} ({leg['window']}): now {leg['currency']} {leg['price']} (was {prev['price']}).")
            if leg.get("saver_available") and not prev.get("saver_available"):
                alerts.append(f"Saver just opened up — {leg['route']} ({leg['window']}), {leg['currency']} {leg['price']}.")
            if leg.get("sale_chatter") and leg["sale_chatter"].lower() not in ("none found", "none", "n/a", ""):
                alerts.append(f"Sale chatter — {leg['route']}: {leg['sale_chatter']}")
        if leg.get("recommendation") == "book now":
            alerts.append(f"Recommendation: BOOK NOW — {leg['route']} ({leg['window']}) at {leg['currency']} {leg['price']}.")

    log.append({"checked_at": checked_at, "legs": result.get("legs", [])})
    save_log(log)

    if alerts:
        send_email(f"Emirates DXB<->DEL: {len(alerts)} update(s)", "\n".join(alerts))
        print("\n".join(alerts))
    else:
        print("No notable change this run.")


if __name__ == "__main__":
    main()
