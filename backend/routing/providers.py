"""Third-party integrations (all free, no API key):
  * Photon (OpenStreetMap)  - geocoding / autocomplete
  * OSRM                    - routing (up to 3 alternatives)
  * Open-Meteo              - hourly wind, rain, snowfall forecast
"""
import logging
import os
import time
from concurrent.futures import ThreadPoolExecutor

import requests
from django.core.cache import cache

from . import geometry

log = logging.getLogger(__name__)

PHOTON_URL = os.environ.get("PHOTON_URL", "https://photon.komoot.io/api/")
OSRM_URL = os.environ.get("OSRM_URL", "https://router.project-osrm.org")
OPEN_METEO_URL = os.environ.get("OPEN_METEO_URL", "https://api.open-meteo.com/v1/forecast")
# OSRM's public server only has a car profile; scale durations if you want a slower "truck" pace.
TRUCK_TIME_FACTOR = float(os.environ.get("TRUCK_TIME_FACTOR", "1.0"))
WEATHER_CHUNK = 50  # coordinates per Open-Meteo request

_session = requests.Session()
_session.headers["User-Agent"] = "weather-truck-routing/1.0 (hiring assessment)"


class ProviderError(Exception):
    """An upstream service failed or returned nothing usable."""


def _get_json(url, params, retries=3, timeout=25):
    last = None
    for attempt in range(retries):
        try:
            r = _session.get(url, params=params, timeout=timeout)
        except requests.RequestException as exc:
            last = exc
            time.sleep(0.6 * (attempt + 1))
            continue
        if r.status_code in (429, 502, 503, 504):
            last = f"HTTP {r.status_code}"
            time.sleep(0.8 * (attempt + 1))
            continue
        if r.status_code >= 400:
            try:
                body = r.json()
                detail = body.get("reason") or body.get("message") or r.text[:200]
            except ValueError:
                detail = r.text[:200]
            raise ProviderError(f"{url.split('/')[2]}: {detail}")
        return r.json()
    raise ProviderError(f"{url.split('/')[2]} is unavailable ({last})")


# ---------------------------------------------------------------- geocoding
def geocode(query, limit=6):
    key = "geo:" + query.strip().lower()
    cached = cache.get(key)
    if cached is not None:
        return cached
    data = _get_json(PHOTON_URL, {"q": query, "limit": limit, "lang": "en"})
    results = []
    for f in data.get("features", []):
        p = f.get("properties", {})
        lng, lat = f["geometry"]["coordinates"]
        parts = [p.get("name") or p.get("street"), p.get("city") or p.get("county"), p.get("state"), p.get("country")]
        label = ", ".join(dict.fromkeys(x for x in parts if x))
        if label:
            results.append({"label": label, "lat": lat, "lng": lng})
    cache.set(key, results, 86400)
    return results


# ------------------------------------------------------------------ routing
def finalize_route(coords, duration_s):
    cum = geometry.cumulative_miles(coords)
    return {"coords": coords, "cum": cum, "distance_mi": cum[-1], "duration_s": duration_s}


def _osrm(points, alternatives):
    path = ";".join(f"{lng:.6f},{lat:.6f}" for lat, lng in points)
    data = _get_json(
        f"{OSRM_URL}/route/v1/driving/{path}",
        {"overview": "full", "geometries": "geojson", "steps": "false", "alternatives": "3" if alternatives else "false"},
    )
    if data.get("code") != "Ok" or not data.get("routes"):
        raise ProviderError(f"No drivable route found ({data.get('code')})")
    return [
        finalize_route([(lat, lng) for lng, lat in r["geometry"]["coordinates"]], r["duration"] * TRUCK_TIME_FACTOR)
        for r in data["routes"]
    ]


def _synthesize_alternatives(origin, dest, routes, need):
    """OSRM often returns <3 alternatives. Fill the gap by routing via a waypoint pushed
    sideways off the main route, keeping only candidates that are genuinely different."""
    base = routes[0]
    total = base["distance_mi"]
    found = []
    attempts = [(0.5, 1, 0.15), (0.5, -1, 0.15), (0.4, 1, 0.3), (0.6, -1, 0.3), (0.5, 1, 0.3), (0.5, -1, 0.3)]
    for frac, side, off in attempts:
        if len(found) >= need:
            break
        c = geometry.point_at(base["coords"], base["cum"], total * frac)
        a = geometry.point_at(base["coords"], base["cum"], total * max(0, frac - 0.02))
        b = geometry.point_at(base["coords"], base["cum"], total * min(1, frac + 0.02))
        heading = geometry.bearing_deg(*a, *b)
        wp = geometry.destination_point(*c, (heading + 90 * side) % 360, min(off * total, 120))
        try:
            cand = _osrm([origin, wp, dest], False)[0]
        except ProviderError:
            continue
        if cand["distance_mi"] > base["distance_mi"] * 1.8:
            continue
        if any(geometry.overlap_fraction(cand["coords"], r["coords"]) > 0.85 for r in routes + found):
            continue
        found.append(cand)
    return found


def get_routes(origin, destination, want=3):
    o, d = (origin["lat"], origin["lng"]), (destination["lat"], destination["lng"])
    routes = _osrm([o, d], True)[:want]
    if len(routes) < want:
        routes += _synthesize_alternatives(o, d, routes, want - len(routes))
    routes.sort(key=lambda r: r["duration_s"])
    return routes


# ------------------------------------------------------------------ weather
def fetch_weather(points, start_date, end_date):
    """Hourly forecast per point, on a shared UTC hourly axis starting at start_date 00:00.
    Returns [{"wind": [...mph], "rain": [...in/hr], "snow": [...in/hr]}] in input order."""
    keys = [(round(lat, 2), round(lng, 2)) for lat, lng in points]
    unique = list(dict.fromkeys(keys))

    def ckey(k):
        return f"wx:{k[0]}:{k[1]}:{start_date}:{end_date}"

    found = {k: v for k in unique if (v := cache.get(ckey(k)))}
    missing = [k for k in unique if k not in found]
    chunks = [missing[i : i + WEATHER_CHUNK] for i in range(0, len(missing), WEATHER_CHUNK)]

    def run(chunk):
        data = _get_json(
            OPEN_METEO_URL,
            {
                "latitude": ",".join(str(k[0]) for k in chunk),
                "longitude": ",".join(str(k[1]) for k in chunk),
                "hourly": "wind_speed_10m,rain,snowfall",
                "wind_speed_unit": "mph",
                "precipitation_unit": "inch",
                "timezone": "UTC",
                "start_date": str(start_date),
                "end_date": str(end_date),
            },
        )
        items = data if isinstance(data, list) else [data]
        out = []
        for item in items:
            h = item.get("hourly") or {}
            wind = [x or 0.0 for x in h.get("wind_speed_10m", [])]
            if not wind:
                raise ProviderError("Weather service returned no forecast data for this time window")
            out.append(
                {
                    "wind": wind,
                    "rain": [x or 0.0 for x in h["rain"]],
                    "snow": [x or 0.0 for x in h["snowfall"]],
                }
            )
        return out

    if chunks:
        with ThreadPoolExecutor(max_workers=4) as pool:
            for chunk, res in zip(chunks, pool.map(run, chunks)):
                for k, item in zip(chunk, res):
                    found[k] = item
                    cache.set(ckey(k), item, 1800)
    return [found[k] for k in keys]
