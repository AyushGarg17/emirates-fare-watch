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
MODEL = "claude-sonnet-4-6"  # check https://docs.claude.com for the current model string if this errors

# ---- Travel windows, from the BITS Pilani Dubai 2026-27 academic calendar ----
LEGS = [
    {"route": "DEL-DXB", "window": "18-25 Aug 2026", "note": "Outbound: First Semester begins 21 Aug, classwork 25 Aug"},
    {"route": "DXB-DEL", "window": "20-26 Dec 2026", "note": "Winter return: Compre ends 24 Dec"},
    {"route": "DEL-DXB", "window": "15-22 Jan 2027", "note": "Back to Dubai: Second Semester begins 22 Jan (Recess 11-21 Jan)"},
]

SYSTEM_PROMPT = """You are tracking Emirates Economy fares on the Dubai (DXB) <-> Delhi (DEL) \
route for a BITS Pilani Dubai student traveling on a student budget.

For each leg given, use web search (Google Flights, Emirates.com, and any current deal/sale \
chatter -- travel deal blogs, r/IndiaTravel, r/dubai) to find the SINGLE cheapest date to fly \
within that window. Do not enumerate every date -- one well-aimed search per leg is enough.

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
    log = load_log()
    result = call_claude(LEGS)
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
