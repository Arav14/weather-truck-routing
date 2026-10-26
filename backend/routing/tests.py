import json
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from django.test import Client, SimpleTestCase

from . import analysis, geometry, providers, risk


class RiskTests(SimpleTestCase):
    def test_wind_bands(self):
        got = [risk.wind_level(v) for v in (0, 24.9, 25, 34.9, 35, 44.9, 45, 54.9, 55, 80)]
        self.assertEqual(got, [0, 0, 1, 1, 2, 2, 3, 3, 4, 4])

    def test_rain_and_snow_bands(self):
        self.assertEqual([risk.rain_level(v) for v in (0.05, 0.10, 0.25, 0.26, 0.50, 1.0, 1.01)], [0, 1, 1, 2, 2, 3, 4])
        self.assertEqual([risk.snow_level(v) for v in (0.4, 0.5, 1.0, 2.0, 3.0, 3.1)], [0, 1, 1, 2, 3, 4])

    def test_load_rules(self):
        self.assertEqual(risk.assess(55, 0, 0, 1_000).level, risk.NO_TRAVEL)  # any load
        self.assertEqual(risk.assess(50, 0, 0, 30_001).level, risk.NO_TRAVEL)
        self.assertEqual(risk.assess(50, 0, 0, 30_000).level, risk.SEVERE)  # not > 30,000
        self.assertEqual(risk.assess(40, 0, 0, 40_001).level, risk.SEVERE)  # escalated from High
        self.assertEqual(risk.assess(40, 0, 0, 40_000).level, risk.HIGH)
        self.assertEqual(risk.assess(10, 1.2, 0, 1_000).level, risk.NO_TRAVEL)  # rain alone

    def test_worst_condition_wins(self):
        self.assertEqual(risk.assess(26, 0.3, 0.6, 10_000).level, risk.HIGH)


class GeometryTests(SimpleTestCase):
    def test_segments_sum_to_total(self):
        for total, spacing in ((100, 25), (101, 25), (7, 10), (0, 10), (1000, 10)):
            miles = geometry.sample_miles(total, spacing)
            self.assertAlmostEqual(sum(geometry.segment_lengths(miles)), total)
            self.assertEqual(miles[-1], total if total > 0 else 0.0)

    def test_point_at_interpolates(self):
        coords = [(40.0, -100.0), (40.0, -99.0)]
        cum = geometry.cumulative_miles(coords)
        lat, lng = geometry.point_at(coords, cum, cum[-1] / 2)
        self.assertAlmostEqual(lng, -99.5, places=3)


def _fake_route(lat, duration_s):
    coords = [(lat, -100.0 + i * 0.1) for i in range(101)]  # ~ 530 mi east-west line
    return providers.finalize_route(coords, duration_s)


def _fake_weather(points, start, end):
    """Route B (lat 41) is calm; A (lat 40) has 40 mph wind; C (lat 42) has heavy rain."""
    n = ((end - start).days + 1) * 24
    out = []
    for lat, _ in points:
        wind, rain = (40.0, 0.0) if round(lat) == 40 else (5.0, 0.3) if round(lat) == 42 else (5.0, 0.0)
        out.append({"wind": [wind] * n, "rain": [rain] * n, "snow": [0.0] * n})
    return out


class PipelineTests(SimpleTestCase):
    dep = datetime.now(timezone.utc) + timedelta(hours=3)
    origin, dest = {"lat": 40, "lng": -100}, {"lat": 40, "lng": -90}

    def run_analysis(self, weight):
        routes = [_fake_route(40, 30_000), _fake_route(41, 33_000), _fake_route(42, 36_000)]
        with patch.object(providers, "get_routes", return_value=routes), patch.object(
            providers, "fetch_weather", side_effect=_fake_weather
        ):
            return analysis.analyze(self.origin, self.dest, self.dep, weight, 25)

    def test_heavy_load_avoids_windy_fast_route(self):
        res = self.run_analysis(45_000)  # 40 mph + >40k lb => Severe all along route A
        a, b, c = res["routes"]
        self.assertGreater(a["summary"]["severe_miles"], 500)
        self.assertEqual(b["summary"]["severe_miles"], 0)
        self.assertGreater(c["summary"]["high_miles"], 500)  # 0.3 in/hr rain => High
        self.assertEqual(res["recommendation"]["route_id"], "B")
        self.assertEqual(res["recommendation"]["ranking"], ["B", "C", "A"])

    def test_light_load_prefers_fast_route_over_rain(self):
        res = self.run_analysis(20_000)  # A is only High (wind), same as C; B is Low
        self.assertEqual(res["recommendation"]["route_id"], "B")
        self.assertEqual(res["routes"][0]["summary"]["severe_miles"], 0)

    def test_shape(self):
        res = self.run_analysis(40_000)
        r = res["routes"][0]
        self.assertEqual(r["checkpoints"][0]["mile"], 0)
        self.assertAlmostEqual(r["checkpoints"][-1]["mile"], r["distance_mi"], places=0)
        self.assertEqual(len(res["heat"]["points"][0]["levels"]), 49)
        self.assertAlmostEqual(sum(r["summary"]["miles_by_level"]), r["distance_mi"], delta=1)


class ApiTests(SimpleTestCase):
    def test_validation(self):
        c = Client()
        bad = c.post("/api/analyze", json.dumps({}), content_type="application/json")
        self.assertEqual(bad.status_code, 400)
        self.assertEqual(c.get("/api/health").json(), {"ok": True})
        self.assertEqual(c.get("/api/geocode?q=ab").json(), {"results": []})
