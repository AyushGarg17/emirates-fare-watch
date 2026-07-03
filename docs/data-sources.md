# Data sources & free-API survey

Notes from surveying alternatives to "Claude + web search" for pulling Emirates
DXB⇄DEL fares. Short version: **no free (or even most paid) APIs reproduce the
Saver / fare-family + sale-chatter features** — that is why the AI route is
primary. A free API can, at best, supplement it with a raw-price cross-check.

_Last surveyed: July 2026._

## The core constraint

The features that make this tracker useful —
- **fare family / "is Saver open"** and
- **live sale-chatter** (deal blogs, r/IndiaTravel, r/dubai) —

are **not available from any self-serve flight-price API**. Fare-class /
booking-class inventory is GDS territory (ExpertFlyer, Sabre, Travelport), which
is subscription-based with no free developer tier — and ExpertFlyer itself lost
a chunk of its availability data in late 2023. Web search + an LLM is the only
low-cost way to get the Saver signal, so **Claude stays the primary source.**

## Options considered

| Source | Free? | Gives price? | Gives Saver / fare family? | Verdict |
|---|---|---|---|---|
| **Claude API + web search** (this repo) | ~$1/mo, not free | Yes (as-seen-online) | **Yes** | Primary. Only feature-complete option. |
| **Amadeus Self-Service** (`check_fares.py`) | Free tier | Yes, but sandbox/cached | No | ⚠️ **Being decommissioned 17 Jul 2026** — the self-service portal shuts down and keys deactivate. The repo's free fallback is effectively dead. Successor (Amadeus Quick Connect) is enterprise-only. |
| **Skyscanner official API** | No | Yes (live) | No | Partner-only; explicitly **excludes students, non-commercial, and low-traffic sites**. There is no official free student tier. |
| **"Sky Scrapper" on RapidAPI** (unofficial) | Free tier (~100 req/mo) | Yes | No | The "free Skyscanner API" you find is this: a third-party **scraper** relabeled with the Skyscanner name. Raw prices only, freshness varies, against Skyscanner ToS, can break anytime. Usable as a fragile free *cross-check*, not a dependable source. |
| **FlightAPI.io** | 20 free test calls (one-off) | Yes | No | Not a sustainable free tier. |
| **Aviationstack** | 100 free req/mo (live) | Mostly status/schedule, thin on fares | No | Wrong shape for fare tracking. |
| **Kiwi (Tequila) / Duffel** | Sandbox/test only | Test data | No | Production/live needs a partnership agreement. |
| **ExpertFlyer / AwardFares** | No | — | **Yes (fare-class buckets)** | The only thing that truly shows Saver inventory, but subscription, no free public API, and reduced coverage since 2023. |

## Recommendation

1. **Keep Claude as the primary source.** It is the only route that preserves
   Saver detection and sale-chatter. "All features, but free, through another
   route" is not achievable — that data simply isn't in free APIs.
2. **Optional free supplement:** the RapidAPI "Sky Scrapper" scraper could add a
   structured raw-price cross-check (does Claude's web-searched number roughly
   match a second source?). It fits the ~100-req/mo free tier only if we query
   *one cheapest-price per leg* (≈5 legs × 13 runs/mo ≈ 65 calls), **not** a
   day-by-day scan. It adds a new `RAPIDAPI_KEY` secret and a fragile dependency,
   and still gives **no** Saver data. Wire in only if a price sanity-check is
   worth the fragility.
3. **Retire `check_fares.py`'s relevance** after 17 Jul 2026 — the Amadeus
   free tier it depends on is going away.

## Sources

- [Amadeus to shut down self-service APIs portal — PhocusWire](https://www.phocuswire.com/amadeus-shut-down-self-service-apis-portal-developers)
- [Amadeus Self-Service API shutdown / migration to AQC](https://oneclicktraveltech.com/blogs/travel/amadeus-self-service-api-shutdown)
- [Skyscanner Partners — Travel API (partner-only)](https://www.partners.skyscanner.net/product/travel-api)
- [Sky Scrapper (unofficial) on RapidAPI](https://rapidapi.com/ntd119/api/sky-scanner3/pricing)
- [10 Best Flight APIs in 2026: free tiers & real pricing — Thunderbit](https://thunderbit.com/blog/best-flight-api-with-free-tiers)
- [ExpertFlyer flight availability / fare-class inventory](https://www.expertflyer.com/features/flight-availability)
