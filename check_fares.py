"""
DXB <-> DEL fare watch.

Queries the Amadeus Self-Service "Flight Offers Search" API (free tier) for
economy prices on DXB->DEL and DEL->DXB across the date windows defined
below, logs results to fare_log.csv, and emails a summary if:
  - it's the lowest price seen so far for that direction, or
  - the price dropped more than PRICE_DROP_ALERT_PCT since the last check.

This tracks overall Economy price movement reliably (it's an official,
documented API). It does NOT read Emirates' internal fare-family label
(Special / Saver / Flex) -- that's booking-class data, which only GDS-facing
tools like ExpertFlyer expose. Use this script for "catch a cheap fare"
alerts, and ExpertFlyer for "tell me when Saver specifically opens up."

Setup (see README.md for the full walkthrough):
  1. Get a free API key/secret from https://developers.amadeus.com
  2. Get a Gmail "app password" for sending mail
  3. Add both as GitHub repo secrets, run this on a schedule via
     .github/workflows/fare-check.yml
"""

import os
import csv
import json
import smtplib
import requests
from datetime import date, timedelta
from email.mime.text import MIMEText
from pathlib import Path

AMADEUS_KEY = os.environ["AMADEUS_API_KEY"]
AMADEUS_SECRET = os.environ["AMADEUS_API_SECRET"]
GMAIL_ADDRESS = os.environ["GMAIL_ADDRESS"]
GMAIL_APP_PASSWORD = os.environ["GMAIL_APP_PASSWORD"]
ALERT_TO = os.environ.get("ALERT_TO", GMAIL_ADDRESS)

# ---- Travel windows, pulled from the BITS Pilani Dubai 2026-27 academic calendar ----
ROUTES = [
    # Outbound to Dubai: First semester begins Aug 21, classwork begins Aug 25
    {"origin": "DEL", "destination": "DXB", "window_start": "2026-08-18", "window_end": "2026-08-25"},
    # Return to India for winter break: Compre ends Dec 24 -> must be back for
    # Second Semester on Jan 22 (Recess is Jan 11-21). Round trip inside this window.
    {"origin": "DXB", "destination": "DEL", "window_start": "2026-12-20", "window_end": "2026-12-26"},
    {"origin": "DEL", "destination": "DXB", "window_start": "2027-01-15", "window_end": "2027-01-22"},
    # No confirmed academic break around Diwali (it's a single holiday on a
    # Sunday) -- uncomment only if you're taking personal leave for it.
    # {"origin": "DXB", "destination": "DEL", "window_start": "2026-11-05", "window_end": "2026-11-09"},
]
PRICE_DROP_ALERT_PCT = 8  # email if price drops more than this % vs last check
LOG_FILE = Path(__file__).parent / "fare_log.csv"

AMADEUS_BASE = "https://test.api.amadeus.com"  # switch to api.amadeus.com on a paid plan


def get_token():
    resp = requests.post(
        f"{AMADEUS_BASE}/v1/security/oauth2/token",
        data={
            "grant_type": "client_credentials",
            "client_id": AMADEUS_KEY,
            "client_secret": AMADEUS_SECRET,
        },
    )
    resp.raise_for_status()
    return resp.json()["access_token"]


def daterange(start, end):
    d = date.fromisoformat(start)
    e = date.fromisoformat(end)
    while d <= e:
        yield d.isoformat()
        d += timedelta(days=1)


def cheapest_price(token, origin, destination, depart_date):
    """Returns the lowest Emirates economy offer for a single date, or None."""
    resp = requests.get(
        f"{AMADEUS_BASE}/v2/shopping/flight-offers",
        headers={"Authorization": f"Bearer {token}"},
        params={
            "originLocationCode": origin,
            "destinationLocationCode": destination,
            "departureDate": depart_date,
            "adults": 1,
            "travelClass": "ECONOMY",
            "includedAirlineCodes": "EK",
            "currencyCode": "INR",
            "max": 5,
        },
    )
    if resp.status_code != 200:
        print(f"  [warn] {origin}->{destination} {depart_date}: {resp.status_code} {resp.text[:200]}")
        return None
    offers = resp.json().get("data", [])
    if not offers:
        return None
    return min(float(o["price"]["grandTotal"]) for o in offers)


def load_previous_prices():
    if not LOG_FILE.exists():
        return {}
    best = {}
    with open(LOG_FILE) as f:
        for row in csv.DictReader(f):
            k = (row["origin"], row["destination"], row["depart_date"])
            price = float(row["price"])
            if k not in best or price < best[k]:
                best[k] = price
    return best


def append_log(rows):
    is_new = not LOG_FILE.exists()
    with open(LOG_FILE, "a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["checked_at", "origin", "destination", "depart_date", "price", "currency"])
        if is_new:
            w.writeheader()
        w.writerows(rows)


def send_email(subject, body):
    msg = MIMEText(body)
    msg["Subject"] = subject
    msg["From"] = GMAIL_ADDRESS
    msg["To"] = ALERT_TO
    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as s:
        s.login(GMAIL_ADDRESS, GMAIL_APP_PASSWORD)
        s.send_message(msg)
    print(f"  [mail] sent: {subject}")


def main():
    token = get_token()
    previous = load_previous_prices()
    new_rows = []
    alerts = []

    for route in ROUTES:
        origin, destination = route["origin"], route["destination"]
        for d in daterange(route["window_start"], route["window_end"]):
            price = cheapest_price(token, origin, destination, d)
            if price is None:
                continue
            checked_at = date.today().isoformat()
            new_rows.append({
                "checked_at": checked_at, "origin": origin, "destination": destination,
                "depart_date": d, "price": price, "currency": "INR",
            })
            key = (origin, destination, d)
            prev_best = previous.get(key)
            if prev_best is None:
                alerts.append(f"First price seen for {origin}->{destination} on {d}: INR {price:,.0f}")
            elif price < prev_best * (1 - PRICE_DROP_ALERT_PCT / 100):
                drop_pct = (1 - price / prev_best) * 100
                alerts.append(
                    f"Price drop {origin}->{destination} on {d}: INR {prev_best:,.0f} -> INR {price:,.0f} "
                    f"({drop_pct:.0f}% down)"
                )
            elif price < prev_best:
                previous[key] = price  # quietly track new lows without alerting on small dips

    append_log(new_rows)

    if alerts:
        body = "\n".join(alerts) + "\n\n(Full log: fare_log.csv in the repo)"
        send_email(f"Emirates DXB<->DEL: {len(alerts)} price alert(s)", body)
    else:
        print("No alert-worthy changes this run.")


if __name__ == "__main__":
    main()
