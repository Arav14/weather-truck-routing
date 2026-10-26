"""Weather risk classification: thresholds and load rules from the assessment brief.

Boundary conventions (the brief's ranges leave the shared edges ambiguous):
  * wind:      <25 Low | 25-<35 Moderate | 35-<45 High | 45-<55 Severe | >=55 No Travel
  * rain/snow: upper edges inclusive, e.g. rain 0.25 -> Moderate, 0.50 -> High, 1.00 -> Severe;
               only values strictly above the last edge are No Travel (">1.00", ">3.0").
"""
from typing import NamedTuple

LOW, MODERATE, HIGH, SEVERE, NO_TRAVEL = range(5)
LEVEL_NAMES = ["Low", "Moderate", "High", "Severe", "No Travel"]


class Assessment(NamedTuple):
    level: int
    drivers: list


def wind_level(mph: float) -> int:
    if mph < 25:
        return LOW
    if mph < 35:
        return MODERATE
    if mph < 45:
        return HIGH
    if mph < 55:
        return SEVERE
    return NO_TRAVEL


def _precip_level(v: float, low: float, moderate: float, high: float, severe: float) -> int:
    if v < low:
        return LOW
    if v <= moderate:
        return MODERATE
    if v <= high:
        return HIGH
    if v <= severe:
        return SEVERE
    return NO_TRAVEL


def rain_level(in_per_hr: float) -> int:
    return _precip_level(in_per_hr, 0.10, 0.25, 0.50, 1.00)


def snow_level(in_per_hr: float) -> int:
    return _precip_level(in_per_hr, 0.5, 1.0, 2.0, 3.0)


def assess(wind_mph: float, rain_in_hr: float, snow_in_hr: float, weight_lb: float) -> Assessment:
    """Worst single-condition level, then escalated by the load rules."""
    by_condition = {
        "wind": wind_level(wind_mph),
        "rain": rain_level(rain_in_hr),
        "snow": snow_level(snow_in_hr),
    }
    level = max(by_condition.values())
    drivers = [name for name, lvl in by_condition.items() if lvl == level and lvl > LOW]

    load_level = None
    if wind_mph >= 55:
        load_level = NO_TRAVEL  # any load
    elif wind_mph >= 45 and weight_lb > 30_000:
        load_level = NO_TRAVEL  # 45-54 mph, heavy load
    elif 35 <= wind_mph < 45 and weight_lb > 40_000:
        load_level = SEVERE  # 35-44 mph, very heavy load
    if load_level is not None and load_level > level:
        level, drivers = load_level, ["wind + load"]
    return Assessment(level, drivers)
