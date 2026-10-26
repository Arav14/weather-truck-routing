"""Pipeline: routes -> checkpoints -> ETAs -> weather -> risk -> ranking -> heatmap data."""
from datetime import datetime, time, timedelta, timezone

from . import geometry, providers, risk

HEAT_HOURS = 48
MILE_TOLERANCE = 5.0  # route differences smaller than this are treated as ties...
RISK_TOLERANCE = 0.1  # ...so that travel time can break near-ties (the brief's "balance")
ROUTE_IDS = "ABC"

# Ranking priority. No Travel is ranked first: a route you cannot drive loses to any drivable one.
CRITERIA = [
    ("no_travel_miles", "No Travel miles"),
    ("severe_miles", "Severe miles"),
    ("high_miles", "High miles"),
    ("avg_risk", "average risk"),
    ("duration_s", "travel time"),
]


def rank_key(m):
    return (
        round(m["no_travel_miles"] / MILE_TOLERANCE),
        round(m["severe_miles"] / MILE_TOLERANCE),
        round(m["high_miles"] / MILE_TOLERANCE),
        round(m["avg_risk"] / RISK_TOLERANCE),
        m["duration_s"],
    )


def _fmt(field, v):
    if field.endswith("miles"):
        return f"{v:.0f} mi"
    if field == "avg_risk":
        return f"{v:.2f}"
    h, m = divmod(int(v // 60), 60)
    return f"{h}h {m:02d}m"


def _reason(ranked):
    if len(ranked) == 1:
        return "Only one route was available."
    best, nxt = ranked[0], ranked[1]
    kb, kn = rank_key(best["metrics"]), rank_key(nxt["metrics"])
    for i, (field, label) in enumerate(CRITERIA):
        if kb[i] != kn[i]:
            if field == "duration_s":
                return (
                    f"Weather risk is equivalent across the top routes, so Route {best['id']} wins on "
                    f"travel time ({_fmt(field, best['metrics'][field])} vs {_fmt(field, nxt['metrics'][field])})."
                )
            return (
                f"Lowest {label}: {_fmt(field, best['metrics'][field])} vs "
                f"{_fmt(field, nxt['metrics'][field])} on Route {nxt['id']}."
            )
    return "Routes are equivalent on every criterion."


def analyze(origin, destination, departure, weight_lb, interval_mi):
    dep = departure.astimezone(timezone.utc)
    routes = providers.get_routes(origin, destination)

    # 1) checkpoints + ETAs (constant average speed along the route)
    for r in routes:
        total = r["distance_mi"]
        r["miles"] = geometry.sample_miles(total, interval_mi)
        r["cps"] = []
        for m in r["miles"]:
            lat, lng = geometry.point_at(r["coords"], r["cum"], m)
            frac = m / total if total > 0 else 0.0
            r["cps"].append({"mile": m, "lat": lat, "lng": lng, "eta": dep + timedelta(seconds=r["duration_s"] * frac)})

    # 2) one weather fetch covering departure..max(ETA, +48h)
    heat_start = dep.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1 if dep.minute >= 30 else 0)
    last_eta = max(cp["eta"] for r in routes for cp in r["cps"])
    window_end = max(heat_start + timedelta(hours=HEAT_HOURS), last_eta) + timedelta(hours=1)
    t0 = datetime.combine(dep.date(), time.min, tzinfo=timezone.utc)
    points = [(cp["lat"], cp["lng"]) for r in routes for cp in r["cps"]]
    wx = providers.fetch_weather(points, dep.date(), window_end.date())

    clamped = False

    def hour_index(t, n):
        nonlocal clamped
        i = round((t - t0).total_seconds() / 3600)
        if i < 0 or i >= n:
            clamped = True
        return min(max(i, 0), n - 1)

    heat_base = int((heat_start - t0).total_seconds() // 3600)
    k = 0
    out_routes, heat_points = [], []
    for idx, r in enumerate(routes):
        rid = ROUTE_IDS[idx]
        seg = geometry.segment_lengths(r["miles"])
        by_level = [0.0] * 5
        cps_out = []
        for cp, seg_mi in zip(r["cps"], seg):
            w = wx[k]
            k += 1
            n = len(w["wind"])
            i = hour_index(cp["eta"], n)
            a = risk.assess(w["wind"][i], w["rain"][i], w["snow"][i], weight_lb)
            by_level[a.level] += seg_mi
            cps_out.append(
                {
                    "mile": round(cp["mile"], 1),
                    "lat": round(cp["lat"], 5),
                    "lng": round(cp["lng"], 5),
                    "eta": cp["eta"].isoformat(),
                    "wind_mph": round(w["wind"][i], 1),
                    "rain_in_hr": round(w["rain"][i], 2),
                    "snow_in_hr": round(w["snow"][i], 2),
                    "level": a.level,
                    "level_name": risk.LEVEL_NAMES[a.level],
                    "drivers": a.drivers,
                }
            )
            # 0-48h heatmap: risk at this location for each hour after departure
            levels = "".join(
                str(risk.assess(w["wind"][j], w["rain"][j], w["snow"][j], weight_lb).level)
                for j in (min(heat_base + h, n - 1) for h in range(HEAT_HOURS + 1))
            )
            heat_points.append({"route": rid, "lat": round(cp["lat"], 4), "lng": round(cp["lng"], 4), "levels": levels})

        total = r["distance_mi"]
        avg = sum(lvl * mi for lvl, mi in enumerate(by_level)) / total if total > 0 else float(cps_out[0]["level"])
        metrics = {
            "no_travel_miles": by_level[risk.NO_TRAVEL],
            "severe_miles": by_level[risk.SEVERE],
            "high_miles": by_level[risk.HIGH],
            "moderate_miles": by_level[risk.MODERATE],
            "avg_risk": avg,
            "duration_s": r["duration_s"],
        }
        out_routes.append(
            {
                "id": rid,
                "distance_mi": round(total, 1),
                "duration_s": round(r["duration_s"]),
                "arrival": (dep + timedelta(seconds=r["duration_s"])).isoformat(),
                "geometry": [[round(a, 5), round(b, 5)] for a, b in geometry.downsample(r["coords"])],
                "summary": {
                    "miles_by_level": [round(x, 1) for x in by_level],
                    "no_travel_miles": round(metrics["no_travel_miles"], 1),
                    "severe_miles": round(metrics["severe_miles"], 1),
                    "high_miles": round(metrics["high_miles"], 1),
                    "moderate_miles": round(metrics["moderate_miles"], 1),
                    "avg_risk": round(avg, 2),
                    "worst_level": max(c["level"] for c in cps_out),
                },
                "checkpoints": cps_out,
                "metrics": metrics,
            }
        )

    ranked = sorted(out_routes, key=lambda r: rank_key(r["metrics"]))
    best = ranked[0]
    advisory = None
    if best["metrics"]["no_travel_miles"] > 0:
        advisory = "Every route has No Travel conditions at the forecast time. Consider a different departure time."
    elif best["metrics"]["severe_miles"] > 0:
        advisory = "Even the best route has Severe segments. Consider a different departure time."
    reason = _reason(ranked)
    ranking = [r["id"] for r in ranked]
    for r in out_routes:
        del r["metrics"]

    return {
        "routes": out_routes,
        "recommendation": {
            "route_id": best["id"],
            "ranking": ranking,
            "reason": reason,
            "advisory": advisory,
        },
        "heat": {"hours": HEAT_HOURS, "interval_mi": interval_mi, "start": heat_start.isoformat(), "points": heat_points},
        "meta": {
            "departure": dep.isoformat(),
            "weight_lb": weight_lb,
            "interval_mi": interval_mi,
            "forecast_clamped": clamped,
        },
    }
